#!/usr/bin/env python3
"""conductor/state_audit.py — 卡片状态哈希链审计器（W2-4）。

对卡片状态哈希链做审计 replay：
  1. seq 必须连续且以 0 开始，块位置 == seq；
  2. 每块 integrity.prev 必须等于上一块的哈希；
  3. 每块 integrity.writer 必须在 WRITER_WHITELIST。

发现断链时：
  - 打印 Incident(state-tamper)；
  - 置卡片 quarantined；
  - 回滚到最后一个有效版本（rollback_to_last_valid）并打印；
  - --verify 以非 0 退出码（1）返回；干净链则 exit 0。

不依赖远程 loop-state 分支：`--input <file>` 读取任意 JSON 数组块文件；未给
--input 时校验模块内置的 SAMPLE_CLEAN 常量。可用 --check-tamper-detection 临时
构造一条含伪造 prev 的破坏副本，验证篡改能被识别（期望 exit 1）。仅用 stdlib。
"""
import argparse
import json
import sys
import os

from conductor.state import (
    WRITER_WHITELIST,
    build_block,
    compute_block_hash,
    rollback_to_last_valid,
    verify_chain,
)

# 把仓库根插入 sys.path，使脚本直跑与 `python -m conductor.state_audit` 两种模式都可用
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 内置的干净样例链（用 build_block 逐块构造，prev 用前块哈希链式相接）
SAMPLE_CLEAN = [
    build_block(0, "", "loopd", "n0", {"state": "ready", "card": "C-001"}),
    build_block(1, compute_block_hash(
        build_block(0, "", "loopd", "n0", {"state": "ready", "card": "C-001"})),
        "conductor", "n1", {"state": "in_progress", "card": "C-001"}),
    build_block(2, compute_block_hash(
        build_block(1, compute_block_hash(
            build_block(0, "", "loopd", "n0", {"state": "ready", "card": "C-001"})),
            "conductor", "n1", {"state": "in_progress", "card": "C-001"})),
        "human-ops", "n2", {"state": "done", "card": "C-001"}),
]


def load_blocks(source):
    """从 --input 文件路径或内置样例链载入块列表。"""
    if source is not None:
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{source} 顶层必须是 JSON 数组，收到 {type(data).__name__}")
        return data
    return SAMPLE_CLEAN


def audit(blocks):
    """对块链做完整审计：返回退出码（0=干净，1=断链/被篡改）。

    断链时打印 Incident(state-tamper)、标 quarantined、打印回滚到最后一个有效
    版本的结果。不静默吞错——任何违规都以非 0 退出码上报。
    """
    ok, violations, last_valid = verify_chain(blocks)
    if ok:
        print(f"clean: chain of {len(blocks)} blocks verified; last_valid_prefix={last_valid}")
        return 0
    for v in violations:
        print(f"VIOLATION: {v}")
    print("Incident(state-tamper)")
    print("quarantined: True")
    valid_prefix = rollback_to_last_valid(blocks)
    print(f"rollback_to_last_valid: {len(valid_prefix)} block(s) "
          f"{[b.get('integrity', {}).get('seq') for b in valid_prefix]}")
    return 1


def tamper_detection_check():
    """从 SAMPLE_CLEAN 构造一条被篡改的副本（伪造最后一个块的 prev），并断言能识别。

    返回 audit 的退出码；由于副本确实含断链，本函数恒返回非 0。
    """
    broken = [dict(b) for b in SAMPLE_CLEAN]
    # 深层浅改：把 last 块的 prev 换成伪造值，破坏 prev 链接
    last = dict(broken[-1])
    last["integrity"] = dict(broken[-1]["integrity"])
    last["integrity"]["prev"] = "deadbeef" * 8  # 伪造的 prev，非前块哈希
    last["integrity"] = {k: last["integrity"][k] for k in last["integrity"]}
    broken[-1] = last
    print("msg: injected forged prev into last block of a SAMPLE_CLEAN copy; audit must detect")
    return audit(broken)


def main():
    ap = argparse.ArgumentParser(
        description="卡片状态哈希链审计器（W2-4）。默认校验内置 SAMPLE_CLEAN 并 exit 0。")
    ap.add_argument("--input", help="要审计的 JSON 数组块文件路径（否则用内置 SAMPLE_CLEAN）")
    ap.add_argument("--verify", action="store_true",
                    help="显式执行 --verify（缺省动作，可省略）")
    ap.add_argument("--gen-sample", nargs="?", const="state_sample.json", metavar="PATH",
                    help="把 SAMPLE_CLEAN 写入 PATH（默认 state_sample.json）后退出")
    ap.add_argument("--check-tamper-detection", action="store_true",
                    help="构造内置样例的伪造 prev 副本并断言断链可识别（期望 exit 1）")
    args = ap.parse_args()

    if args.gen_sample:
        path = args.gen_sample
        with open(path, "w", encoding="utf-8") as f:
            json.dump(SAMPLE_CLEAN, f, indent=2, ensure_ascii=False)
        print(f"wrote SAMPLE_CLEAN ({len(SAMPLE_CLEAN)} blocks) to {path}")
        return 0

    try:
        if args.check_tamper_detection:
            sys.exit(tamper_detection_check())
        # 默认 / --verify：审计 --input 或内置样例
        blocks = load_blocks(args.input)
        sys.exit(audit(blocks))
    except Exception as e:  # 显式上报而非静默吞错；非 0 退出
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()