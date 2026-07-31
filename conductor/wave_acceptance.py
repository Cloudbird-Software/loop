#!/usr/bin/env python3
"""conductor/wave_acceptance.py — 波次自动验收（R14-2）。

解析 waves/WAVE-NN.md 中声明的『本波次的检查方法』，逐项判定：
  - 有机器可执行实现或证据 → pass
  - 明确标注 human-verify → pass（但计入 human 比例）
  - 无实现无证据 → fail

human-verify 项超过 1/3 时整体验收失败，并生成人类待办清单。
"""
import json
import os
import pathlib
import re
import sys
from typing import List, Dict, Any


def _loop_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("LOOP_ROOT", os.environ.get("GITHUB_WORKSPACE", "/workspace")))


def _waves_dir() -> pathlib.Path:
    return _loop_root() / "waves"


def _evidence_dir(wave_id: str) -> pathlib.Path:
    return _loop_root() / "evidence" / wave_id.lower()


def list_waves() -> List[pathlib.Path]:
    d = _waves_dir()
    if not d.exists():
        return []
    return sorted(d.glob("WAVE-*.md"))


def parse_wave_checks(wave_path: pathlib.Path) -> List[Dict[str, Any]]:
    """解析 WAVE 文件中的『本波次的检查方法』区块，返回检查项列表。"""
    text = wave_path.read_text(encoding="utf-8")
    # 匹配"## 本波次的检查方法（Wave-level Gate）"到下一个 ## 或文件尾
    m = re.search(
        r"#{1,4}\s*本波次的检查方法.*?\n(.*?)\n(?=#{1,4}\s|\Z)",
        text, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []
    section = m.group(1)
    items = []
    current_human = False
    for line in section.splitlines():
        line = line.strip()
        if not line:
            continue
        # 标注 human-verify 的说明行
        if re.match(r"^human[-_]?verify\b", line, re.I) or "人类" in line:
            current_human = True
            continue
        # 数字列表项才是检查项
        mm = re.match(r"^(\d+)\.\s*(.+)$", line)
        if mm:
            items.append({
                "number": int(mm.group(1)),
                "text": mm.group(2).strip(),
                "human_verify": current_human,
            })
            current_human = False
    return items


def _slug(text: str) -> str:
    return re.sub(r"[^\w\-_]", "_", text)[:40].strip("_")


def check_item(item: Dict[str, Any], wave_id: str) -> Dict[str, Any]:
    """判定单条检查项是否满足。"""
    evidence_dir = _evidence_dir(wave_id)
    slug = _slug(item["text"])
    evidence_file = evidence_dir / f"{slug}.md"

    # 1) 有证据文件 → 通过
    if evidence_file.exists():
        return {"ok": True, "detail": f"evidence found: {evidence_file}"}

    # 2) human-verify 项 → 通过但计入比例（需要人类待办清单）
    if item.get("human_verify"):
        return {"ok": True, "detail": "human-verify item; needs human checklist"}

    # 3) 检查是否有同名脚本/命令可执行（简单约定）
    cmd_file = _loop_root() / "scripts" / f"wave-accept-{wave_id.lower()}-{item['number']:02d}.sh"
    if cmd_file.exists():
        return {"ok": True, "detail": f"executable script found: {cmd_file}"}

    return {"ok": False, "detail": "no evidence, script or human-verify annotation"}


def run_acceptance(wave_id: str = "WAVE-14") -> Dict[str, Any]:
    wave_path = _waves_dir() / f"{wave_id}.md"
    if not wave_path.exists():
        return {"wave": wave_id, "passed": False, "reason": "wave file not found"}

    checks = parse_wave_checks(wave_path)
    if not checks:
        return {"wave": wave_id, "passed": False, "reason": "no checks parsed from wave file"}

    results = []
    human_count = 0
    for c in checks:
        res = check_item(c, wave_id)
        res.update({"item": c["text"], "number": c["number"], "human_verify": c.get("human_verify", False)})
        if c.get("human_verify"):
            human_count += 1
        results.append(res)

    total = len(results)
    human_ratio = human_count / total if total else 0.0
    passed = all(r["ok"] for r in results) and human_ratio <= (1.0 / 3.0)

    return {
        "wave": wave_id,
        "passed": passed,
        "total": total,
        "human_count": human_count,
        "human_ratio": round(human_ratio, 3),
        "checks": results,
    }


def human_checklist(wave_id: str = "WAVE-14") -> List[Dict[str, Any]]:
    """返回需要人类介入的检查项清单。"""
    wave_path = _waves_dir() / f"{wave_id}.md"
    if not wave_path.exists():
        return []
    checks = parse_wave_checks(wave_path)
    return [c for c in checks if c.get("human_verify")]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="波次自动验收")
    ap.add_argument("--wave", default="WAVE-14")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    result = run_acceptance(args.wave)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Wave: {result['wave']}  passed: {result.get('passed')}")
        for r in result.get("checks", []):
            mark = "✓" if r["ok"] else "✗"
            print(f"  {mark} {r['number']}. {r['item']} — {r['detail']}")
    sys.exit(0 if result.get("passed") else 1)
