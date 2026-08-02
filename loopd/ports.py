#!/usr/bin/env python3
"""loopd.ports — 外层接口（loopd 分层：ports，W2-7 AC-3）。

分层目标：cli → usecases → domain ← ports/adapters。
本模块只声明"外接协议接口"（门禁/调度器/物化器/状态写），不承载业务实现，
由 adapters 提供实现。业务规则（转移表、租约、epoch）在 domain 层，单一事实源。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StateChainPort(Protocol):
    """状态真源读写端口（真实实现 = conductor.cas / loop-state 分支）。"""

    def current_sha(self, ref: str = "heads/loop-state") -> str | None:
        raise NotImplementedError

    def cas_update(self, base_sha: str, new_sha: str, force: bool = False) -> str:
        raise NotImplementedError


@runtime_checkable
class GatePort(Protocol):
    """门禁端口：任一不满足即拒（fail-closed）。"""

    def check(self, ctx: dict) -> bool:
        raise NotImplementedError


@runtime_checkable
class MaterializerPort(Protocol):
    """物化器端口：幂等建卡/更新卡（CARD-<wave>-<idx>-<sha8> + upsert）。"""

    def upsert(self, key: str, payload: dict) -> int:
        raise NotImplementedError


# 分层自检入口：证明 ports 层可作为协议的适配现场
def _selfcheck():
    from loopd.domain import transitions as _dom  # domain 单一事实源
    # 哨兵：domain 层仍暴露 apply 判转移，ports 只声明协议
    assert hasattr(_dom, "apply"), "domain transitions must remain the single source"
    return "OK: loopd ports layer present; domain single-source intact"


if __name__ == "__main__":
    import sys
    print(_selfcheck())
    sys.exit(0)