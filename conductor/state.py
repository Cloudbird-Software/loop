#!/usr/bin/env python3
"""conductor/state.py — 卡片状态块的哈希链完整性原语（W2-4）。

W2-4 卡片目标：给每个 card-state 块加上完整性字段 {seq, prev, writer, nonce}，
构成一条防篡改的哈希链。本模块只提供自洽、可独立验证的结构与 helpers，不依赖
远程 loop-state orphan 分支——验收（AC-1..AC-4）全部可在本地用标准库完成。

完整性约定（replay 判定）：
  - 每个块形如 {"integrity": {seq, prev, writer, nonce}, "content": {...}}。
  - seq 从 0 开始连续递增；块在链中的位置必须等于其 seq。
  - 每个块的 integrity.prev 必须等于前一个块的哈希（sha256），seq 0 的 prev 为空串。
  - integrity.writer 必须在 WRITER_WHITELIST 白名单内。

本模块只依赖 stdlib（json / hashlib），可被 Python 3 直接 import。
"""
import hashlib
import json

# 完整性字段名（卡 acceptance AC-2 要求 grep-assertable）
STATE_INTEGRITY_FIELDS = ["seq", "prev", "writer", "nonce"]

# 允许写入卡片状态块的 writer 白名单（AC-2）
WRITER_WHITELIST = ["loopd", "conductor", "human-ops"]

# 哈希链起始块（seq=0）的 prev 占位值
GENESIS_PREV = ""


def canonical_json(obj):
    """对象 -> 确定性正规化 JSON 字符串（key 排序、紧凑分隔、保留非 ASCII）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_block_hash(block):
    """计算单个块的 sha256（对块的 integrity+content 正规化 JSON 做哈希）。

    因 block 内已含 prev，本函数天然地对"整条链到当前块为止"做承诺：改链条任意
    前缀都会改变后续所有块的哈希。返回 64 位小写十六进制字符串。
    """
    data = canonical_json({
        "integrity": block.get("integrity", {}),
        "content": block.get("content", {}),
    })
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def build_block(seq, prev_hash, writer, nonce, content):
    """构造带完整性字段的块 dict。

    调用方负责传入正确的前驱哈希与合法的 writer；本函数只组装结构并做基本类型校验。
    """
    if not isinstance(seq, int) or seq < 0:
        raise ValueError(f"seq 必须是非负整数，收到 {seq!r}")
    if writer not in WRITER_WHITELIST:
        raise ValueError(f"writer 不在白名单 {WRITER_WHITELIST}，收到 {writer!r}")
    return {
        "integrity": {
            "seq": seq,
            "prev": prev_hash,
            "writer": writer,
            "nonce": nonce,
        },
        "content": content,
    }


def verify_chain(blocks):
    """重放一条块链，返回 (ok, violations, last_valid_index)。

    - seq 连续且以 0 开始，且块位置 == seq。
    - 每块 prev == 前一块哈希（genesis 块 prev 必须为 GENESIS_PREV）。
    - 每块 writer 必须在 WRITER_WHITELIST。
    - 违规即中断（返回已发现违规 + 最后一个有效前缀末尾索引）。
    last_valid_index：最后一个编号合法的前缀长度（即该前缀里有多少个块）；
    空链/首块即坏时为 0。
    """
    violations = []
    prev_hash = GENESIS_PREV
    last_valid = 0
    ok = True
    for i, block in enumerate(blocks):
        integrity = block.get("integrity", {}) if isinstance(block, dict) else {}
        seq = integrity.get("seq")
        writer = integrity.get("writer")
        prev = integrity.get("prev")
        # 1) seq 连续性 / 位置 == seq
        if seq != i:
            violations.append(
                f"seq-mismatch: block[{i}] seq={seq!r} (期望 {i})")
            ok = False
            break
        # 2) prev 必须指向上一块哈希
        if prev != prev_hash:
            violations.append(
                f"prev-broken: block[{i}] prev={prev!r} (期望 {prev_hash!r})")
            ok = False
            break
        # 3) writer 白名单
        if writer not in WRITER_WHITELIST:
            violations.append(
                f"writer-not-whitelisted: block[{i}] writer={writer!r}")
            ok = False
            break
        prev_hash = compute_block_hash(block)
        last_valid = i + 1
    return ok, violations, last_valid


def rollback_to_last_valid(blocks):
    """链被篡改时回滚到最后一个有效版本。

    返回与"从 0 到最后一个有效索引"等价的合法前缀块列表（N 个块）。
    空链或首块即坏时返回空列表（无法回滚到任何有效版本）。
    """
    _ok, _violations, last_valid = verify_chain(blocks)
    return blocks[:last_valid]