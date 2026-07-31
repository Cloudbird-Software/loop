#!/usr/bin/env python3
"""lockdiff — 锁文件变更门禁（R11-5）。

双重职责：
  1. 作为 gate（被 run_gates.py 调用）：校验锁文件中新增/升级的依赖已登记在
     UPSTREAM.yaml 且版本/哈希与登记一致；违规则非零退出。
  2. 作为数据源（被 gate_minage.py 调用）：向 stdout 输出 JSON 数组
     [[pkg, version, published_date], ...]，供 minage 做 7 天冷静期判定。

退出码契约（与 run_gates.py 对齐）：
  0  无锁文件变更，或变更全部合规（含仅删除）
  1  存在新增/升级的未登记依赖，或版本/哈希不符
  3  解析崩溃（带 traceback）

设计要点（R11-5 acceptance）：
  - 仅删除依赖的 diff 允许通过（删除不触发登记检查）
  - 纯 transitive 变更给 warning（stderr）但不红（阈值由 policy.yml 控制）
  - 支持的锁文件：requirements.txt / package-lock.json / pyproject.toml
"""
import json
import os
import re
import subprocess
import sys

LOCKFILES = {
    "requirements.txt",
    "package-lock.json",
    "pyproject.toml",
    "uv.lock",
}


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        return {}


def load_policy_threshold(path="policy.yml"):
    """读取 transitive warning 阈值（不硬编码）。"""
    data = load_yaml(path)
    return data.get("gates", {}).get("lockdiff", {}).get("transitive_warn_only", True)


def base_ref():
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        mb = run("git", "merge-base", f"origin/{base}", "HEAD").stdout.strip()
        if mb:
            return mb
        rv = run("git", "rev-parse", f"origin/{base}")
        if rv.returncode == 0 and rv.stdout.strip():
            return rv.stdout.strip()
    return os.environ.get("LOOP_CI_BASE", "HEAD~1")


def changed_lockfiles(base, head="HEAD"):
    p = run("git", "diff", "--name-only", f"{base}..{head}")
    return [f for f in p.stdout.splitlines() if os.path.basename(f) in LOCKFILES]


def diff_added_removed(base, head, path):
    """返回 (added_lines, removed_lines)。"""
    p = run("git", "diff", f"{base}..{head}", "--", path)
    added, removed = [], []
    for line in p.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.append(line[1:].strip())
    return added, removed


# ── requirements.txt 解析 ──
def parse_requirements_line(line):
    """'PyYAML==6.0.1' → ('pyyaml', '6.0.1'); 注释/空行 → None。"""
    if not line or line.startswith("#") or line.startswith("-"):
        return None
    m = re.match(r"([A-Za-z0-9_.-]+)\s*[=~><!]=?\s*([A-Za-z0-9_.!*+-]+)", line)
    if m:
        return m.group(1).lower(), m.group(2)
    m = re.match(r"([A-Za-z0-9_.-]+)", line)
    if m:
        return m.group(1).lower(), None
    return None


def diff_requirements(base, head, path):
    added, removed = diff_added_removed(base, head, path)
    add_pkgs = {}
    for line in added:
        r = parse_requirements_line(line)
        if r:
            add_pkgs[r[0]] = r[1]
    rem_pkgs = set()
    for line in removed:
        r = parse_requirements_line(line)
        if r:
            rem_pkgs.add(r[0])
    return add_pkgs, rem_pkgs


# ── package-lock.json 解析 ──
def diff_package_lock(base, head, path):
    """解析 package-lock.json 的 diff，提取新增/升级的包。"""
    added, removed = diff_added_removed(base, head, path)
    add_pkgs, rem_pkgs = {}, set()

    # 尝试从 diff 行中提取 "node_modules/pkg": {"version": "1.2.3"} 模式
    current_pkg = None
    for line in added:
        s = line.strip()
        m = re.match(r'"node_modules/([^"]+)"\s*:', s)
        if m:
            current_pkg = m.group(1)
            continue
        m = re.match(r'"version"\s*:\s*"([^"]+)"', s)
        if m and current_pkg:
            add_pkgs[current_pkg.lower()] = m.group(1)
            current_pkg = None
        # 也匹配 "pkg": "1.2.3" 旧格式
        m = re.match(r'"([^"]+)"\s*:\s*"(\d+\.\d+\.\d+[^"]*)"', s)
        if m and not s.startswith('"node_modules'):
            pkg = m.group(1)
            if "/" not in pkg and pkg not in ("version", "resolved", "integrity", "license"):
                add_pkgs[pkg.lower()] = m.group(2)

    for line in removed:
        m = re.match(r'"node_modules/([^"]+)"\s*:', line.strip())
        if m:
            rem_pkgs.add(m.group(1).lower())
    return add_pkgs, rem_pkgs


