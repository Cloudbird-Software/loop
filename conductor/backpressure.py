#!/usr/bin/env python3
"""conductor/backpressure.py — 背压纯库（W3-3）。

目标：并发上限 / 每仓上限 / 令牌桶（读 X-RateLimit-Remaining 剩余配额）/ 日预算；
撞限时**显式降级 + 开 Incident（绝不静默 continue，N11）**。

A7 收敛：dispatcher（W3-1）的并发/预算裁决统一调本库，不做第二套独立预算逻辑
（AC-4b）。本库为纯函数，不直接开 GitHub issue——"开 Incident"。
以返回的 degraded/incident 语义表达，由调用方（tick/dispatcher）落到 issue。
"""
from __future__ import annotations

import os
import pathlib
import sys

# 让 `python conductor/backpressure.py` 直接运行也能 import policy（与 tick 同款根修复）
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

POLICY_FILE = os.environ.get("LOOP_POLICY", "policy.yml")


def _load_policy(policy=None):
    """读 policy.yml 的 dispatch 段（每天预算等）。policy 入参优先（便于单测）。

    yaml 缺失或文件不存在时返回空 dict（用默认值），保证背压裁决不为"读取失败"而
    死，但撞限判据依然 fail-closed（拿不到配置即按默认保守值走真实限额）。
    """
    if policy is not None:
        return policy
    try:
        import yaml
        with open(POLICY_FILE) as f:
            data = yaml.safe_load(f) or {}
        sec = data.get("dispatch", {}) or {}
        return sec if isinstance(sec, dict) else {}
    except (ImportError, FileNotFoundError, OSError):
        return {}


class Decision:
    """一次背压裁决结果。degraded=撞限需降级，必带 reason；不静默。"""

    __slots__ = ("ok", "reason", "degraded", "incidents")

    def __init__(self, ok, reason="", degraded=False, incidents=None):
        self.ok = ok
        self.reason = reason
        self.degraded = degraded
        self.incidents = incidents or (["backpressure degraded: " + reason] if degraded else [])

    def __repr__(self):  # pragma: no cover - debug only
        return f"Decision(ok={self.ok}, degraded={self.degraded}, reason={self.reason!r})"


def _header(headers, name):
    if not headers:
        return None
    val = headers.get(name)
    if val is None:
        # GitHub 返回大小写可能不同，遍历小写匹配
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
    return val


def check_budget(active_cards=0, per_repo_active=0, headers=None, policy=None, env=None):
    """背压裁决：并发上限 / 每仓上限 / 令牌桶剩余 / 日预算，任一撞限 → degrade+拒绝。

    参数:
      active_cards     : 当前在跑的总卡数
      per_repo_active  : 当前某仓在跑的卡数
      headers          : gh api 返回的 headers（含 X-RateLimit-Remaining / X-RateLimit-Limit）
      policy           : dispatch 段 dict（缺省读 policy.yml）
      env              : 环境变量覆盖（测试用，缺省 os.environ）

    返回 Decision：
      - LOOP_SIMULATE_BUDGET 设定为 0 → 直接拒绝 + degraded（日预算=0，AC-5 负证）；
      - 并发/每仓/令牌桶/日预算撞限 → ok=False；
      - 全部通过 → ok=True（决策是函数，是否最终投放由 dispatcher 决定）。
    """
    env = os.environ if env is None else env
    cfg = _load_policy(policy)
    max_concurrent = int(cfg.get("max_concurrent_sandboxes", 4) or 4)
    per_repo_cap = int(cfg.get("concurrency_per_repo", 2) or 2)
    token_threshold = float(cfg.get("quota_token_threshold", 0.2) or 0.2)
    daily_budget = float(cfg.get("daily_budget", 30) or 30)

    # AC-5（负证）：LOOP_SIMULATE_BUDGET=0 → 日预算=0 → 拒绝 + degraded + Incident
    sim_budget = env.get("LOOP_SIMULATE_BUDGET")
    if sim_budget is not None and sim_budget != "" and float(sim_budget) == 0:
        return Decision(False,
                        "daily budget is 0 (LOOP_SIMULATE_BUDGET=0); refusing to dispatch",
                        degraded=True)

    if active_cards >= max_concurrent:
        return Decision(False, f"active_cards {active_cards} >= max_concurrent {max_concurrent}", degraded=True)

    if per_repo_active >= per_repo_cap:
        return Decision(False, f"per-repo active {per_repo_active} >= cap {per_repo_cap}", degraded=True)

    # 令牌桶：读 X-RateLimit-Remaining / X-RateLimit-Limit（AC-2/AC-3 grep 目标）
    remaining = _header(headers, "X-RateLimit-Remaining")
    limit = _header(headers, "X-RateLimit-Limit")
    if remaining is not None and limit not in (None, "", "0"):
        try:
            ratio = float(remaining) / float(limit)
            if ratio < token_threshold:  # <20% 降级
                return Decision(False, f"rate-limit remaining {ratio:.0%} < threshold {token_threshold:.0%}", degraded=True)
        except (ValueError, ZeroDivisionError):
            pass  # 非数字头不据此裁决，但仍走其它维度

    # 日预算：读 policy dispatch.daily_budget（非硬编码，AC-3 grep 目标）
    if daily_budget <= 0:
        return Decision(False, f"daily_budget {daily_budget} exhausted/zero", degraded=True)
    return Decision(True, "within budget")


def admit(requests, active_count, max_concurrent=None, policy=None):
    """确定性并发门限：从 candidate 列表里受理最多 max_concurrent-active_count 个，其余拒绝。

    AC-6（行为负证·内联）：并当前置 1 + 投 3 张无冲突卡 → 恰好 1 张进 claimed、
    rejected≥2。不依赖真实时延，纯函数判定。
    """
    cfg = _load_policy(policy)
    cap = max_concurrent if max_concurrent is not None else int(cfg.get("max_concurrent_sandboxes", 4))
    accepted = []
    rejected = []
    for r in requests:
        if len(accepted) + active_count < cap:
            accepted.append(r)
        else:
            rejected.append(r)
    return accepted, rejected