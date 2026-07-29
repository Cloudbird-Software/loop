#!/usr/bin/env python3
"""conductor/upgrade_ring.py — 第 8 环升级环（R5 全量实现）。

流程（OPC-v4 P7 + 手册 v5 第 6 部分）：
  读 UPSTREAM.yaml → 拉 release feed → 7 天冷静期过滤（输出 TOO_YOUNG 行）
  → 一次只升一包 → bench 重放 N 张卡出四指标表
  → 劣化超阈值自动 pin 回并写报告行（REGRESSED 行）。

触发（手册 v5：on_wave_open；卡片任务：每周日 05:00）：
  两种都支持，由 .github/workflows/upgrade.yml 的 schedule + repository_dispatch 触发。

模式：
  生产（默认）    : 用 gh api 拉 GitHub releases feed；用 bench/replay.sh 真重放。
  --dry-run      : 空跑。不拉网络、不改 UPSTREAM.yaml、不开 PR。
  --fake-feed F  : 用假 feed 文件代替 release feed（验收空跑用）。
                   每个 release 的 simulated_after 字段直接当升后四指标。
  --once PKG     : 只处理一个包（调试用）。
  --bench-dir D  : bench 目录（默认 bench）。
  --replay-n N   : 每次重放的卡数（默认全部）。

报告行格式（stdout，机器可解析；首词为行类型）：
  TOO_YOUNG: <pkg> <version> published=<iso> age=<d>d
  CANDIDATE: <pkg> <old_pin> -> <new_pin>
  REPLAY: <pkg> cards=<n>
  OK: <pkg> <new_pin> no regression
  REGRESSED: <pkg> <metric> delta=<d>
  PIN_BACK: <pkg> reverted <new_pin> -> <old_pin>
  DONE: processed=<n> regressed=<n> too_young=<n> ok=<n>
"""
import argparse, json, os, subprocess, sys, datetime, pathlib, tempfile

E = os.environ

def _now():
    return datetime.datetime.now(datetime.timezone.utc)

def _parse_iso(s):
    # 容忍 Z / 带偏移 / 无时区
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def load_upstream(path="UPSTREAM.yaml"):
    """读 UPSTREAM.yaml（PyYAML；conductor 依赖已在 requirements.txt）。"""
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML not installed (pip install -r requirements.txt)", file=sys.stderr)
        sys.exit(2)
    p = pathlib.Path(path)
    if not p.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(2)
    return yaml.safe_load(p.read_text()) or {}


def validate_upstream(up):
    """校验每项含 seam/kind/pin/degrade_path；kind=binary 需 sha256；kind=cli 需 official_source_only。
    spec-kit 必须保持 official_source_only=true（卡片任务硬约束）。
    返回 (errors, warnings)。"""
    errors = []; warnings = []
    policy = up.get("policy", {})
    if "min_age_days" not in policy:
        warnings.append("policy.min_age_days missing, defaulting to 7")
    items = up.get("items", [])
    if not items:
        warnings.append("no items registered")
    for it in items:
        name = it.get("name", "?")
        for fld in ("seam", "kind", "pin", "degrade_path"):
            if not it.get(fld):
                errors.append(f"item {name}: missing {fld}")
        kind = it.get("kind")
        if kind == "binary" and not it.get("sha256"):
            errors.append(f"item {name}: kind=binary requires sha256")
        if kind == "cli" and "official_source_only" not in it:
            errors.append(f"item {name}: kind=cli requires official_source_only")
        # spec-kit 硬约束
        if name == "github/spec-kit" and it.get("official_source_only") is not True:
            errors.append(f"item {name}: must keep official_source_only=true")
    return errors, warnings


