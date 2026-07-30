#!/usr/bin/env python3
"""gates/gate_settings_roundtrip.py — settings 快照与线上 ruleset 逐字对齐（R10-4）。

治本：settings/main-protection.json 曾缺 required_status_checks（审查新发现的高危缺陷）。
一旦 policy.yml 的 apply 被实现，残缺快照会以"人类批准"的名义抹掉线上仅有的 6 道真门禁。
本 gate 拉线上 ruleset 与仓库快照做归一化比对，不一致则非零退出并逐字段打印 diff。

铁律（CHARTER N5）：只检测与开 Incident，绝不写任何自动 apply/修正 ruleset 的代码路径。
"""
import json
import os
import subprocess
import sys

# 服务端字段：比对时忽略（这些由 GitHub 生成，不在仓库快照的语义范围内）。
SERVER_ONLY_KEYS = {"id", "node_id", "created_at", "updated_at", "_links",
                     "current_user_can_bypass", "name"}


def gh_json(endpoint):
    """调用 gh api，返回解析后的 JSON 或 None。"""
    p = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def normalize(obj):
    """递归去除服务端字段，rules 按 type 排序。返回深拷贝。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SERVER_ONLY_KEYS:
                continue
            out[k] = normalize(v)
        # rules 列表按 type 排序（忽略顺序差）
        if "rules" in out and isinstance(out["rules"], list):
            out["rules"] = sorted(out["rules"], key=lambda r: (r.get("type") or ""))
        return out
    if isinstance(obj, list):
        return [normalize(x) for x in obj]
    return obj


def diff_fields(local, live, prefix=""):
    """逐字段比较两个归一化后的 dict，返回差异描述列表。"""
    diffs = []
    keys = sorted(set(local) | set(live))
    for k in keys:
        lv = local.get(k, "<missing>")
        rv = live.get(k, "<missing>")
        if lv != rv:
            diffs.append(f"  {prefix}{k}: local={lv!r} live={rv!r}")
    return diffs


def compare_one(local_snapshot):
    """比较单个 settings/*.json 与线上 ruleset，返回 (ok, diffs)。"""
    rid = local_snapshot.get("id")
    if not rid:
        return True, []  # 无 id 的文件不监控
    st = (local_snapshot.get("source_type") or "").strip()
    src = local_snapshot.get("source", "")
    if st == "Organization":
        org = os.environ.get("LOOP_ORG", os.environ.get("GITHUB_REPOSITORY_OWNER", ""))
        endpoint = f"/orgs/{org}/rulesets/{rid}"
    elif st == "Repository":
        if not src:
            return False, [f"  source missing for ruleset {rid}"]
        endpoint = f"/repos/{src}/rulesets/{rid}"
    else:
        return True, []  # 未知 source_type，不监控

    live = gh_json(endpoint)
    if live is None:
        return False, [f"  cannot read live ruleset {rid} via {endpoint}"]

    local_n = normalize(local_snapshot)
    live_n = normalize(live)
    diffs = diff_fields(local_n, live_n)
    return (len(diffs) == 0), diffs


def main():
    settings_dir = pathlib_settings_dir()
    if not settings_dir or not os.path.isdir(settings_dir):
        print("SKIP: no settings/ directory")
        sys.exit(0)

    all_ok = True
    for sf in sorted(os.listdir(settings_dir)):
        if not sf.endswith(".json"):
            continue
        path = os.path.join(settings_dir, sf)
        local = json.loads(open(path, encoding="utf-8").read())
        rid = local.get("id", "?")
        ok, diffs = compare_one(local)
        if ok:
            print(f"OK: {sf} (ruleset {rid}) matches live")
        else:
            all_ok = False
            print(f"FAIL: {sf} (ruleset {rid}) differs from live:")
            for d in diffs:
                print(d)

    if all_ok:
        print("settings roundtrip OK — all snapshots match live rulesets")
        sys.exit(0)
    print("\n::error::settings drift detected — see diffs above (CHARTER N5: no auto-apply)")
    sys.exit(1)


def pathlib_settings_dir():
    return os.path.join(os.getcwd(), "settings")


if __name__ == "__main__":
    main()
