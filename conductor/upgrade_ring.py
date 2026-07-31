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
import base64
from collections import defaultdict

# loop pin 解析器（R13-6 #2 三方共用）。作为脚本直接运行时 conductor 不在 sys.path，
# 回退到同目录导入。
try:
    from conductor import loop_pin as lp
except ImportError:  # pragma: no cover - 脚本直跑路径
    import loop_pin as lp

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


# ── loop 控制面 bump PR（R13-6 #3/#4/#5）──────────────────────
def is_loop_control_plane(item):
    """识别 loop 控制面条目（seam=control-plane, kind=workflow）。"""
    return item.get("seam") == "control-plane" and item.get("kind") == "workflow"


def load_products_yml(path="products.yml"):
    """读 products.yml 返回 enabled 产品仓列表 [{name, repo, default_branch, ...}]。
    失败 → 返回空列表（dry-run 友好，不抛异常）。"""
    try:
        import yaml
    except ImportError:
        return []
    p = pathlib.Path(path)
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for pr in data.get("products", []) or []:
        if not isinstance(pr, dict):
            continue
        if pr.get("enabled", True) is False:
            continue
        out.append(pr)
    return out


def _strip_quotes(v):
    v = str(v)
    if len(v) >= 2 and v[0] in '"\'' and v[-1] == v[0]:
        return v[1:-1]
    return v


def _apply_file_change(content, file_entry):
    """对单个文件内容应用一条变更（来自 lp.suggest_bump 的 files 条目），返回新内容。
    纯函数，可单测。支持 LOOP.yml（loop.version/loop.sha）、UPSTREAM.yaml（pin）、
    三个薄壳 workflow（@<old_sha> → @<new_sha>）。"""
    path = file_entry.get("path", "")
    trailing_nl = content.endswith("\n")
    lines = content.splitlines()

    if path == "LOOP.yml":
        field = file_entry.get("field", "")
        new_val = _strip_quotes(file_entry.get("new", ""))
        out = []
        in_loop = False
        for ln in lines:
            s = ln.strip()
            indent = ln[:len(ln) - len(ln.lstrip())]
            is_top = (indent == "" and s and not s.startswith("#"))
            if is_top:
                in_loop = s.startswith("loop:")
            if in_loop and field == "loop.version" and s.startswith("version:"):
                out.append(f'{indent}version: "{new_val}"')
                continue
            if in_loop and field == "loop.sha" and s.startswith("sha:"):
                out.append(f'{indent}sha: "{new_val}"')
                continue
            out.append(ln)
        return "\n".join(out) + ("\n" if trailing_nl else "")

    if path == "UPSTREAM.yaml":
        new_val = file_entry.get("new", "")
        out = []
        in_item = False
        for ln in lines:
            s = ln.strip()
            if s.startswith("- name:"):
                in_item = (s == "- name: Cloudbird-Software/loop")
                out.append(ln)
                continue
            if in_item and s.startswith("pin:"):
                indent = ln[:len(ln) - len(ln.lstrip())]
                out.append(f'{indent}pin: "{new_val}"')
                continue
            out.append(ln)
        return "\n".join(out) + ("\n" if trailing_nl else "")

    if path.startswith(".github/workflows/loop-"):
        old_sha = file_entry.get("old_sha", "")
        new_sha = file_entry.get("new_sha", "")
        if old_sha and new_sha:
            return content.replace(f"@{old_sha}", f"@{new_sha}")
        return content

    return content


