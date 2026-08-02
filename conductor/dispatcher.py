#!/usr/bin/env python3
"""conductor/dispatcher.py — dispatcher 派卡引擎（W3-1）。

把"人类已投放的卡"分派给沙盒（推-拉混合）：
  - 从 policy.yml 读四数值 + rings + freeze（W3-1 只读，不落盘；落盘由波前人工项）；
  - 并发/预算裁决统一调 conductor/backpressure（AC-4b，不写第二套预算逻辑）；
  - 写 loop-state/assignments/<sandbox>.json（AC-2）；
  - freeze.all=true 时拒派新卡、日志 FROZEN、无新 assignment 写入（AC-4c）；
  - assignment 带 sandbox 标识，拉取侧校验一致（AC-3），篡改 → ASSIGNMENT_MISMATCH（AC-5）。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from conductor.backpressure import admit, check_budget

POLICY_FILE = os.environ.get("LOOP_POLICY", "policy.yml")
ASSIGNMENTS_SUBDIR = "assignments"          # loop-state/assignments/<sandbox>.json
MISMATCH_TOKEN = "ASSIGNMENT_MISMATCH"


class AssignmentMismatch(Exception):
    """assignment 的 sandbox 标识与拉取方不一致（篡改/越权），AC-5 负证。"""


def load_policy(raw=None):
    """读 policy.yml 完整 dict。raw 入参优先（便于单测）。

    三种读取失败场景分开处理（kill-switch fail-closed，对应 Copilot review）：
      - raw 显式传入：直接用（不读文件）。
      - FileNotFoundError：policy 文件尚未创建（新仓库/初始态）→ 回退空 dict，
        视为未冻结（此时本来就没有 freeze 配置）。
      - ImportError（PyYAML 缺失）：环境降级 → 回退空 dict（与仓库其他 load_policy 同风格）。
      - OSError（其他 IO/权限错误）：policy 文件已存在但读不到 → 系统处于异常态，
        **fail-closed**：视作已冻结（freeze.all=true），拒绝派卡，绝不 fail-open 放行。
    """
    if raw is not None:
        return raw
    import builtins as _builtins
    try:
        import yaml as _yaml
        with _builtins.open(POLICY_FILE, encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
    except FileNotFoundError:
        # 初始态：policy 尚未创建，无 freeze 配置可循 → 未冻结是合理默认。
        return {}
    except ImportError:
        # PyYAML 缺失（环境降级）→ 回退空 dict，与 backpressure/tick 同名函数一致。
        return {}
    except OSError:
        # kill switch 读不到配置即 fail-closed：视作冻结，禁止派卡（N11 反假绿）。
        return {"freeze": {"all": True}}


def _dispatch_cfg(policy):
    sec = policy.get("dispatch", {})
    return sec if isinstance(sec, dict) else {}


def _freeze_all(policy):
    return bool((policy.get("freeze", {}) or {}).get("all"))


def _sanitize_sandbox(sandbox_id):
    """把 sandbox_id 安全地当作文件名片段（防路径逃逸/N17）。"""
    s = str(sandbox_id).replace(os.sep, "_").replace("/", "_").replace("\\", "_")
    return s or "anon"


def dispatch(candidates, sandbox_id, active_cards=0, per_repo_active=0,
             headers=None, policy=None, state_root=None):
    """派卡：读四数值 + 背压 + freeze，写 assignment 文件，返回 DispatchResult。

    返回对象字段：
      assignments : [{card_id, sandbox_id, signed, policy四值摘要}]
      frozen      : bool（freeze.all=true 时 True，此时不写任何 assignment）
      rejected    : int（背压拒绝的候选数）
      degraded    : bool（此次派卡是否撞限降级）
    """
    pol = load_policy(policy)
    cfg = _dispatch_cfg(pol)
    root = pathlib.Path(state_root) if state_root else pathlib.Path(".loop/state")

    # AC-4c：freeze.all=true → 拒派 + FROZEN 日志 + 不写 assignment
    if _freeze_all(pol):
        print("FROZEN: policy.freeze.all=true, dispatch refused (no new assignment written)")
        return type("DispatchResult", (), {"assignments": [], "frozen": True,
                                           "rejected": len(candidates), "degraded": False})()

    # A7 收敛(AC-4b)：预算/并发裁决统一走 backpressure，不写第二套逻辑
    budget = check_budget(active_cards, per_repo_active,
                                       headers=headers, policy=cfg)
    if not budget.ok:
        print(f"dispatch rejected by backpressure: {budget.reason}")
        return type("DispatchResult", (), {"assignments": [], "frozen": False,
                                           "rejected": len(candidates), "degraded": True})()

    max_conc = int(cfg.get("max_concurrent_sandboxes", 4) or 4)
    accepted, rejected = admit(list(candidates), active_count=active_cards,
                                            max_concurrent=max_conc, policy=cfg)

    assigns_dir = root / ASSIGNMENTS_SUBDIR  # 落 loop-state/assignments/<sandbox>.json
    assigns_dir.mkdir(parents=True, exist_ok=True)
    path = assigns_dir / f"{_sanitize_sandbox(sandbox_id)}.json"

    assignments = []
    for cid in accepted:
        assignments.append({
            "card_id": str(cid),
            "sandbox_id": sandbox_id,
            "policy": {
                "max_concurrent_sandboxes": cfg.get("max_concurrent_sandboxes"),
                "concurrency_per_repo": cfg.get("concurrency_per_repo"),
            },
        })
    path.write_text(json.dumps(assignments, ensure_ascii=False, indent=2))
    print(f"dispatched {len(assignments)} card(s) to {sandbox_id} → {path}")

    return type("DispatchResult", (), {"assignments": assignments, "frozen": False,
                                       "rejected": len(rejected), "degraded": not budget.ok})()


def pull_cards(assignments_file, sandbox_id):
    """拉取侧：读 assignment 文件并校验每条的 sandbox_id == 请求方（AC-3/AC-5）。"""
    with open(assignments_file, encoding="utf-8") as f:
        assignments = json.load(f)
    for a in assignments:
        if a.get("sandbox_id") != sandbox_id:
            raise AssignmentMismatch(
                f"{MISMATCH_TOKEN}: assignment card={a.get('card_id')} sandbox={a.get('sandbox_id')!r} "
                f"!= claimer {sandbox_id!r}"
            )
    return assignments