#!/usr/bin/env python3
"""conductor/drift_check.py — ruleset 漂移检测。

用 POLICY_R app token 拉线上 ruleset，对比 settings/*.json。
- Organization 级 ruleset 走 /orgs/{org}/rulesets/{id}
- Repository 级 ruleset 走 /repos/{org}/{repo}/rulesets/{id}（仓库由 source 字段决定）
比较时 rules 数组按 type 排序后比对（忽略顺序差，含 parameters），
enforcement 字段纳入比对。漂移 → 开 Incident（永不自动修）。
"""
import json, os, subprocess, pathlib

E = os.environ
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER", ""))
REPO = f"{ORG}/loop"   # Incident 开在 loop 控制面仓库


def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True)


def normalize_rules(rules):
    """保留 type + parameters，按 type 排序——忽略 rules 数组的顺序差。"""
    out = []
    for r in rules or []:
        out.append({"type": r.get("type"), "parameters": r.get("parameters", {})})
    return sorted(out, key=lambda x: (x["type"] or ""))


def ruleset_endpoint(local):
    """按 source_type 选择 API 路径，返回 (endpoint, kind)。"""
    rid = local.get("id")
    st = (local.get("source_type") or "").strip()
    if st == "Organization":
        return f"/orgs/{ORG}/rulesets/{rid}", "org"
    if st == "Repository":
        src = local.get("source")  # 形如 "Cloudbird-Software/product-x"
        if not src:
            return None, "repo-no-source"
        return f"/repos/{src}/rulesets/{rid}", "repo"
    return None, f"unknown-source_type:{st or 'missing'}"


def main():
    settings_dir = pathlib.Path("settings")
    if not settings_dir.exists():
        print("No settings/ directory, skipping drift check.")
        return

    drifts = []
    for sf in sorted(settings_dir.glob("*.json")):
        name = sf.stem  # e.g. "main-protection"
        local = json.loads(sf.read_text())
        rid = local.get("id")
        if not rid:
            print(f"Skipping {sf.name}: no ruleset id")
            continue
        endpoint, kind = ruleset_endpoint(local)
        if not endpoint:
            print(f"Skipping {sf.name}: {kind}")
            continue
        p = gh("api", endpoint)
        if p.returncode != 0:
            err = (p.stderr.strip().splitlines() or ["error"])[-1]
            print(f"Cannot read ruleset {rid} ({kind}) via {endpoint}: {err}")
            drifts.append(f"{name}: cannot read live ruleset {rid} via {endpoint} ({err})")
            continue
        live = json.loads(p.stdout)
        # rules：按 type 排序后比对（含 parameters），忽略顺序差
        local_rules = normalize_rules(local.get("rules", []))
        live_rules = normalize_rules(live.get("rules", []))
        if local_rules != live_rules:
            drifts.append(
                f"{name}: rules differ (local={[r['type'] for r in local_rules]} "
                f"live={[r['type'] for r in live_rules]})"
            )
        # enforcement 纳入比对
        if local.get("enforcement") != live.get("enforcement"):
            drifts.append(
                f"{name}: enforcement local={local.get('enforcement')} "
                f"live={live.get('enforcement')}"
            )

    if drifts:
        print("DRIFT DETECTED:")
        for d in drifts:
            print(f"  ⚠ {d}")
        body = "## Ruleset Drift Detected\n\n" + "\n".join(f"- {d}" for d in drifts)
        body += "\n\n**No automatic fix applied.** Review and apply via policy.yml workflow."
        gh("issue", "create", "-R", REPO, "--title", "Drift: ruleset mismatch detected",
           "--label", "incident", "--body", body)
        print(f"→ Opened Incident in {REPO}")
    else:
        print("No drift detected. All settings match live rulesets. (无漂移)")


if __name__ == "__main__":
    main()