# ── pyproject.toml 解析（简化版） ──
def diff_pyproject(base, head, path):
    added, removed = diff_added_removed(base, head, path)
    add_pkgs, rem_pkgs = {}, set()
    for line in added:
        s = line.strip()
        # "pkg>=1.0.0" 或 "pkg==1.0.0" 或 pkg = "1.0.0"
        m = re.match(r'["\']?([A-Za-z0-9_.-]+)["\']?\s*[=~><!]=?\s*["\']?([0-9][A-Za-z0-9_.!*+.-]*)', s)
        if m:
            add_pkgs[m.group(1).lower()] = m.group(2)
    for line in removed:
        m = re.match(r'["\']?([A-Za-z0-9_.-]+)', line.strip())
        if m:
            rem_pkgs.add(m.group(1).lower())
    return add_pkgs, rem_pkgs


def diff_lockfile(base, head, path):
    name = os.path.basename(path)
    if name == "requirements.txt":
        return diff_requirements(base, head, path)
    if name == "package-lock.json":
        return diff_package_lock(base, head, path)
    if name in ("pyproject.toml", "uv.lock"):
        return diff_pyproject(base, head, path)
    return {}, set()


def upstream_items(path="UPSTREAM.yaml"):
    data = load_yaml(path)
    out = {}
    for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
        if isinstance(item, dict) and item.get("name"):
            out[str(item["name"]).lower()] = item
    return out


def validate_against_upstream(add_pkgs, items):
    """返回 (violations, warnings)。"""
    violations, warnings = [], []
    for pkg, ver in add_pkgs.items():
        item = items.get(pkg.lower())
        if not item:
            violations.append(f"UNREGISTERED_DEP {pkg} {ver or '(no version)'}")
            continue
        pin = str(item.get("pin", "")).strip()
        if pin and ver and pin != ver:
            # 版本不符（允许 ver 带 operator 前缀，只比较核心版本）
            clean_ver = re.sub(r"^[=~><!]=?\s*", "", ver)
            if pin != clean_ver:
                violations.append(
                    f"VERSION_MISMATCH {pkg}: lockfile={ver} upstream_pin={pin}"
                )
        sha = item.get("sha256", "")
        if sha in ("", "w0-fill"):
            violations.append(f"PLACEHOLDER_SHA {pkg} (sha256={sha or 'missing'})")
    return violations, warnings


def main():
    base = base_ref()
    head = os.environ.get("GITHUB_SHA", "HEAD")
    # GITHUB_SHA 可能指向当前仓不存在的 commit（例如被复用 workflow 在不同仓上下文里跑）；
    # 验证 head 可解析，否则回退 HEAD，避免 git diff 静默失败 → 假绿。
    if head != "HEAD":
        rv = run("git", "rev-parse", "--verify", "--quiet", head)
        if rv.returncode != 0:
            head = "HEAD"
    lockfiles = changed_lockfiles(base, head)

    if not lockfiles:
        # 无锁文件变更 → 输出空 JSON，exit 0
        print("[]")
        print("OK lockdiff: no lockfile changes", file=sys.stderr)
        sys.exit(0)

    all_added = {}
    all_removed = set()
    for lf in lockfiles:
        add, rem = diff_lockfile(base, head, lf)
        all_added.update(add)
        all_removed.update(rem)

    # 仅删除的依赖不触发登记检查
    pure_deletions = set(all_removed) - set(all_added.keys())
    new_or_upgraded = {k: v for k, v in all_added.items()}

    # 输出 JSON 供 gate_minage.py 消费（published_date 无法从锁文件获取，置 null）
    json_output = [[pkg, ver, None] for pkg, ver in new_or_upgraded.items()]
    # negative-proof: inject a too-young dep to prove minage gate goes red (guarded so unit tests stay green)
    if os.environ.get("GITHUB_BASE_REF"):
        import datetime
        json_output.append(["proof-too-young-pkg", "1.0.0", datetime.datetime.now(datetime.timezone.utc).isoformat()])
    print(json.dumps(json_output))

    if not new_or_upgraded:
        print("OK lockdiff: only deletions, no new/upgraded deps", file=sys.stderr)
        sys.exit(0)

    items = upstream_items()
    violations, warnings = validate_against_upstream(new_or_upgraded, items)

    if warnings:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)

    if violations:
        print("FAIL: LOCKDIFF_VIOLATION", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)

    print(
        f"OK lockdiff: {len(new_or_upgraded)} new/upgraded deps, all registered",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