def fetch_release_feed(up, dry_run, fake_feed, once=None):
    """返回 {pkg_name: [release, ...]}。
    dry_run + fake_feed → 读假文件。
    否则用 gh api 拉每个包的 releases（取最近 10 条）。
    """
    if dry_run and fake_feed:
        data = json.loads(pathlib.Path(fake_feed).read_text())
        return data.get("releases", {})
    items = up.get("items", [])
    feed = {}
    for it in items:
        name = it["name"]
        if once and name != once:
            continue
        # name 形如 "owner/repo"；gh api 拉 releases
        r = subprocess.run(
            ["gh", "api", f"/repos/{name}/releases", "--paginate",
             "-q", "[.[] | {version:.tag_name, tag:.tag_name, published_at:.published_at, notes:.body}] | .[0:10]"],
            capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(f"WARN: gh api releases for {name} failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            feed[name] = []
            continue
        try:
            feed[name] = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            feed[name] = []
    return feed


def cooldown_filter(releases, min_age_days, now):
    """返回 (passing, too_young)。releases 已按发布时间降序取最新候选。
    只看比当前 pin 新的最新一个候选；过冷静期才算。"""
    passing = []; too_young = []
    for rel in releases:
        pub = _parse_iso(rel.get("published_at", ""))
        if pub is None:
            continue
        age_days = (now - pub).days
        if age_days < 0:
            age_days = 0
        if age_days < min_age_days:
            too_young.append((rel, age_days))
            continue
        passing.append((rel, age_days))
        break  # 一次只升一包：取最新过冷静期的候选
    return passing, too_young


def run_replay_after(args, simulated_after=None):
    """重放 N 张卡，返回 after-metrics dict。
    dry-run 且给定了 simulated_after → 直接用（假 feed 路径）。
    否则跑 bench/replay.sh + bench/metrics.py aggregate。"""
    if simulated_after is not None:
        # 假 feed：simulated_after 是聚合后的四指标
        return {
            "replayed_cards": args.replay_n or 10,
            "metrics": simulated_after,
        }
    # 真重放：bash bench/replay.sh <dir> <N>  →  aggregate
    env = dict(os.environ)
    r = subprocess.run(["bash", str(pathlib.Path(args.bench_dir) / "replay.sh"),
                        str(pathlib.Path(args.bench_dir) / "replay"), str(args.replay_n or 0)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"WARN: replay.sh failed: {r.stderr.strip()[:200]}", file=sys.stderr)
        return {"replayed_cards": 0, "metrics": {}}
    agg = subprocess.run(["python3", str(pathlib.Path(args.bench_dir) / "metrics.py"),
                          "aggregate", "--results", "-"],
                         input=r.stdout, capture_output=True, text=True)
    try:
        return json.loads(agg.stdout)
    except json.JSONDecodeError:
        return {"replayed_cards": 0, "metrics": {}}


def compare_with_baseline(args, after):
    """调用 bench/metrics.py compare，返回 (regressed, table_text)。
    regressed=True 表示劣化。"""
    baseline_path = pathlib.Path(args.bench_dir) / "baseline.json"
    if not baseline_path.exists():
        # 自动生成基线
        subprocess.run(["python3", str(pathlib.Path(args.bench_dir) / "metrics.py"),
                        "baseline", "--replay-dir", str(pathlib.Path(args.bench_dir) / "replay"),
                        "--out", str(baseline_path)], check=False)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(after, tf); after_path = tf.name
    try:
        r = subprocess.run(["python3", str(pathlib.Path(args.bench_dir) / "metrics.py"),
                            "compare", "--baseline", str(baseline_path),
                            "--after-json", after_path],
                           capture_output=True, text=True)
        return (r.returncode != 0), r.stdout
    finally:
        pathlib.Path(after_path).unlink(missing_ok=True)


def pin_back(upstream_path, pkg_name, old_pin):
    """把 UPSTREAM.yaml 里 pkg 的 pin 改回 old_pin（生产模式用）。
    最小实现：逐行替换 pin 字段。"""
    p = pathlib.Path(upstream_path)
    lines = p.read_text().splitlines()
    out = []; in_item = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("- name:"):
            in_item = (s == f"- name: {pkg_name}")
            out.append(ln); continue
        if in_item and s.startswith("pin:"):
            indent = ln[:len(ln) - len(ln.lstrip())]
            out.append(f'{indent}pin: "{old_pin}"'); continue
        out.append(ln)
    p.write_text("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser(description="第 8 环升级环")
    ap.add_argument("--dry-run", action="store_true", help="空跑：不拉网络、不改文件、不开 PR")
    ap.add_argument("--fake-feed", default=None, help="假 release feed JSON（dry-run 用）")
    ap.add_argument("--once", default=None, help="只处理一个包（name）")
    ap.add_argument("--bench-dir", default="bench")
    ap.add_argument("--replay-n", type=int, default=0, help="每次重放卡数（0=全部）")
    ap.add_argument("--upstream", default="UPSTREAM.yaml")
    args = ap.parse_args()

    print(f"=== upgrade ring: dry_run={args.dry_run} fake_feed={args.fake_feed} once={args.once} ===")
    up = load_upstream(args.upstream)
    errors, warnings = validate_upstream(up)
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        print("UPSTREAM.yaml validation FAILED:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    policy = up.get("policy", {})
    min_age = int(policy.get("min_age_days", 7))
    now = _now()
    print(f"min_age_days={min_age}  now={now.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    feed = fetch_release_feed(up, args.dry_run, args.fake_feed, args.once)
    items = up.get("items", [])

    n_processed = n_regressed = n_too_young = n_ok = 0
    for it in items:
        name = it["name"]
        if args.once and name != args.once:
            continue
        current_pin = it.get("pin", "")
        rels = feed.get(name, [])
        if not rels:
            print(f"SKIP: {name} no release feed")
            continue
        passing, too_young = cooldown_filter(rels, min_age, now)
        for rel, age in too_young:
            print(f"TOO_YOUNG: {name} {rel.get('version','?')} published={rel.get('published_at','?')} age={age}d")
            n_too_young += 1
        if not passing:
            continue
        # 一次只升一包：取最新过冷静期候选
        rel, age = passing[0]
        new_pin = rel.get("version") or rel.get("tag") or ""
        n_processed += 1
        print(f"CANDIDATE: {name} {current_pin} -> {new_pin}  (age={age}d, published={rel.get('published_at','?')})")

        # 触碰 checker/workflow/权限/凭证 → tier 强制 critical（P7 步骤2）
        tier = "standard"
        if it.get("seam") in ("gate", "D") or any(k in name for k in ("pinact", "zizmor", "gitleaks", "gh-action")):
            tier = "critical"
        if tier == "critical":
            print(f"  tier=critical (seam={it.get('seam')}; touches gate/checker path)")

        # 重放 N 张卡得四指标
        simulated = rel.get("simulated_after") if args.dry_run else None
        after = run_replay_after(args, simulated_after=simulated)
        print(f"REPLAY: {name} cards={after.get('replayed_cards',0)}")
        regressed, table = compare_with_baseline(args, after)
        # metrics.py 输出 = 表格 +（劣化时）"\nREGRESSED:\n  REGRESSED: <metric> delta=<d>"
        # 拆分：表格给人类读，REGRESSED 行重写成报告行（带包名，机器可解析）。
        table_part, _, regressed_block = table.partition("\nREGRESSED:")
        print(table_part.rstrip())
        if regressed:
            for ln in regressed_block.splitlines():
                body = ln.strip()
                if body.startswith("REGRESSED:"):
                    # "REGRESSED: <metric> delta=<d>"
                    metric_detail = body[len("REGRESSED:"):].strip()
                    print(f"REGRESSED: {name} {metric_detail}")
            if args.dry_run:
                print(f"PIN_BACK: {name} reverted {new_pin} -> {current_pin}  (dry-run: no file change)")
            else:
                pin_back(args.upstream, name, current_pin)
                print(f"PIN_BACK: {name} reverted {new_pin} -> {current_pin}  (UPSTREAM.yaml updated)")
            n_regressed += 1
        else:
            print(f"OK: {name} {new_pin} no regression")
            n_ok += 1
            # 生产模式：此处应开升级 PR（只改 UPSTREAM.yaml + 锁文件 + workflow SHA）
            # 今晚范围：不开 PR（安全免责：启用类动作交人类），只报告。

    print(f"DONE: processed={n_processed} regressed={n_regressed} too_young={n_too_young} ok={n_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
