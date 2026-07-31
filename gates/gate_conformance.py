#!/usr/bin/env python3
"""gate_conformance — 产品仓合规门禁（R13-2）。

校验产品仓是否正确接入 loop 控制面，六项检查全部通过才绿。
退出码：0=全通过，1=至少一项红。
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from conductor import loop_pin as lp

LOOP_REPO_DEFAULT = "Cloudbird-Software/loop"
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
# 匹配 `uses: <owner>/<repo>/.github/workflows/<name>.yml@<ref>`
USES_LOOP_RE = re.compile(
    r"uses:\s*(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/)?"
    r"\.github/workflows/[A-Za-z0-9_./-]+\.yml@([^\s,]+)"
)
# 匹配本地 `run:` 步骤（行首缩进，允许 `- run:` 内联形式）
RUN_STEP_RE = re.compile(r"(?m)^\s*(-\s+)?run:\s")
LAST_EDIT_RE = re.compile(r"last-human-edit:\s*(\S+)")


def load_yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _int(v, default):
    try:
        return int(v)
    except Exception:
        return default


def gh_api(endpoint):
    """调用 `gh api <endpoint>`，返回解析后的 JSON；失败返回 None。"""
    env = dict(os.environ)
    token = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
    if token:
        env["GH_TOKEN"] = token
    try:
        p = subprocess.run(
            ["gh", "api", endpoint], capture_output=True, text=True,
            env=env, timeout=30,
        )
    except Exception:
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def _loop_pin(product_dir):
    """读 LOOP.yml 的 loop 段，返回 (data, loop_dict, sha, version)。"""
    pin = lp.parse_loop_yml(os.path.join(product_dir, "LOOP.yml"))
    sha = pin["sha"].strip()
    version = pin["version"].strip()
    loop = {
        "repo": pin["repo"],
        "version": version,
        "sha": sha,
        "max_lag_tags": pin["max_lag_tags"],
        "max_lag_days": pin["max_lag_days"],
    }
    return {}, loop, sha, version


# ── 检查 1：pin 存在且合法 ──────────────────────────────────
def check1_pin_valid(product_dir, loop_repo):
    loop_yml = os.path.join(product_dir, "LOOP.yml")
    if not os.path.isfile(loop_yml):
        return False, "LOOP.yml 不存在"
    _data, _loop, sha, _version = _loop_pin(product_dir)
    if not HEX40.match(sha):
        return False, f"loop.sha 不是 40 位十六进制 ({sha[:16]!r})"
    commit = gh_api(f"/repos/{loop_repo}/commits/{sha}")
    if commit is None:
        return False, f"pin SHA {sha[:12]} 在 {loop_repo} 不可达（gh api 失败或 SHA 不存在）"
    return True, f"loop.sha={sha[:12]} 在 {loop_repo} 可达"


# ── 检查 2：pin 新鲜 ────────────────────────────────────────
def check2_pin_fresh(product_dir, loop_repo):
    _data, loop, sha, _version = _loop_pin(product_dir)
    if not HEX40.match(sha):
        return False, "loop.sha 非合法 40 位 SHA，无法判定新鲜度"
    max_lag_tags = _int(loop.get("max_lag_tags"), 2)
    max_lag_days = _int(loop.get("max_lag_days"), 30)

    tags = gh_api(f"/repos/{loop_repo}/tags")
    pin_commit = gh_api(f"/repos/{loop_repo}/commits/{sha}")
    if tags is None or pin_commit is None:
        # 网络不可达 → WARN 不红（无法证明过期就不红）
        return True, "WARN: gh api 不可达，新鲜度未判定（不阻塞）"

    lag_tags = None
    if isinstance(tags, list):
        for i, t in enumerate(tags):
            c = t.get("commit") if isinstance(t, dict) else None
            if isinstance(c, dict) and str(c.get("sha", "")) == sha:
                lag_tags = i
                break

    lag_days = None
    try:
        c = pin_commit.get("commit", {}) if isinstance(pin_commit, dict) else {}
        committer = c.get("committer", {}) if isinstance(c, dict) else {}
        date_str = str(committer.get("date", ""))
        if date_str:
            pub = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=datetime.timezone.utc)
            now = datetime.datetime.now(datetime.timezone.utc)
            lag_days = (now - pub).days
    except Exception:
        lag_days = None

    reasons = []
    if lag_tags is not None and lag_tags > max_lag_tags:
        reasons.append(f"落后 {lag_tags} 个 tag（上限 {max_lag_tags}）")
    if lag_days is not None and lag_days > max_lag_days:
        reasons.append(f"落后 {lag_days} 天（上限 {max_lag_days}）")
    if reasons:
        return False, "；".join(reasons)
    if lag_tags is None and lag_days is None:
        return True, "WARN: 无法计算落后程度（pin 不在 tag 列表且无 commit date），不阻塞"
    parts = []
    if lag_tags is not None:
        parts.append(f"lag_tags={lag_tags}/{max_lag_tags}")
    if lag_days is not None:
        parts.append(f"lag_days={lag_days}/{max_lag_days}")
    return True, "，".join(parts)


# ── 检查 3：必需文件齐备 ────────────────────────────────────
def check3_files_complete(product_dir):
    required = [
        ("CHARTER.md", os.path.join(product_dir, "CHARTER.md")),
        ("LOOP.yml", os.path.join(product_dir, "LOOP.yml")),
        ("UPSTREAM.yaml", os.path.join(product_dir, "UPSTREAM.yaml")),
        (".github/workflows/loop-ci.yml",
         os.path.join(product_dir, ".github", "workflows", "loop-ci.yml")),
    ]
    missing = [name for name, p in required if not os.path.isfile(p)]
    if missing:
        return False, f"缺少必需文件: {', '.join(missing)}"
    charter_path = os.path.join(product_dir, "CHARTER.md")
    try:
        with open(charter_path, encoding="utf-8") as f:
            charter = f.read()
    except Exception:
        return False, "CHARTER.md 无法读取"
    if "## 索引" not in charter:
        return False, "CHARTER.md 缺少机器可读索引段 '## 索引'"
    m = LAST_EDIT_RE.search(charter)
    if not m:
        return False, "CHARTER.md 缺少 last-human-edit 标记"
    if m.group(1).upper() == "PENDING":
        return False, "CHARTER.md last-human-edit=PENDING（章程未经人类审定）"
    return True, "必需文件齐备且 CHARTER 已审定"


# ── 检查 4：薄壳未被魔改 ────────────────────────────────────
def _shell_paths(product_dir):
    wf_dir = os.path.join(product_dir, ".github", "workflows")
    shells = ["loop-ci.yml", "loop-gates.yml", "loop-review.yml"]
    return [(n, os.path.join(wf_dir, n))
            for n in shells if os.path.isfile(os.path.join(wf_dir, n))]


def check4_shell_unmodified(product_dir):
    found = _shell_paths(product_dir)
    if not found:
        return False, "未发现任何 loop-* 薄壳 workflow"
    violations = []
    for name, p in found:
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            violations.append(f"{name}: 无法读取")
            continue
        if RUN_STEP_RE.search(text):
            violations.append(f"{name}: 含本地 'run:' 步骤（薄壳禁止内联逻辑）")
        for m in USES_LOOP_RE.finditer(text):
            ref = m.group(1).rstrip(",")
            if not HEX40.match(ref):
                violations.append(f"{name}: reusable workflow 引用未钉 40 位 SHA (@{ref})")
    if violations:
        return False, "; ".join(violations)
    return True, f"{len(found)} 个薄壳 workflow 仅含 uses: 引用"


# ── 检查 5：机制副本为零 ────────────────────────────────────
def _scan_dir(product_dir, subdir, predicate):
    out = []
    root = os.path.join(product_dir, subdir)
    if not os.path.isdir(root):
        return out
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, product_dir)
            try:
                if predicate(rel):
                    out.append(rel)
            except Exception:
                pass
    return sorted(out)


def check5_no_copies(product_dir):
    violations = []
    violations += _scan_dir(product_dir, "gates", lambda r: r.endswith(".py"))
    violations += _scan_dir(product_dir, "lenses", lambda r: r.endswith((".sh", ".py")))
    violations += _scan_dir(product_dir, "conductor", lambda r: r.endswith(".py"))
    violations += _scan_dir(product_dir, "loopd", lambda r: True)
    violations += _scan_dir(product_dir, "prompts", lambda r: r.endswith(".md"))
    env_yml = os.path.join("settings", "environments.yml")
    violations += _scan_dir(
        product_dir, "settings",
        lambda r: r.endswith(".json") and r != env_yml,
    )
    if violations:
        return False, f"发现 loop 机制副本: {', '.join(violations)}"
    return True, "无 loop 机制副本"


# ── 检查 6：薄壳引用 SHA 与 LOOP.yml 一致 ──────────────────
def check6_sha_consistency(product_dir, loop_repo):
    _data, _loop, pin_sha, _version = _loop_pin(product_dir)
    if not HEX40.match(pin_sha):
        return False, "LOOP.yml loop.sha 非合法 40 位 SHA"
    found = _shell_paths(product_dir)
    refs = []
    for name, p in found:
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except Exception:
            continue
        for m in USES_LOOP_RE.finditer(text):
            refs.append((name, m.group(1).rstrip(",")))
    if not refs:
        return False, "薄壳 workflow 中未发现 loop reusable workflow 引用"
    mismatches = []
    for name, ref in refs:
        if not HEX40.match(ref):
            mismatches.append(f"{name}: @{ref} 非 40 位 SHA")
        elif ref != pin_sha:
            mismatches.append(f"{name}: @{ref[:12]} != LOOP.yml @{pin_sha[:12]}")
    if mismatches:
        return False, "; ".join(mismatches)
    return True, f"{len(refs)} 个薄壳引用 SHA 与 LOOP.yml 一致"


CHECKS = [
    ("pin 存在且合法", lambda pd, lr: check1_pin_valid(pd, lr)),
    ("pin 新鲜", lambda pd, lr: check2_pin_fresh(pd, lr)),
    ("必需文件齐备", lambda pd, lr: check3_files_complete(pd)),
    ("薄壳未被魔改", lambda pd, lr: check4_shell_unmodified(pd)),
    ("机制副本为零", lambda pd, lr: check5_no_copies(pd)),
    ("薄壳 SHA 一致", lambda pd, lr: check6_sha_consistency(pd, lr)),
]


def run(product_dir, loop_repo):
    failures = 0
    for name, fn in CHECKS:
        try:
            ok, detail = fn(product_dir, loop_repo)
        except Exception as e:
            ok, detail = False, f"检查异常: {e}"
        if ok:
            print(f"OK: {name} — {detail}")
        else:
            print(f"FAIL: {name} — {detail}")
            failures += 1
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description="产品仓合规门禁（R13-2）")
    ap.add_argument("--product-dir", default=".", help="产品仓目录（默认当前目录）")
    ap.add_argument("--loop-repo", default=LOOP_REPO_DEFAULT,
                    help="loop 仓名（默认 Cloudbird-Software/loop）")
    args = ap.parse_args(argv)
    product_dir = os.path.abspath(args.product_dir)
    failures = run(product_dir, args.loop_repo)
    if failures:
        print(f"\n{failures} 项检查未通过")
        sys.exit(1)
    print("\n全部检查通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
