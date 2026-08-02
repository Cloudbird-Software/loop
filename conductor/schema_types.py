#!/usr/bin/env python3
"""conductor/schema_types.py — card-state schema 单一事实源读取器（W2-5）。

单一事实源：.loop/schemas/state.json 是「card-state json loop 块」的唯一权威描述。
本模块只从该文件派生类型视图（dataclass CardState / Integrity）与常量
（SCHEMA_VERSION、SUPPORTED_SCHEMA_VERSIONS），不重复硬编码版本号，保证可再生、
幂等（重复读取同一文件结构恒等）。对未知 schema 版本号 fail-closed，
显式抛 SCHEMA_UNSUPPORTED，绝不允许 fail-open。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, fields
from typing import Dict, Optional

# 相对本文件（conductor/）上溯两级到仓库根，再进 .loop/schemas/state.json。
SCHEMA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".loop", "schemas")
)
SCHEMA_PATH = os.path.join(SCHEMA_DIR, "state.json")


class SCHEMA_UNSUPPORTED(Exception):
    """未知 schema 版本号被拒收（fail-closed，显式异常，不允许 fail-open）。"""


def _load_source() -> dict:
    """读取单一事实源文件。纯读文件、确定性、幂等。"""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# 顶层执行时加载一次。重复读取同一文件产生的结构恒等（幂等）。
SOURCE = _load_source()

# 从 source 派生常量——版本号不吃死代码，从 const 字段取。
SCHEMA_VERSION: int = SOURCE["properties"]["schema"]["const"]
SUPPORTED_SCHEMA_VERSIONS = frozenset({int(SCHEMA_VERSION), int(SCHEMA_VERSION) - 1})

# 从 source 派生期望的字段名集合，供一致性自检与 gate 校验使用。
_CARD_STATE_KEYS = frozenset(SOURCE["properties"].keys())
# 公开别名：gate_schema_singlesource.py 用它对比单一事实源。
SCHEMA_TYPE_CARD_KEYS = _CARD_STATE_KEYS
_INTEGRITY_KEYS = frozenset(
    SOURCE["properties"]["verification"]["properties"].keys()
)


@dataclass
class Integrity:
    """卡片状态块内的完整性校验子块（从 source 的 verification 定义派生）。"""

    checksum_sha256: Optional[str] = None
    signals: Dict[str, bool] = None  # type: ignore[assignment]


@dataclass
class CardState:
    """card-state json loop 块的强类型视图。

    必需字段排前（无默认值），可选字段随后；字段名必须与 source 的
    properties 一致（由 _check_single_source 在加载后强制）。
    """

    schema: int
    card_id: str
    state: str
    lease_until: Optional[str] = None
    heartbeat_at: Optional[str] = None
    attempt: int = 0
    model: str = ""
    verification: Optional[Integrity] = None


def _check_single_source() -> None:
    """强制单一事实源：dataclass 字段名必须与 source 完全一致。

    一旦 .loop/schemas/state.json 与这里的类型视图漂移，一律显式报错，
    不静默吞掉（fail-closed）。
    """
    card_fields = frozenset(f.name for f in fields(CardState))
    if card_fields != _CARD_STATE_KEYS:
        missing = sorted(_CARD_STATE_KEYS - card_fields)
        extra = sorted(card_fields - _CARD_STATE_KEYS)
        raise SCHEMA_UNSUPPORTED(
            f"schema double-source drift: state.json has {sorted(_CARD_STATE_KEYS)!r}, "
            f"CardState has {sorted(card_fields)!r}; missing={missing}, extra={extra}"
        )
    integ_fields = frozenset(f.name for f in fields(Integrity))
    if integ_fields != _INTEGRITY_KEYS:
        raise SCHEMA_UNSUPPORTED(
            f"schema double-source drift: state.json verification has "
            f"{sorted(_INTEGRITY_KEYS)!r}, Integrity has {sorted(integ_fields)!r}"
        )


def derive_view() -> dict:
    """返回从单一事实源派生出的类型视图（确定性结构，供 read() 与 gate 校验）。"""
    return {
        "SCHEMA_VERSION": SCHEMA_VERSION,
        "SUPPORTED_SCHEMA_VERSIONS": sorted(SUPPORTED_SCHEMA_VERSIONS),
        "card_state_keys": sorted(_CARD_STATE_KEYS),
        "integrity_keys": sorted(_INTEGRITY_KEYS),
    }


def read(state_dict: dict) -> CardState:
    """把一段 state 字典解码为 CardState。

    对 schema 版本不在 SUPPORTED_SCHEMA_VERSIONS 内一律抛 SCHEMA_UNSUPPORTED
    （fail-closed）；缺关键字段也显式报错，不 fail-open。
    """
    if not isinstance(state_dict, dict):
        raise SCHEMA_UNSUPPORTED(
            f"expected a state dict, got {type(state_dict).__name__}"
        )
    ver = state_dict.get("schema")
    if ver not in SUPPORTED_SCHEMA_VERSIONS:
        raise SCHEMA_UNSUPPORTED(
            f"unsupported schema version {ver!r}; supported={sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    required = set(SOURCE.get("required", []))
    missing = sorted(required - set(state_dict.keys()))
    if missing:
        raise SCHEMA_UNSUPPORTED(
            f"state dict missing required fields {missing}; not failing open"
        )

    verification = None
    if state_dict.get("verification") is not None:
        verification = Integrity(
            checksum_sha256=state_dict["verification"].get("checksum_sha256"),
            signals=state_dict["verification"].get("signals"),
        )

    return CardState(
        schema=int(state_dict["schema"]),
        card_id=state_dict["card_id"],
        state=state_dict["state"],
        lease_until=state_dict.get("lease_until"),
        heartbeat_at=state_dict.get("heartbeat_at"),
        attempt=int(state_dict.get("attempt", 0)),
        model=state_dict.get("model", ""),
        verification=verification,
    )


def run_expect_unsupported() -> int:
    """AC-4：证明未知 schema 版本（如 999）被显式 SCHEMA_UNSUPPORTED 拒收。"""
    try:
        read({"schema": 999, "card_id": "C-001", "state": "ready", "attempt": 0, "model": "m0"})
    except SCHEMA_UNSUPPORTED as exc:
        print(f"OK: SCHEMA_UNSUPPORTED raised -> {exc}")
        return 0
    print("ERROR: expected SCHEMA_UNSUPPORTED but it did NOT raise (fail-open!)")
    return 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--expect-unsupported" in argv:
        return run_expect_unsupported()
    if "--dump-view" in argv:
        print(json.dumps(derive_view(), sort_keys=True))
        return 0
    print(f"SCHEMA_VERSION={SCHEMA_VERSION}")
    print(f"SUPPORTED_SCHEMA_VERSIONS={sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    return 0


# 模块加载即做一次单一事实源自检（fail-closed）：任何 import 都会触发一致性校验。
_check_single_source()


if __name__ == "__main__":
    sys.exit(main())