#!/usr/bin/env python3
"""conductor/drift_check.py — ruleset 漂移检测。

用 POLICY_R app token 拉线上 ruleset，对比 settings/*.json。
漂移 → 开 Incident（永不自动修）。
"""
import json, os, subprocess, sys, pathlib

E = os.environ
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))
REPO = f"{ORG}/loop"

def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True)

def main():
    settings_dir = pathlib.Path("settings")
    if not settings_dir.exists():
        print("No settings/ directory, skipping drift check.")
        return

    drifts = []
    for sf in sorted(settings_dir.glob("*.json")):
        name = sf.stem  # e.g. "main-protection"
        local = json.loads(sf.read_text())
        ruleset_id = local.get("id")
        if not ruleset_id:
            print(f"Skipping {sf.name}: no ruleset id")
            continue
        # 拉线上 ruleset
        p = gh("api", f"/orgs/{ORG}/rulesets/{ruleset_id}")
        if p.returncode != 0:
            print(f"Cannot read ruleset {ruleset_id}: {p.stderr}")
            continue
        live = json.loads(p.stdout)
        # 对比 rules（只比 type 和关键参数）
        local_rules = sorted([r.get("type") for r in local.get("rules",[])])
        live_rules = sorted([r.get("type") for r in live.get("rules",[])])
        if local_rules != live_rules:
            drifts.append(f"{name}: rules differ (local={local_rules} live={live_rules})")
        # 对比 enforcement
        if local.get("enforcement") != live.get("enforcement"):
            drifts.append(f"{name}: enforcement local={local.get('enforcement')} live={live.get('enforcement')}")

    if drifts:
        print("DRIFT DETECTED:")
        for d in drifts:
            print(f"  ⚠ {d}")
        body = "## Ruleset Drift Detected\n\n" + "\n".join(f"- {d}" for d in drifts)
        body += "\n\n**No automatic fix applied.** Review and apply via policy.yml workflow."
        gh("issue","create","-R",REPO,"--title","Drift: ruleset mismatch detected",
           "--label","incident","--body",body)
        print(f"→ Opened Incident in {REPO}")
    else:
        print("No drift detected. All settings match live rulesets.")

if __name__ == "__main__":
    main()
