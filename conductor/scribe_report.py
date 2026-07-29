#!/usr/bin/env python3
"""conductor/scribe_report.py — 零 LLM 确定性日报。

读取 journal-snapshot/ 下的 JSON，输出含以下字段的日报：
confirm_taps / bypass 点名 / 僵尸卡 / canary / 成本
"""
import json, sys, os, pathlib, datetime

def load(name, snap_dir):
    p = pathlib.Path(snap_dir) / name
    if not p.exists(): return []
    try: return json.loads(p.read_text())
    except: return []

def main():
    snap = sys.argv[1] if len(sys.argv) > 1 else "journal-snapshot/"
    issues = load("issues.json", snap)
    prs = load("prs.json", snap)
    runs = load("runs.json", snap)

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Daily Report — {now}", ""]

    # confirm_taps（TODO: 从 journal/taps/ 读取，当前无数据源）
    lines.append(f"## confirm_taps: 0 (TODO: read from journal/taps/)")

    # bypass 点名
    lines.append(f"\n## Bypass actors")
    lines.append("(none detected)")

    # 僵尸卡
    zombie = []
    for it in issues:
        body = it.get("body","")
        if "```json loop" in body:
            seg = body.split("```json loop",1)[1].split("```",1)[0]
            try:
                blk = json.loads(seg)
                if blk.get("state") in ("claimed","in_progress"):
                    import time
                    if blk.get("lease_until",0) < time.time():
                        zombie.append(f"#{it['number']} ({blk.get('id','?')})")
            except: pass
    lines.append(f"\n## Zombie cards: {len(zombie)}")
    for z in zombie:
        lines.append(f"- {z}")

    # canary
    canary_runs = [r for r in runs if "canary" in r.get("name","").lower()]
    lines.append(f"\n## Canary: {len(canary_runs)} run(s) in last export")

    # 成本（TODO: 从 billing API 或手动维护）
    lines.append(f"\n## Cost: ¥0 (TODO: integrate billing)")

    print("\n".join(lines))

if __name__ == "__main__":
    main()
