#!/usr/bin/env python3
"""conductor/drift_check.py — ruleset 漂移检测（R10-6：指纹去重）。

用 POLICY_R app token 拉线上 ruleset，对比 settings/*.json。
- 比较逻辑委托给 gates/gate_settings_roundtrip.py（R10-4），单一真源。
- 漂移 → 开 Incident，但**先按指纹查重**：同一根因只留一张 open 的 Incident，
  重复触发改为追加评论 + 更新计数（R10-6 治理 Incident 噪声）。
- 指纹 = sha256(归一化 drift 内容) 前 8 位，稳定且与时间戳无关。
- 永不自动修（CHARTER N5）。
"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

# 复用 gate_settings_roundtrip 的比较逻辑（R10-4 单一真源）
_GATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "gates")
if _GATES_DIR not in sys.path:
    sys.path.insert(0, _GATES_DIR)
import gate_settings_roundtrip as rt  # noqa: E402

E = os.environ
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER", ""))
REPO = f"{ORG}/loop"   # Incident 开在 loop 控制面仓库


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def collect_drifts():
    """遍历 settings/*.json，用 gate_settings_roundtrip 比对，返回 drift 描述列表。"""
    settings_dir = pathlib.Path("settings")
    if not settings_dir.exists():
        return [], {}
    drifts = []
    raw = []
    for sf in sorted(settings_dir.glob("*.json")):
        local = json.loads(sf.read_text())
        ok, diffs = rt.compare_one(local)
        if not ok:
            block = f"{sf.stem}: " + "; ".join(diffs)
            drifts.append(block)
            raw.append({"file": sf.name, "diffs": diffs})
    return drifts, raw


def fingerprint(raw_drifts):
    """稳定指纹：sha256(归一化 drift JSON) 前 8 位。同根因 → 同指纹。

    先对列表元素按其 JSON 表示排序，保证顺序无关（同一组 drift 无论检出顺序都同指纹）。
    """
    serialized = sorted(json.dumps(d, sort_keys=True) for d in raw_drifts)
    h = hashlib.sha256("\n".join(serialized).encode()).hexdigest()
    return h[:8]


def find_open_incident(fp):
    """按指纹查重：返回同指纹 open Incident 的 number，或 None。"""
    p = gh("issue", "list", "-R", REPO, "--state", "open",
           "--search", f"fp={fp} in:title", "--json", "number,title", "--limit", "10")
    if p.returncode != 0:
        return None
    try:
        items = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None
    for it in items:
        if f"fp={fp}" in (it.get("title") or ""):
            return it["number"]
    return None


def append_to_incident(num, fp, drifts):
    """在已有 Incident 追加评论（不新开）。"""
    import datetime
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    body = f"**Drift still present** @ {ts} (fp={fp})\n\n" + "\n".join(f"- {d}" for d in drifts)
    body += "\n\n*No new incident opened — same fingerprint. (R10-6 dedup)*"
    gh("issue", "comment", str(num), "-R", REPO, "--body", body)
    print(f"→ Appended to existing Incident #{num} (fp={fp})")


def open_new_incident(fp, drifts):
    """新开 Incident（标题含稳定指纹前缀）。"""
    title = f"Incident: ruleset drift detected [fp={fp}]"
    body = "## Ruleset Drift Detected\n\n"
    body += f"**Fingerprint**: `fp={fp}` (stable — same root cause = same fp)\n\n"
    body += "\n".join(f"- {d}" for d in drifts)
    body += "\n\n**No automatic fix applied.** Review and apply via policy.yml workflow."
    p = gh("issue", "create", "-R", REPO, "--title", title,
           "--label", "incident", "--body", body)
    url = p.stdout.strip()
    print(f"→ Opened Incident {url} (fp={fp})")


def main():
    drifts, raw = collect_drifts()
    if not drifts:
        print("No drift detected. All settings match live rulesets. (无漂移)")
        return
    print("DRIFT DETECTED:")
    for d in drifts:
        print(f"  ⚠ {d}")
    fp = fingerprint(raw)
    existing = find_open_incident(fp)
    if existing:
        append_to_incident(existing, fp, drifts)
    else:
        open_new_incident(fp, drifts)


if __name__ == "__main__":
    main()
