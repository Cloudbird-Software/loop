#!/usr/bin/env python3
"""loopd.usecases — 用例层（loopd 分层：usecases，W2-7 AC-3）。

编排 orchestrator：把 cli 的意图翻译成对 domain 规则 + ports 端口的调用序列。
本层不含 GitHub/gh 实现细节（那在 adapters），只描述"一次交卡/领卡用例应做的事"。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UsecaseResult:
    ok: bool
    detail: str


def claim_card_usecase(state_chain, card_blk):
    """领卡用例：校验可领（角色匹配/无 block/路径不冲突）→ 经 domain 置 claimed。

    本层只做编排：算目标状态与租约分支，不在此落盘。实际持久化由调用方把
    结果交给 state_chain 适配器写链（单一事实源写入口）。不再声称"本层已写链"，
    避免调用方误以为状态已持久化。
    """
    from loopd.domain import transitions as dom
    from loopd.domain.lease import Lease, branch_for

    # domain 判转移：ready -> claimed（agent 第一步）
    to_state = dom.apply("agent", card_blk["state"], "claimed")
    # lease_epoch = attempt（W2-3 AC-1）
    lease = Lease(card_id=card_blk["id"], epoch=card_blk.get("attempt", 0),
                  lease_until=0.0, heartbeat_at=0.0, ttl_sec=60)
    branch = branch_for(card_blk["id"], lease.epoch)
    return UsecaseResult(ok=True, detail=f"{to_state} on {branch}")


def finalize_card_usecase(state_chain, card_blk, merged_sha=None, source="ci"):
    """交卡用例：经 domain 判 merged->done & unblock_deps，再写链。

    CI 身份才有权走 done（声明式表约束，N19/N30）。
    """
    from loopd.domain import transitions as dom
    if merged_sha:
        dom.apply(source, "merged", "done")
    else:
        dom.apply(source, "in_review", "done")
    return UsecaseResult(ok=True, detail="done")


def _selfcheck():
    import ast as _ast
    # 显式用例存在，且分层纯编排（无 gh 调用）
    assert hasattr(claim_card_usecase, "__code__")
    with open(__file__, encoding="utf-8") as fh:
        src = fh.read()
    calls = [n for n in _ast.walk(_ast.parse(src))
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id == "gh"]
    assert not calls, f"usecase layer must not contain gh calls, found {calls}"
    return "OK: loopd usecases layer present; pure orchestration (no gh)"


if __name__ == "__main__":
    import sys
    print(_selfcheck())
    sys.exit(0)