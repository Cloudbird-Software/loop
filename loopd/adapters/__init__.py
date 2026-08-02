"""loopd.adapters — 具象适配器层（loopd 分层：adapters，W2-7 AC-3）。

本包是四层里唯一允许触碰 gh/shell 的地方，把 loopd.ports 声明的协议翻译成
`gh api` 具体调用。业务规则在 loopd.domain，纯编排在 loopd.usecases，
本层只做"协议 → 外部调用"的落地。
"""
from loopd.adapters.github import (
    GhStateChainPort,
    GhGatePort,
    GhMaterializerPort,
    _selfcheck,
)

__all__ = ["GhStateChainPort", "GhGatePort", "GhMaterializerPort", "_selfcheck"]


if __name__ == "__main__":
    import sys
    print(_selfcheck())
    sys.exit(0)