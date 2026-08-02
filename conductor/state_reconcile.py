#!/usr/bin/env python3
"""conductor/state_reconcile.py — 事件-投影对账纯库（W3-9）。

W2 关闭判定"事件-投影对账连续 72h diff=0"：把事件日志里记录的**状态迁移**
与当前投影状态（card 的 state 字段）做 diff 判定。本模块为纯库：

  - reconcile(events, projection) -> ReconcileResult：比对每类迁移事件是否与投影一致；
  - 反真空（覆盖率）：空日志 → coverage=0 → 判 FAIL，绝不"真空绿"（N29）；
  - 反 fail-open（N30/N31）：存在与投影不符的伪造/断链事件 → diff≠0，产生 incident；
  - 开 Incident 不在本库（纯库不碰 gh），由 tick（W3-TK）按 result.incidents 落 issue。
"""
from __future__ import annotations

import json
import pathlib

from conductor import events as _events


class ReconcileResult:
    """一次对账结果。

    - events_total  : 读到的迁移事件总数（坏行已剔除）
    - coverage      : 去重后的迁移类型数（READY→CLAIMED / CLAIMED→DONE 之类）
    - diff          : 与投影不符的事件数（0 = 完全一致）
    - mismatches    : 逐条不符说明（客观描述）
    - incidents     : 需要上报 Incident 的理由（diff≠0 或空日志）
    """

    __slots__ = ("events_total", "coverage", "diff", "mismatches", "incidents", "ok")

    def __init__(self, events_total, coverage, diff, mismatches, incidents):
        self.events_total = events_total
        self.coverage = coverage
        self.diff = diff
        self.mismatches = mismatches
        self.incidents = incidents
        # 反真空 + 反 fail-open：空日志或存在 diff 都不算 ok
        self.ok = (events_total > 0) and (diff == 0)

    def to_dict(self):
        return {
            "events_total": self.events_total,
            "coverage": self.coverage,
            "diff": self.diff,
            "mismatches": self.mismatches,
            "incidents": self.incidents,
            "ok": self.ok,
        }


def _transition_key(ev):
    """从一条事件提取迁移类型 key。

    - 优先用 ev["transition"]（如 "ready->claimed"）；
    - 否则从 ev.get("from")/ev.get("to") 拼；
    - 没有迁移语义的事件（心跳/元事件）返回 None（不计覆盖率，也不参与 diff）。
    """
    t = ev.get("transition")
    if isinstance(t, str) and "->" in t:
        return t.strip()
    frm = ev.get("from") or ev.get("dist_from")
    to = ev.get("to") or ev.get("dist_to") or ev.get("state")
    if frm or to:
        return f"{frm or '*' }->{to or '?'}"
    return None


def reconcile(events, projection=None, transition_fn=None):
    """对账：事件日志记录的迁移 vs 投影状态。

    参数:
      events      : 事件列表（每项 dict）——来自 events.load_events/append_event；
      projection  : {card_id: current_state} 或 None（None 表示"无投影、全部视为断链"）。
      transition_fn: 可选，由事件反推"投影应处状态"的函数 ev -> state；
                    缺省按 transition 箭头右端取值（ready->claimed → claimed）。

    返回 ReconcileResult：
      - 空日志  → coverage=0、incident="empty event log"，ok=False（反真空，N29）；
      - 事件声称的迁移与投影不符 → diff+=1、逐条 mismatch（反 fail-open，N30）；
      - 否则 ok=True、diff=0（覆盖每类已发生迁移）。
    """
    transition_fn = transition_fn or (lambda ev: _default_projected_state(ev))
    if projection is None:
        projection = {}

    if not events:
        return ReconcileResult(
            events_total=0, coverage=0, diff=0, mismatches=[],
            incidents=["empty event log: coverage FAIL (anti-vacuum, N29)"],
        )

    seen_types = {}
    mismatches = []
    diff = 0
    for ev in events:
        key = _transition_key(ev)
        if key is None:
            continue
        seen_types[key] = seen_types.get(key, 0) + 1
        card = ev.get("card") or ev.get("card_id") or ev.get("id")
        expected = transition_fn(ev)
        actual = projection.get(card) if card is not None else None
        # 无投影（None）或投影与该事件预期不符 → 断链/伪造 → diff+1
        if actual is None or (expected is not None and actual != expected):
            diff += 1
            mismatches.append(
                f"card={card} transition={key} expected_state={expected} projected={actual}"
            )

    incidents = []
    if diff > 0:
        incidents.append(f"reconcile diff={diff} (event-vs-projection mismatch, N30/N31)")
    return ReconcileResult(
        events_total=len(events), coverage=len(seen_types), diff=diff,
        mismatches=mismatches, incidents=incidents,
    )


def _default_projected_state(ev):
    """迁移事件预期投影状态：取 transition 箭头右端（如 ready->claimed → claimed）。"""
    t = ev.get("transition")
    if isinstance(t, str) and "->" in t:
        return t.split("->", 1)[1].strip()
    return ev.get("to") or ev.get("dist_to") or ev.get("state")


def reconcile_check(events, projection=None, transition_fn=None):
    """供 tick / CLI 调用的 exit-code 形入口：不一致或空日志 → 返回非 0。"""
    res = reconcile(events, projection=projection, transition_fn=transition_fn)
    if not res.ok:
        raise _ReconcileFailed("\n".join(res.incidents) or "reconcile failed")
    return 0


class _ReconcileFailed(Exception):
    """对账失败（diff≠0 或空日志），由调用方捕获后开 Incident；不静默吞。"""

    def __init__(self, msg):
        super().__init__(msg)
        self.message = msg


def reconcile_from_dir(events_dir, projection=None, transition_fn=None):
    """从 events 目录读取全部事件后对账（events.load_events 封装）。"""
    rows, bad = _events.load_events(events_dir)
    res = reconcile(rows, projection=projection, transition_fn=transition_fn)
    res.events_total = len(rows)
    if bad:
        res.diff += bad
        res.incidents.append(f"unparseable event rows={bad}")
    return res