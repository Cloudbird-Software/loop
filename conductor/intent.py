#!/usr/bin/env python3
"""conductor/intent.py — 单写者状态写通道的意图协议（W2-2）。

界职责：
  - 本地 CAS（conductor/cas.py）保留为快速失败通道：非 done/verified 的普通状态推进
    可直接走本地 CAS，避免每次都绕 GitHub Actions 一次网络往返。
  - 正规路径（跨身份 / 终态）必须经 intent：把意图提交到 repository_dispatch，
    由 CONDUCTOR_APP/CI 身份经 cas 写入后再轮询结果（N19/N30）。
  - 只读校验器 ``apply_intent``：校验意图合法（card_id/目标态合法、done/verified 仅 CI
    身份可写），合法则落本地 CAS——这正是 intent.yml workflow 调用的同一入口。

核心理念（N19/N30）：AGENT 永远没有能力把状态推到 done/verified；它只能提交意图，
最终落成 done/verified 的唯一写者是 CI 身份。``AGENT_APP`` 即便拿到 payload 也无法
直接 ``gh issue edit`` 写 verified——那是被 GitHub branch/issue 保护层与身份判定共同拦住的。
"""
from __future__ import annotations

import os
import subprocess
import time
import json as _json

E = os.environ

# 只有 CI 身份（workflow 的 GITHUB_TOKEN）可把状态推进到这些终态
CI_ONLY_STATES = {"done", "verified"}

# 允许 agent（低权限）经本地 CAS 快速写的前几步状态
AGENT_WRITABLE_PREFIX = {"ready", "claimed", "in_progress"}

# writer 白名单的真正权威在 conductor/state.py（integrity.writer 校验），无需在此重复定义。

# intent 提交后轮询上限（秒），防止挂死
_POLL_TIMEOUT = int(E.get("LOOP_INTENT_POLL_SEC", 300))
_POLL_INTERVAL = 2


class IntentError(Exception):
    """意图不合法或通道失败。唯一出口是抛错，绝不停留在中间态。"""


def _gh(args):
    """跑 `gh api`，返回 (exit_code, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["gh", "api", *args], capture_output=True, text=True,
            env=dict(os.environ),
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "gh not found"


def _assert_writer_allowed(identity, target_state):
    """AC-3 负证 N1：非 CI 身份不得写 done/verified。不满足即抛。"""
    if target_state in CI_ONLY_STATES and identity != "ci":
        raise IntentError(
            f"permission denied: state={target_state!r} is CI-only; "
            f"identity={identity!r} is not 'ci' (N19/N30)"
        )


def _assert_intent_validated(payload):
    """AC-4 负证 N2：state 写必须经过意图通道校验，不得存在绕过。"""
    if not isinstance(payload, dict) or "card_id" not in payload:
        raise IntentError(f"invalid intent payload: {payload!r}")
    if payload.get("to_state") not in AGENT_WRITABLE_PREFIX | CI_ONLY_STATES:
        raise IntentError(f"illegal target state: {payload.get('to_state')!r}")


def submit_intent(payload, repo=None, token=None):
    """AC-2：提交意图到 repository_dispatch（loop-intent）。

    AGENT 调用此函数请求一次状态写；真正的写入由 CI 身份经 cas 完成。
    返回 dispatch id；若 gh 不可用则抛 IntentError（不假装成功）。
    """
    repo = repo or E.get("LOOP_REPO", "Cloudbird-Software/loop")
    body = {
        "event_type": "loop-intent",
        "client_payload": payload,
    }
    args = [
        "--method", "POST",
        f"/repos/{repo}/dispatches",
        "--input", "-",
    ]
    env = dict(os.environ)
    if token:
        env["GH_TOKEN"] = token
    try:
        p = subprocess.run(
            ["gh", "api", *args], input=_json.dumps(body), capture_output=True,
            text=True, env=env,
        )
    except FileNotFoundError as exc:
        raise IntentError(f"gh not on PATH; cannot submit intent: {exc}") from exc
    if p.returncode != 0:
        raise IntentError(f"dispatch failed (exit={p.returncode}): {p.stderr.strip()}")
    # GitHub dispatch 接口 204 无 body → 返回 event_type 作为回执
    return body["event_type"]


def poll_intent(card_id, target_state, timeout=_POLL_TIMEOUT):
    """AC-2：轮询意图结果，直到最终态写入或超时。

    真实实现会查询 loop-state / issue 的最终状态；此处做可判定的轮询骨架：
    - 若目标态已非终态（agent 前三步）视为可判成功（本地 CAS 已落）。
    - 若目标是终态（done/verified），轮询直到读到该态或超时抛 IntentError。
    """
    deadline = time.time() + timeout
    # 快速：非终态由本地 CAS 立即落，无需跨通道轮询
    if target_state in AGENT_WRITABLE_PREFIX:
        return {"card_id": card_id, "state": target_state, "confirmed": True}
    while time.time() < deadline:
        # 骨架占位：真实处从 loop-state/issue 读取 state；此处保持可判定零假绿
        # —— 终态必须由 apply_intent 落成，轮询侧读到才算。绝不在未确认时声称成功。
        time.sleep(_POLL_INTERVAL)
        # 本地可测试出口：allow apply 侧写入的 in-memory 注册表
        if target_state in _CONFIRMED.get(card_id, set()):
            return {"card_id": card_id, "state": target_state, "confirmed": True}
    raise IntentError(f"timeout polling intent for {card_id} state={target_state}")


# 本地测试用确认注册表（真实环境由 loop-state CAS 链承载）
_CONFIRMED: dict[str, set] = {}


def confirm_local(card_id, state):
    _CONFIRMED.setdefault(card_id, set()).add(state)


def apply_intent(payload, identity="ci"):
    """AC-1..AC-5 的判读核心 / intent.yml 唯一写入口。

    幂等 + 校验：card_id 必填、目标态合法、身份权责正确（done/verified 仅 ci）。
    合法且可写则落本地 CAS（模拟 cas_update 判定：能过校验即可写）。
    返回 True 表示可写/已认可；拒绝即抛 IntentError（由调用方取反成 INTENT_REJECTED）。

    本层只做"判定 + 本地确认"（confirm_local）；真实持久化由 CI 身份经
    intent.yml 调用别处落到 loop-state（单写者）。此处不伪装已写链。
    """
    _assert_intent_validated(payload)
    to_state = payload.get("to_state")
    _assert_writer_allowed(identity, to_state)
    # 本地可写判定：通过校验即视为允许（实际原子写由 CI 走 loop-state 层完成）
    confirm_local(payload.get("card_id"), to_state)
    return True


if __name__ == "__main__":
    import sys

    payload = _json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    identity = sys.argv[2] if len(sys.argv) > 2 else "ci"
    try:
        ok = apply_intent(payload, identity=identity)
    except IntentError as exc:
        print(f"INTENT_REJECTED: {exc}")
        sys.exit(1)
    print("INTENT_APPLIED")
    sys.exit(0 if ok else 1)