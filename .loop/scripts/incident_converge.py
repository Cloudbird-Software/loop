#!/usr/bin/env python3
""".loop/scripts/incident_converge.py — 一次性 Incident 收敛（R10-6）。

按指纹（或标题前缀）分组 open 的 Incident，每组只保留最新 1 张作为证据，
其余关闭并附关闭理由。用于收敛 R10-6 之前积累的重复 Incident 噪声。

用法：
  python3 .loop/scripts/incident_converge.py --dry-run   # 预览不执行
  python3 .loop/scripts/incident_converge.py              # 执行收敛
"""
import argparse
import json
import os
import re
import subprocess
import sys

E = os.environ
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER", ""))
REPO = f"{ORG}/loop"

FP_RE = re.compile(r"fp=([0-9a-f]{4,16})")
# 旧式标题（无指纹）：取 "Incident: <描述>" 去掉 @timestamp 作为分组键
LEGACY_TIME_RE = re.compile(r"\s*@\s*\d{4}-\d{2}-\d{2}.*$")


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def list_incidents():
    """返回 open 的 incident label issues：[{number, title, createdAt}]。"""
    p = gh("issue", "list", "-R", REPO, "--state", "open", "--label", "incident",
           "--json", "number,title,createdAt", "--limit", "200")
    if p.returncode != 0:
        print(f"ERROR: cannot list incidents: {p.stderr.strip()}")
        return []
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return []


def group_key(issue):
    """分组键：优先指纹，否则标题前缀（去 timestamp）。"""
    title = issue.get("title", "")
    m = FP_RE.search(title)
    if m:
        return f"fp={m.group(1)}"
    return LEGACY_TIME_RE.sub("", title).strip()


def close_with_reason(num, reason):
    gh("issue", "close", str(num), "-R", REPO, "-c", reason)


def converge(dry_run=False):
    incidents = list_incidents()
    if not incidents:
        print("No open incidents to converge.")
        return 0

    # 按分组键聚合
    groups = {}
    for it in incidents:
        k = group_key(it)
        groups.setdefault(k, []).append(it)

    closed = 0
    kept = 0
    for key, items in sorted(groups.items()):
        items.sort(key=lambda x: x.get("createdAt", ""))  # 旧 → 新
        latest = items[-1]
        dupes = items[:-1]
        kept += 1
        if not dupes:
            print(f"  [{key}] #{latest['number']} — only one, kept")
            continue
        reason = (f"按 .loop/scripts/incident_converge.py 收敛：同指纹/同标题重复 "
                  f"(key={key})。保留最新 #{latest['number']} 作为证据，关闭本张。"
                  f"见 R10-6 Incident 幂等与噪声治理。")
        print(f"  [{key}] keep #{latest['number']}, close {[i['number'] for i in dupes]}")
        if not dry_run:
            for d in dupes:
                close_with_reason(d["number"], reason)
        closed += len(dupes)

    print(f"\nsummary: {len(incidents)} open → kept {kept} (1 per fingerprint), "
          f"closed {closed}{' (dry-run)' if dry_run else ''}")
    return closed


def main():
    ap = argparse.ArgumentParser(description="一次性 Incident 收敛（R10-6）")
    ap.add_argument("--dry-run", action="store_true", help="只打印不执行")
    args = ap.parse_args()
    converge(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