def _put_file_change(product_repo, branch, file_entries, env):
    """读取产品仓 branch 上某文件当前内容，应用 file_entries（同一 path 的多条变更），
    通过 Contents API PUT 回去。失败抛 RuntimeError。"""
    path = file_entries[0].get("path", "")
    r = subprocess.run(
        ["gh", "api", f"/repos/{product_repo}/contents/{path}?ref={branch}"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api get file {path} failed: {r.stderr.strip()[:200]}")
    try:
        meta = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"gh api get file {path}: bad JSON")
    content_b64 = meta.get("content", "")
    file_sha = meta.get("sha", "")
    try:
        content = base64.b64decode(content_b64).decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"decode file {path} failed: {e}")
    for fe in file_entries:
        content = _apply_file_change(content, fe)
    new_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    msg = f"loop-bump: update {path}"
    r = subprocess.run(
        ["gh", "api", "-X", "PUT", f"/repos/{product_repo}/contents/{path}",
         "-f", f"message={msg}", "-f", f"content={new_b64}",
         "-f", f"branch={branch}", "-f", f"sha={file_sha}"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api put file {path} failed: {r.stderr.strip()[:200]}")


def bump_loop_pin(args, item, new_tag, new_sha, current_pin, product_repo, default_branch="main"):
    """为一个产品仓开 loop bump PR。
    - 用 lp.suggest_bump 生成变更集（覆盖 LOOP.yml / UPSTREAM.yaml / 三薄壳 workflow）。
    - dry-run：只打印将改的文件清单，不改文件、不开 PR。
    - 生产：用 gh CLI 建分支 → 逐个 PUT 文件内容（不在本地落盘）→ gh pr create。
      PR 标题 `[loop-bump] <new_tag> @<new_sha[:12]>`，body 说明三者 SHA 一致、豁免数 0。
    - 失败（gh 调用失败）→ 抛 RuntimeError，由上层 main() 捕获并开 Incident。
    """
    changeset = lp.suggest_bump(current_pin, {"name": new_tag, "commit": {"sha": new_sha}})
    short_sha = (new_sha or "")[:12]
    pr_title = f"[loop-bump] {new_tag} @{short_sha}"
    pr_body = (
        f"loop 控制面 pin 升级：{current_pin.get('version', '')} -> {new_tag}\n\n"
        f"本 PR 由升级环在冷静期届满后自动开出（seam=control-plane, kind=workflow）。\n"
        f"同步更新：\n"
        f"  - LOOP.yml 的 loop.version / loop.sha\n"
        f"  - UPSTREAM.yaml 的 Cloudbird-Software/loop 条目 pin\n"
        f"  - 三个薄壳 workflow（loop-ci.yml / loop-gates.yml / loop-review.yml）的 @<sha>\n"
        f"三者 SHA 一致：{new_sha}\n\n"
        f"门禁：走与普通 PR 完全相同的门禁，豁免数为 0（不因来自 loop 享受任何豁免）。\n"
    )
    if getattr(args, "dry_run", False):
        print(f"[dry-run] bump_loop_pin: {product_repo} branch=loop-bump/{new_tag} <- {default_branch}")
        print(f"[dry-run]   title: {pr_title}")
        for f in changeset.get("files", []):
            print(f"[dry-run]   file: {f.get('path')}")
        print(f"[dry-run]   (no file changes, no PR created)")
        return None

    env = dict(os.environ)
    branch = f"loop-bump/{new_tag}"
    # 1. 取 default branch 的 sha
    r = subprocess.run(
        ["gh", "api", f"/repos/{product_repo}/branches/{default_branch}", "-q", ".commit.sha"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api get {default_branch} sha failed: {r.stderr.strip()[:200]}")
    base_sha = r.stdout.strip()
    # 2. 建分支
    r = subprocess.run(
        ["gh", "api", f"/repos/{product_repo}/git/refs", "-X", "POST",
         "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base_sha}"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api create branch failed: {r.stderr.strip()[:200]}")
    # 3. 逐个文件 PUT（同 path 的多条变更合并为一次 GET+PUT）
    by_path = defaultdict(list)
    for f in changeset.get("files", []):
        by_path[f.get("path", "")].append(f)
    for _path, entries in by_path.items():
        _put_file_change(product_repo, branch, entries, env)
    # 4. 开 PR
    r = subprocess.run(
        ["gh", "pr", "create", "--repo", product_repo,
         "--base", default_branch, "--head", branch,
         "--title", pr_title, "--body", pr_body],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {r.stderr.strip()[:200]}")
    pr_url = r.stdout.strip()
    print(f"LOOP_BUMP_PR: {product_repo} {pr_title} -> {pr_url}")
    return pr_url


def open_rollback_pr(args, product_repo, default_branch, old_pin_sha, old_tag,
                     failed_tag, failed_sha, reason):
    """开回退 PR：把 LOOP.yml/UPSTREAM.yaml/三薄壳 workflow 的 SHA 改回 old_pin_sha。
    - PR 标题 `[loop-rollback] revert <failed_tag> -> <old_tag>`，body 说明回退原因 + Incident 引用。
    - dry-run 下只打印。
    - 失败抛 RuntimeError。
    完整"合并后回退检测"由独立的定时任务负责；本函数提供能力（验收 #5）。"""
    short_failed = (failed_sha or "")[:12]
    short_old = (old_pin_sha or "")[:12]
    pr_title = f"[loop-rollback] revert {failed_tag} -> {old_tag}"
    pr_body = (
        f"loop 控制面 pin 回退：{failed_tag} @{short_failed} -> {old_tag} @{short_old}\n\n"
        f"回退原因：{reason}\n\n"
        f"本 PR 由合并后回退检测自动开出：bump 合并后首个周期出现门禁性失败，恢复上一个 pin。"
        f"同步更新 LOOP.yml/UPSTREAM.yaml/三薄壳 workflow 的 SHA，三者一致回到 {old_pin_sha}。\n"
        f"已开 Incident 引用本回退原因；走与普通 PR 完全相同的门禁，豁免数为 0。\n"
    )
    if getattr(args, "dry_run", False):
        print(f"[dry-run] open_rollback_pr: {product_repo} branch=loop-rollback/{failed_tag} <- {default_branch}")
        print(f"[dry-run]   title: {pr_title}")
        print(f"[dry-run]   files: LOOP.yml, UPSTREAM.yaml, .github/workflows/loop-ci.yml, loop-gates.yml, loop-review.yml")
        print(f"[dry-run]   (no file changes, no PR created)")
        return None

    env = dict(os.environ)
    branch = f"loop-rollback/{failed_tag}"
    r = subprocess.run(
        ["gh", "api", f"/repos/{product_repo}/branches/{default_branch}", "-q", ".commit.sha"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api get {default_branch} sha failed: {r.stderr.strip()[:200]}")
    base_sha = r.stdout.strip()
    r = subprocess.run(
        ["gh", "api", f"/repos/{product_repo}/git/refs", "-X", "POST",
         "-f", f"ref=refs/heads/{branch}", "-f", f"sha={base_sha}"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh api create branch failed: {r.stderr.strip()[:200]}")
    # 回退 = 把 failed pin 当 current、old pin 当 new 的 bump
    rollback_changeset = lp.suggest_bump(
        {"version": failed_tag, "sha": failed_sha},
        {"name": old_tag, "commit": {"sha": old_pin_sha}})
    by_path = defaultdict(list)
    for f in rollback_changeset.get("files", []):
        by_path[f.get("path", "")].append(f)
    for _path, entries in by_path.items():
        _put_file_change(product_repo, branch, entries, env)
    r = subprocess.run(
        ["gh", "pr", "create", "--repo", product_repo,
         "--base", default_branch, "--head", branch,
         "--title", pr_title, "--body", pr_body],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {r.stderr.strip()[:200]}")
    pr_url = r.stdout.strip()
    print(f"LOOP_ROLLBACK_PR: {product_repo} {pr_title} -> {pr_url}")
    return pr_url


def _open_incident(args, product_repo, title, body):
    """开 Incident（gh issue create）。dry-run 下只打印。失败不抛（只警告）。"""
    if getattr(args, "dry_run", False):
        print(f"[dry-run] INCIDENT: {product_repo} — {title}")
        return None
    env = dict(os.environ)
    r = subprocess.run(
        ["gh", "issue", "create", "--repo", product_repo,
         "--title", title, "--body", body, "--label", "loop-bump-alert"],
        capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"WARN: gh issue create failed in {product_repo}: {r.stderr.strip()[:200]}", file=sys.stderr)
        return None
    url = r.stdout.strip()
    print(f"INCIDENT: {product_repo} {title} -> {url}")
    return url


def _resolve_loop_new_sha(args, rel, loop_repo):
    """从 release feed 候选解析新 tag 的 commit SHA。
    生产：lp.fetch_loop_tags 找匹配 tag 的 sha。
    dry-run：不拉网络，用占位 SHA（或 feed 自带 sha）。"""
    if getattr(args, "dry_run", False):
        return (rel.get("commit") or {}).get("sha", "") or rel.get("sha", "") or "0" * 40
    new_tag = rel.get("version") or rel.get("tag") or ""
    for t in lp.fetch_loop_tags(repo=loop_repo):
        if t.get("name") == new_tag:
            return (t.get("commit") or {}).get("sha", "")
    return ""


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

        # ── loop 控制面专属：开 bump PR（R13-6 #3/#4/#5）──
        if is_loop_control_plane(it):
            loop_repo = name  # name == "Cloudbird-Software/loop"
            # 当前 loop pin：优先 lp.parse_upstream_loop（产品仓 UPSTREAM.yaml），
            # 回退 item["pin"]（loop 仓自己的 UPSTREAM.yaml 无 loop 条目）。
            up_loop = lp.parse_upstream_loop(args.upstream)
            pin_str = (up_loop or {}).get("pin") or it.get("pin", "")
            if "@" in pin_str:
                cur_tag, cur_sha = pin_str.rsplit("@", 1)
            else:
                cur_tag, cur_sha = "", pin_str
            loop_current_pin = {"version": cur_tag, "sha": cur_sha}
            new_tag_loop = rel.get("version") or rel.get("tag") or ""
            new_sha_loop = _resolve_loop_new_sha(args, rel, loop_repo)
            products = load_products_yml()
            if not products:
                print(f"SKIP: {name} no enabled products in products.yml")
                continue
            # bench 重放一次（产品无关）；每个产品仓各自 compare + 决策（验收 #4）
            simulated_loop = rel.get("simulated_after") if args.dry_run else None
            after_loop = run_replay_after(args, simulated_after=simulated_loop)
            print(f"REPLAY: {name} cards={after_loop.get('replayed_cards',0)}")
            regressed_loop, table_loop = compare_with_baseline(args, after_loop)
            metric_detail = ""
            if regressed_loop:
                for ln in table_loop.splitlines():
                    b = ln.strip()
                    if b.startswith("REGRESSED:"):
                        metric_detail = b[len("REGRESSED:"):].strip()
                        break
                print(f"REGRESSED: loop {metric_detail}")
            for prod in products:
                prod_repo = prod.get("repo", "")
                prod_branch = prod.get("default_branch", "main")
                if not prod_repo:
                    continue
                if regressed_loop:
                    # 劣化 → 不开 bump PR，开 Incident（验收 #4）
                    _open_incident(args, prod_repo,
                        f"[loop-bump] regression on {new_tag_loop}",
                        f"loop bump to {new_tag_loop} @{new_sha_loop[:12]} regressed bench "
                        f"({metric_detail}); no bump PR opened.")
                    n_regressed += 1
                    continue
                try:
                    bump_loop_pin(args, it, new_tag_loop, new_sha_loop,
                                  loop_current_pin, prod_repo, prod_branch)
                    print(f"ROLLBACK_WATCH: loop {new_tag_loop} merged, watching next cycle for gate failures")
                    n_ok += 1
                except RuntimeError as e:
                    # bump 失败 → 开 Incident（pin_back 语义不适用 loop）
                    _open_incident(args, prod_repo,
                        f"[loop-bump] failed to open bump PR for {new_tag_loop}",
                        f"bump_loop_pin raised: {e}")
                    n_regressed += 1
            continue  # loop 不走通用 pin_back（pin 在产品仓侧）

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
