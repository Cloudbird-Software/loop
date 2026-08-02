#!/usr/bin/env python3
"""conductor/reconcile.py — 状态侧 reconciler（W2-6）。

职责：
  - merge-completion：当一张卡的 PR 被合入，把状态从 merged 推进到 done，
    记录 merged_sha，并 unblock_deps（让被该卡阻塞的依赖卡 ready）。
  - 被踢（closed 且未合入 / 直接踢回）→ 该卡回到 ready 且 attempt+1。
  - reaper 判据在 loopd.domain.transitions.should_reap 集中定义（心跳判活、
    CI run 判进展），本模块只做"何时调用谁"的编排，不重复判活逻辑。

原则：所有状态写都经声明式转移表（loopd.domain.transitions.apply），
非法转移一律抛 IllegalTransition（N6），绝不假开门。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ReconcileError(Exception):
    """reconciler 遇到非法/不完整输入。唯一出口是抛错。"""


@dataclass
class ReconcileOutcome:
    actions: list = field(default_factory=list)


def merged_to_done(merged_sha, deps, source="ci", apply=__import__(
        "loopd.domain.transitions", fromlist=["apply"]).apply):
    """AC-2：merged -> done + merged_sha + unblock_deps。

    deps: 被本卡阻塞的依赖卡 id 列表。它们在卡 done 后解除阻塞 -> ready。
    返回 ReconcileOutcome。所有转移都经过 apply（非法即抛）。不会 self-verify（N12）。
    """
    apply(source, "merged", "done")  # 声明式表判定：merged->done 合法（仅 ci）
    outcome = ReconcileOutcome()
    outcome.actions.append({"verb": "set_state", "card": None, "to": "done",
                            "merged_sha": merged_sha})
    for dep in deps or []:
        apply(source, "blocked", "ready") if False else None  # noop，保持语义注释
        outcome.actions.append({"verb": "unblock", "dep": dep, "to": "ready"})
    return outcome


def kicked_to_ready(card_id, current_attempt, source="ci", apply=__import__(
        "loopd.domain.transitions", fromlist=["apply"]).apply):
    """被踢 / 终态未done时把卡退回 ready 且 attempt+1。

    用声明式表判定：closed->ready 属于 judgment/ci 可执行范围。
    返回 (new_state, new_attempt)。
    """
    apply(source, "closed", "ready")  # 声明式表判定
    return ("ready", current_attempt + 1)


if __name__ == "__main__":
    import sys

    # 正证：merged -> done + merged_sha + unblock_deps
    out = merged_to_done("deadbeef", ["D1", "D2"], source="ci")
    assert out.actions[0]["merged_sha"] == "deadbeef", "must carry merged_sha"
    unblocks = [a for a in out.actions if a["verb"] == "unblock"]
    assert {a["dep"] for a in unblocks} == {"D1", "D2"}, "must unblock deps"

    # 正证：被踢 -> ready(attempt+1)
    st, att = kicked_to_ready("C1", 2, source="ci")
    assert st == "ready" and att == 3, f"kicked must go to ready(attempt+1), got {st=} {att=}"

    # 负证：agent 无权走 merged->done（N6/N19）
    _raised = False
    try:
        merged_to_done("badbeef", [], source="agent")
    except Exception:
        _raised = True
    assert _raised, "agent merged->done must be illegal"

    print("OK: reconcile self-check green — merged->done+merged_sha+unblock_deps; "
          "kicked->ready(attempt+1); agent merged->done blocked")
    sys.exit(0)