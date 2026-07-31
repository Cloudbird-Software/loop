#!/usr/bin/env python3
"""gate_upstream — 校验新增外部依赖都登记在 UPSTREAM.yaml。"""
import os, re, subprocess, sys

SCAN_FILES = ("requirements.txt", "loopd/bootstrap.sh")


def run(*cmd): return subprocess.run(cmd, capture_output=True, text=True)


def load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        return {}


def upstream_items(path="UPSTREAM.yaml"):
    data = load_yaml(path)
    out = {}
    for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
        if isinstance(item, dict) and item.get("name"): out[str(item["name"]).lower()] = item
    return out


def base_ref():
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        mb = run("git", "merge-base", f"origin/{base}", "HEAD").stdout.strip()
        if mb: return mb
        rv = run("git", "rev-parse", f"origin/{base}")
        if rv.returncode == 0 and rv.stdout.strip(): return rv.stdout.strip()
    return os.environ.get("LOOP_CI_BASE", "HEAD~1")


def changed_files(base, head="HEAD"):
    p = run("git", "diff", "--name-only", f"{base}..{head}")
    return [f for f in p.stdout.splitlines() if f]


def added_lines(base, head, path):
    p = run("git", "diff", f"{base}..{head}", "--", path)
    return [l[1:].strip() for l in p.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]


def package_from_requirement(line):
    if not line or line.startswith("#"): return None
    m = re.match(r"([A-Za-z0-9_.-]+)", line)
    return m.group(1).lower() if m else None


def refs_from_added(path, line):
    refs = []
    m = re.search(r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@", line)
    if m: refs.append(m.group(1))
    for owner, repo in re.findall(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", line):
        refs.append(f"{owner}/{repo}")
    if os.path.basename(path) == "requirements.txt":
        dep = package_from_requirement(line)
        if dep: refs.append(dep)
    return refs


def refs_from_diff(base, head="HEAD"):
    refs = set()
    for path in changed_files(base, head):
        if not (path == "requirements.txt" or path == "loopd/bootstrap.sh" or path.startswith(".github/workflows/")):
            continue
        for line in added_lines(base, head, path):
            refs.update(refs_from_added(path, line))
    return sorted(refs)


def validate_refs(refs, items):
    missing, placeholders = [], []
    for ref in refs:
        item = items.get(ref.lower())
        if not item:
            missing.append(ref); continue
        if item.get("sha256") == "w0-fill" or "w0-fill" in str(item.get("pin", "")):
            placeholders.append(ref)
    return missing, placeholders


def scan_placeholder_items(items):
    """R11-3: 扫描 UPSTREAM.yaml 中【所有】条目，凡 sha256==w0-fill 或 pin 含 w0-fill
    即记为 PLACEHOLDER_PIN_OR_SHA 违规（覆盖 diff 命中的之外的全部条目）。返回排序后的 name 列表。"""
    out = []
    for name, item in items.items():
        if item.get("sha256") == "w0-fill" or "w0-fill" in str(item.get("pin", "")):
            out.append(name)
    return sorted(out)


def scan_w0_fill_file(path="UPSTREAM.yaml"):
    """R11-3: 全文扫描——UPSTREAM.yaml 只要残留任意 `w0-fill` 字面量即返回 True。
    即使本次 diff 未触碰任何 deps，占位未回填也必须红（W0_FILL_PLACEHOLDER present）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return "w0-fill" in f.read()
    except Exception:
        return False


def main():
    base = base_ref(); head = os.environ.get("GITHUB_SHA", "HEAD")
    items = upstream_items()
    refs = refs_from_diff(base, head)
    missing, placeholders = validate_refs(refs, items)
    # R11-3: 全量扫描所有条目的 w0-fill 占位（不止 diff 命中的依赖）
    placeholder_all = scan_placeholder_items(items)
    bad = [f"MISSING_UPSTREAM {r}" for r in missing]
    bad += [f"PLACEHOLDER_PIN_OR_SHA {r}" for r in sorted(set(placeholders) | set(placeholder_all))]
    # R11-3: 全文扫描——即使 diff 未动 deps，UPSTREAM.yaml 残留 w0-fill 即红
    if scan_w0_fill_file("UPSTREAM.yaml"):
        bad.append("W0_FILL_PLACEHOLDER present")
    if bad:
        print("FAIL: UPSTREAM_VIOLATION\n" + "\n".join(bad)); sys.exit(1)
    print(f"OK upstream registered for {len(refs)} touched deps")


if __name__ == "__main__":
    main()
