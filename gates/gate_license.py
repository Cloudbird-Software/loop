#!/usr/bin/env python3
"""gate_license — 校验新增依赖已登记且许可证在白名单内。"""
import json, os, re, subprocess, sys

DEFAULT_ALLOW = ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Unlicense", "CC0-1.0", "PSF-2.0", "Python-2.0"]
MANIFESTS = {"requirements.txt", "package.json", "go.mod", "Cargo.toml", "pyproject.toml"}


def run(*cmd): return subprocess.run(cmd, capture_output=True, text=True)


def load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception:
        return {}


def ensure_license_policy(path="policy.yml"):
    policy = load_yaml(path)
    allow = policy.get("license", {}).get("allow") if isinstance(policy.get("license"), dict) else None
    if allow: return allow
    if os.path.exists(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write("\nlicense:\n  allow: [" + ", ".join(DEFAULT_ALLOW) + "]\n")
    return DEFAULT_ALLOW


def base_ref():
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        mb = run("git", "merge-base", f"origin/{base}", "HEAD").stdout.strip()
        if mb: return mb
        rv = run("git", "rev-parse", f"origin/{base}")
        if rv.returncode == 0 and rv.stdout.strip(): return rv.stdout.strip()
    return os.environ.get("LOOP_CI_BASE", "HEAD~1")


def changed_manifests(base, head="HEAD"):
    p = run("git", "diff", "--name-only", f"{base}..{head}")
    return [f for f in p.stdout.splitlines() if os.path.basename(f) in MANIFESTS]


def added_lines(base, head, path):
    p = run("git", "diff", f"{base}..{head}", "--", path)
    return [l[1:].strip() for l in p.stdout.splitlines() if l.startswith("+") and not l.startswith("+++")]


def dep_name_from_line(path, line):
    if not line or line.startswith(("#", "//")): return None
    name = os.path.basename(path)
    if name == "requirements.txt":
        m = re.match(r"([A-Za-z0-9_.-]+)", line); return (m.group(1).lower() if m else None)
    if name == "go.mod":
        m = re.match(r"(?:require\s+)?([A-Za-z0-9_.-]+/[A-Za-z0-9_.\-/]+)\s+v?\d", line); return (m.group(1) if m else None)
    if name == "package.json":
        m = re.match(r'"(@?[^"/]+(?:/[^"/]+)?)"\s*:\s*"', line); return (m.group(1) if m else None)
    if name in {"Cargo.toml", "pyproject.toml"}:
        m = re.match(r'([A-Za-z0-9_.-]+)\s*=\s*["{]', line); return (m.group(1).lower() if m else None)
    return None


def new_deps_from_diff(base, head="HEAD"):
    deps = set()
    for path in changed_manifests(base, head):
        for line in added_lines(base, head, path):
            dep = dep_name_from_line(path, line)
            if dep: deps.add(dep)
    return sorted(deps)


def upstream_items(path="UPSTREAM.yaml"):
    data = load_yaml(path)
    out = {}
    for item in data.get("items", []) if isinstance(data.get("items"), list) else []:
        if isinstance(item, dict) and item.get("name"): out[str(item["name"]).lower()] = item
    return out


def validate_licenses(deps, items, allow):
    bad = []
    allow_set = set(allow)
    for dep in deps:
        item = items.get(dep.lower())
        lic = item.get("license") if isinstance(item, dict) else None
        if not item: bad.append(f"MISSING_UPSTREAM {dep}")
        elif not lic: bad.append(f"MISSING_LICENSE {dep}")
        elif lic not in allow_set: bad.append(f"LICENSE_NOT_ALLOWED {dep} {lic}")
    return bad


def main():
    allow = ensure_license_policy()
    base = base_ref(); head = os.environ.get("GITHUB_SHA", "HEAD")
    manifests = changed_manifests(base, head)
    if not manifests:
        print("OK license skipped (no dependency manifest changes)"); sys.exit(0)
    deps = new_deps_from_diff(base, head)
    bad = validate_licenses(deps, upstream_items(), allow)
    if bad:
        print("FAIL: LICENSE_VIOLATION\n" + "\n".join(bad)); sys.exit(1)
    print(f"OK licenses allowed for {len(deps)} new deps")


if __name__ == "__main__":
    main()
