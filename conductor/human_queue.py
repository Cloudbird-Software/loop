#!/usr/bin/env python3
"""conductor/human_queue.py — 人类决策队列纯库（W3-5）。

人类决策自动入列 + SLA 计时 + digest 组装（引用 escalation 输出，SLA 排序）。
本模块为纯库：只做入列/组装，调度与 digest 步注册由 W3-TK（接线卡）负责。

N30：非白名单身份调用 add_decision 会被拒绝（raise/quarantine），杜绝伪造人工决定。
"""
from __future__ import annotations

import datetime
import os

# 唯一规则键 → SLA（小时）。keys 必须全局唯一（AC-4）。
RULES = {
    "human_merge": 24,     # 人类决定合并上限 24h
    "human_waiver": 12,    # 豁免决定 12h
    "human_decision": 48,  # 设计/架构决策 48h
}

# 允许调用 add_decision 的身份白名单（可被 env 覆盖，用于测试）
DEFAULT_IDENTITIES = {"loop-conductor", "humans", "planner", "lead", "mechanism"}


def _identity(env=None):
    return (os.environ if env is None else env).get("LOOP_IDENTITY", "")


def _allowed(env=None):
    raw = (os.environ if env is None else env).get("LOOP_IDENTITY_ALLOW", "")
    if raw:
        return {x.strip() for x in raw.split(",") if x.strip()}
    return set(DEFAULT_IDENTITIES)


class PermissionDenied(Exception):
    """非白名单身份尝试入队决策（N30），fail-closed。"""


def add_decision(decision, env=None, identity=None):
    """入列一条人类决策（带 SLA 计时）。

    - 校验调用身份 ∈ 白名单，否则抛 PermissionDenied（AC-6）；
    - 决策需含 rule（唯一规则键）与 payload；rule 必须已在 RULES 注册（否则抛 KeyError）；
    - 附 sla_hours / enqueued_at / due_by（enqueued_at + sla）。
    """
    identity = identity if identity is not None else _identity(env)
    if identity not in _allowed(env):
        raise PermissionDenied(f"identity '{identity or '<none>'}' not whitelisted (N30)")

    rule = decision.get("rule")
    if rule not in RULES:
        raise KeyError(f"unknown human-decision rule '{rule}'; registered: {sorted(RULES)}")

    sla_h = RULES[rule]
    now = datetime.datetime.now(datetime.timezone.utc)
    entry = dict(decision)
    entry.setdefault("sla_hours", sla_h)
    entry.setdefault("enqueued_at", now.isoformat().replace("+00:00", "Z"))
    entry.setdefault("due_by", (now + datetime.timedelta(hours=sla_h)).isoformat().replace("+00:00", "Z"))
    return entry


def build_digest(decisions, escalation_outcome=None):
    """组装 digest：按 SLA 到期语义给列，SLA 升序（最紧急置顶），并引用 escalation 输出。

    参数:
      decisions        : add_decision 返回的 entry 列表
      escalation_outcome: escalation 库 evaluate 的 EvaluationResult（可选），
                          有则把其中的 notify/freeze 摘要并入 digest（引用 escalation 输出）。

    返回 dict:
      rows        : [ {rule, subject, severity?, sla_hours, due_by, status} ... ]，按 due_by 升序
      sla_column  : "due_by"（含到期时间列）
      escalation  : escalation 输出的摘要（或 None）
    """
    rows = []
    for d in decisions:
        rows.append({
            "rule": d.get("rule"),
            "subject": d.get("subject", d.get("payload", "")),
            "severity": d.get("severity"),
            "sla_hours": d.get("sla_hours"),
            "due_by": d.get("due_by"),
            "enqueued_at": d.get("enqueued_at"),
            "status": d.get("status", "pending"),
        })
    # SLA 升序：到期越早越靠前（AC-5 要求 SLA 降序或到期时间列——这里输出 due_by 到期列并升序）
    rows.sort(key=lambda r: r.get("due_by") or "")

    esc = None
    if escalation_outcome is not None:
        esc = {
            "has_freeze": bool(getattr(escalation_outcome, "has_freeze", False)),
            "outcomes": [
                {"rule_id": o.rule_id, "outcome": o.outcome, "severity": o.severity}
                for o in getattr(escalation_outcome, "outcomes", [])
            ],
        }

    return {
        "rows": rows,
        "sla_column": "due_by",
        "escalation": esc,
    }