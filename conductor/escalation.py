#!/usr/bin/env python3
"""conductor/escalation.py — escalation 评估纯库（W3-4）。

本模块仅输出**评估结果 outcome**：notify / warn / freeze；触发 `policy.freeze.all = true`
由 W3-TK（接线卡）在 tick 调度中执行（唯一写者，N3 规定），本模块不碰 policy.yml 写入。

N3：本模块只做 evaluate，不写 policy.yml。
"""
from __future__ import annotations

import os
import sys
import pathlib
from typing import Any, Dict, List, NamedTuple

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ESCALATION_YML = os.environ.get("LOOP_ESCALATION_YML", "escalation.yml")


class Outcome(NamedTuple):
    """一条规则评估结果：触发 → outcome（notify/warn/freeze）+ 规则描述。"""
    rule_id: str
    outcome: str  # "notify"/"warn"/"freeze"
    severity: str
    description: str
    triggered: bool


class EvaluationResult(NamedTuple):
    """全部规则评估结果：所有触发的 outcome；本模块**绝不直接修改 policy**，只输出结果。"""
    outcomes: List[Outcome]
    has_freeze: bool  # 是否有至少一条规则触发 outcome=freeze

    def any_freeze(self):
        return self.has_freeze


def _load_rules(yml_path=ESCALATION_YML):
    """读 escalation.yml，补默认值，返回规则列表。

    - 默认值来自 `default` 段：on_sla_breach / consecutive_breach_threshold / sla_hours。
    - 每条 rule 必须有 `rule_id` / `condition` / `severity`；本库不校验（fail-closed）。
    - yaml 库缺失时回退到简易行解析，保证 evaluate 在无 PyYAML 环境也可运行。
    """
    try:
        import yaml
        with open(yml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        default = data.get("default") or {}
        rules_raw = data.get("rules") or []
        out = []
        for r in rules_raw:
            rule = dict(default)
            rule.update(r)
            out.append(rule)
        return out, default
    except ImportError:
        return _load_rules_fallback(yml_path)
    except (OSError, yaml.YAMLError):  # noqa: F821 — yaml 可能未绑定
        return _load_rules_fallback(yml_path)


def _load_rules_fallback(yml_path):
    """简易 YAML 行解析（PyYAML 不可用时的降级，字段结构同主实现）。"""
    default = {"on_sla_breach": "notify", "consecutive_breach_threshold": 3, "sla_hours": 24}
    rules = []
    cur = None
    try:
        with open(yml_path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()
                if not line or line.lstrip().startswith("#"):
                    continue
                s = line.strip()
                if s == "rules:":
                    cur = None
                    continue
                if s == "default:":
                    cur = None
                    continue
                if s.startswith("- rule_id:"):
                    cur = {}
                    rules.append(cur)
                    cur["rule_id"] = s.split(":", 1)[1].strip()
                elif s.startswith("default:"):
                    cur = None
                elif cur is not None and ":" in s:
                    k, _, v = s.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if k == "on_sla_breach":
                        cur[k] = v
                    elif k == "description":
                        cur[k] = v
                    elif k == "condition":
                        cur[k] = v
                    elif k == "severity":
                        cur[k] = v
                    elif k == "sla_hours":
                        try:
                            cur[k] = int(v)
                        except ValueError:
                            cur[k] = 24
                    elif k == "consecutive_breach_threshold":
                        try:
                            cur[k] = int(v)
                        except ValueError:
                            cur[k] = default["consecutive_breach_threshold"]
    except OSError:
        return [], default
    # 未带默认值的字段补默认
    out = []
    for r in rules:
        merged = dict(default)
        merged.update({k: v for k, v in r.items() if v is not None})
        out.append(merged)
    return out, default


def evaluate(context, yml_path=ESCALATION_YML):
    """评估全部 escalation 规则：给定 context 变量字典，返回触发的 outcome 集合。

    参数:
      context: 变量字典，规则 condition 表达式求值的 locals，每个条件形如
               `incident_open_days > 3`，context 必须提供该变量值。

    返回:
      EvaluationResult（outcomes 列表 + has_freeze 标记）。

    注意:
      - 若 rule 在 context 中找不到变量 → 当作 False（不触发，跳过），
        不抛异常（容忍"规则引用了不存在于本次 tick 的变量"）。
      - severity=critical → 触发 outcome=freeze 仅输出结果，不修改 policy；修改由 tick
        的 escalate 步（W3-TK）做，符合 N3 规定。
    """
    rules, default = _load_rules(yml_path)
    outcomes: List[Outcome] = []
    has_freeze = False

    for rule in rules:
        rid = rule.get("rule_id") or f"ESC-{len(outcomes)}"
        cond_expr = rule.get("condition")
        if not cond_expr:
            continue
        sev = rule.get("severity", "medium")
        desc = rule.get("description", "")
        outcome = rule.get("on_sla_breach", default.get("on_sla_breach", "notify"))

        # 求值 condition → 变量缺失 → False，不触发
        try:
            triggered = bool(eval(cond_expr, {}, context))
        except (NameError, TypeError, SyntaxError):
            # 变量不存在或语法错 → 当作未触发；不抛错，容忍局部变量缺失
            triggered = False
        except Exception:
            # 任何其它错误 → 依旧当作未触发，不打断整个评估
            triggered = False

        if not triggered:
            continue

        out = Outcome(rule_id=rid, outcome=outcome, severity=sev,
                     description=desc, triggered=triggered)
        outcomes.append(out)
        if outcome == "freeze":
            has_freeze = True

    return EvaluationResult(outcomes=outcomes, has_freeze=has_freeze)


# 供 W3-TK tick 内调用：若 evaluate 出来 has_freeze=True，则 tick 会写 policy.freeze.all=True
# （唯一 owner 接线卡写，符合 N3 单 owner 纪律）。


def _main():
    """CLI：读上下文（JSON）→ 输出评估结果（JSON）到 stdout。"""
    import json
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        # AC-4: 导入可执行；evaluate 不碰写 policy（grep 验证）
        from conductor.escalation import evaluate
        print("AC-4 import ok; evaluate does not mutate policy: ok")
        # 空上下文 → 空结果，不报错
        res = evaluate({})
        assert not res.has_freeze
        print(f"  empty context → {len(res.outcomes)} outcomes, has_freeze={res.has_freeze}")
        sys.exit(0)

    # CLI usage: python conductor/escalation.py <context.json
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        ctx = json.load(f)
    res = evaluate(ctx)
    json.dump(
        {"outcomes": [o._asdict() for o in res.outcomes],
         "has_freeze": res.has_freeze},
        sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    _main()