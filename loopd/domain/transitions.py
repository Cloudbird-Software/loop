#!/usr/bin/env python3
"""loopd.domain.transitions — 声明式状态转移表（W2-6）。

卡片生命周期是一张**声明式**转移表，杜绝跳步 / 越权。核心：

  - ``STATES``：卡片可处状态全集（ready/claimed/in_progress/in_review/done/closed
    /respec/stalled/orphaned/merged/abandoned）。
  - ``STATE_ORDER``：本波次实际推进使用的前几步（agent 只走前三步）。
  - ``ALLOWED_TRANSITIONS_BY_SOURCE``：按**写者身份**（ci / judgment / agent）声明的
    允许转移。done/verified 只有 ``ci`` 能写（N19/N30）；judgment 只能写 failed；
    agent 只走 ready→claimed→in_progress→in_review。
  - ``apply(source, from_state, to_state)``：查表，非法即抛 ``IllegalTransition``，
    全空间要么有定义、要么抛——不存在未定义/假开门（N11）。
  - merge-completion：merged→done + merged_sha + unblock_deps。

穷举性质测试：``__main__`` 对 "身份 × 出发态 × 目标态" 全空间断言——每个组合要么
合法通过、要么抛 IllegalTransition；对负证 ``verified→in_progress`` 断言必然抛。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class IllegalTransition(Exception):
    """状态转移不在声明式表中：必然抛，禁止静默/假开门。"""


# 卡片生命周期全集（合并 declared + 语义状态）
STATES = (
    "ready", "claimed", "in_progress", "in_review", "done",
    "closed", "respec", "stalled", "orphaned", "merged", "abandoned", "verified",
)

# agent 只被允许走的前三步（ready→claimed→in_progress→in_review）
AGENT_PATH = ("ready", "claimed", "in_progress", "in_review")

# 终态：仅 CI 可写（N19/N30）
CI_ONLY_TERMINAL = ("done", "verified")


# 按写者身份声明的合法转移。
# 语义：每个来源身份给出 {from_state: frozenset(to_states)}；未列出的 (from,to) 一律非法。
def _all(s):
    return frozenset(s)


ALLOWED_TRANSITIONS_BY_SOURCE = {
    # CI：可推进常规路径 + 可写全部终态 + merged 完结 + 各类终结
    "ci": {
        "ready": _all(("claimed", "in_progress", "done", "verified", "closed", "respec", "stalled", "orphaned", "abandoned")),
        "claimed": _all(("in_progress", "ready", "done", "verified", "closed", "respec", "stalled", "orphaned", "abandoned")),
        "in_progress": _all(("in_review", "ready", "done", "verified", "closed", "respec", "stalled", "orphaned", "abandoned")),
        "in_review": _all(("done", "verified", "closed", "respec", "stalled", "orphaned", "abandoned", "claimed")),
        "closed": _all(("ready",)),
        "merged": _all(("done",)),
    },
    # judgment（人类裁决）：只能写 failed 类终结，不得越权推前进/终态
    "judgment": {
        "ready": _all(("closed", "respec", "stalled", "orphaned", "abandoned")),
        "claimed": _all(("closed", "respec", "stalled", "orphaned", "abandoned")),
        "in_progress": _all(("closed", "respec", "stalled", "orphaned", "abandoned")),
        "in_review": _all(("closed", "respec", "stalled", "orphaned", "abandoned")),
    },
    # agent：只走前几步的正向推进 + 允许反悔到 ready（被踢/放弃）
    "agent": {
        "ready": _all(("claimed",)),
        "claimed": _all(("in_progress", "ready")),
        "in_progress": _all(("in_review", "claimed")),
        "in_review": _all(("ready", "claimed")),
    },
}


# 合并后的合法转移判据（供 O(1) 查询）
def _build_allowed():
    tbl = {}
    for src, m in ALLOWED_TRANSITIONS_BY_SOURCE.items():
        for f, ts in m.items():
            tbl[(src, f)] = tbl.get((src, f), frozenset()) | ts
    return tbl


_ALLOWED = _build_allowed()


def apply(source: str, from_state: str, to_state: str) -> str:
    """查声明式表判转移。非法即抛 IllegalTransition；合法返回 to_state。"""
    if from_state not in STATES or to_state not in STATES:
        raise IllegalTransition(
            f"unknown state: from={from_state!r} to={to_state!r} (must be in {STATES})"
        )
    key = (source, from_state)
    allowed = _ALLOWED.get(key, frozenset())
    if to_state not in allowed:
        raise IllegalTransition(
            f"illegal {from_state}->{to_state} for source={source!r} "
            f"(not in table {key}={sorted(allowed)})"
        )
    return to_state


# ---------------------------------------------------------------
# merge-completion（AC-2）：merged 完结携带 merged_sha 并解除依赖
# ---------------------------------------------------------------

@dataclass
class MergeCompletion:
    card_id: str
    merged_sha: str
    unblocked_deps: list = field(default_factory=list)

    def finalize(self, source):
        """merged -> done（仅 CI/完成判定可过）；AGENT 无权完结自己（N12）。"""
        apply(source, "merged", "done")
        return {"state": "done", "merged_sha": self.merged_sha}


# ---------------------------------------------------------------
# reaper 判活 / 进展（AC-3/AC-5）：心跳判活、CI run 判进展
# ---------------------------------------------------------------

def should_reap(heartbeat_ts, now_ts, lease_ttl_sec, ci_running: bool) -> bool:
    """reaper 判据：心跳判活（超期考虑回收），但**运行中的 CI 自动延期**。

    返回 True=该回收。AC-3：CI 运行中 → 视为有进展 → 不回收。
    AC-5：12 分钟无 commit 的 CI —— ci_running=True 时即使心跳很久也未超期 → 保留。
    """
    if ci_running:
        # CI 在跑 → 进展在延续，租约自动延期，绝不回收（长 CI 实验 AC-5）
        return False
    return (now_ts - heartbeat_ts) > lease_ttl_sec


def merge_completion_reconciler(card_id, merged_sha, deps) -> MergeCompletion:
    """merged -> done + merged_sha + unblock_deps 的声明式 reconcile 数据包。"""
    return MergeCompletion(card_id=card_id, merged_sha=merged_sha, unblocked_deps=list(deps))


if __name__ == "__main__":
    import sys

    # 穷举性质测试：身份 × 出发态 × 目标态 —— 每个组合要么定义、要么抛 IllegalTransition。
    sources = set(ALLOWED_TRANSITIONS_BY_SOURCE)
    defined = 0
    for src in sources:
        for f in STATES:
            for t in STATES:
                try:
                    apply(src, f, t)
                    defined += 1
                except IllegalTransition:
                    pass  # 预期：非法组合必须抛

    # 正证：合法转移通过
    assert apply("agent", "ready", "claimed") == "claimed"
    assert apply("agent", "claimed", "in_progress") == "in_progress"
    assert apply("ci", "in_review", "done") == "done"
    assert MergeCompletion("C1", "abc1234", ["D1", "D2"]).finalize("ci")["state"] == "done"

    # 负证 N6：verified -> in_progress 必须抛 IllegalTransition
    _raised = False
    try:
        apply("ci", "verified", "in_progress")
    except IllegalTransition:
        _raised = True
    assert _raised, "verified->in_progress must raise IllegalTransition (N6)"

    # 负证：agent 无权写 done（N19/N30 收口到 verify 侧亦是）
    _agent_done = False
    try:
        apply("agent", "in_review", "done")
    except IllegalTransition:
        _agent_done = True
    assert _agent_done, "agent must NOT be able to write done (N19/N30)"

    # AC-3/AC-5：长 CI -> 不回收
    now = 1_000_000
    assert should_reap(heartbeat_ts=now - 10_000, now_ts=now, lease_ttl_sec=60, ci_running=True) is False, "CI 运行中不得回收"
    assert should_reap(heartbeat_ts=now - 10_000, now_ts=now, lease_ttl_sec=60, ci_running=False) is True

    print(f"OK: exhaustive transitions green; defined={defined}/{len(sources)*len(STATES)**2} "
          f"(rest raise IllegalTransition); N6 verified->in_progress blocked; "
          f"agent-done blocked; long-CI not reaped (AC-5)")
    sys.exit(0)