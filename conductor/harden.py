#!/usr/bin/env python3
"""conductor/harden.py — 信任单调下降：把已确认 claim 固化为确定性 lens（R12-6）。

强模型验收环的产出（claim）经独立复现确认（REPRODUCED）后，若同一
suggested_checker 被确认达 policy.yml review.harden_after_confirms 次（默认 2），
则强制开「写检查器」卡，把该缺陷类别固化成 lenses/ 下的确定性 lens / 检查器。

固化后该缺陷类别不再依赖模型判断——系统对模型的信任单调下降，永不回升。
本模块是「已固化检查器」注册表（lenses/README.md）的唯一维护入口。

外部入口：
  should_harden(claim, confirmed_history, policy=None) — 是否达到固化阈值
  create_harden_card(claim, role="materializer")        — 开「写检查器」Card
  register_lens(name, source_claim_id, defect_category, false_positive_rate=0.0)
                                                         — 在 lenses/README.md 登记（幂等）
  is_already_hardened(suggested_checker)                 — 该检查器是否已固化
  demote_future_claims(suggested_checker, claim, policy=None)
                                                         — 已固化且检查器绿 → 降权 0.5×
  get_hardened_lenses()                                  — 读注册表，返回已固化列表

铁律：
- 单向阀门：create_harden_card 复用 materialize._enforce_role(role, "Card")，
  只有 materializer（及 incident）可造 Card。
- 幂等：register_lens 同名 lens 重复登记不产生重复行。
- 保守：demote_future_claims 仅在「已固化 + 确定性检查器当前绿（exit 0）」时降权；
  无法确认绿（检查器缺失/崩溃/非零退出）则不降权。
"""
import datetime
import json
import os
import pathlib
import subprocess

POLICY_PATH = os.environ.get("POLICY_PATH", "policy.yml")
LENS_REGISTRY_PATH = os.environ.get("LENS_REGISTRY_PATH", "lenses/README.md")
LENS_RUN_TIMEOUT_SEC = 120
DEFAULT_HARDEN_AFTER_CONFIRMS = 2

# 仓库根（与 gates/run_gates.py 同样从 __file__ 推导，不依赖 cwd）
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# policy 读取
# ============================================================
def _load_policy():
    try:
        import yaml
        with open(POLICY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _harden_after_confirms(policy=None):
    """读 policy.yml review.harden_after_confirms（默认 2）。"""
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    if not isinstance(review, dict):
        review = {}
    n = review.get("harden_after_confirms", DEFAULT_HARDEN_AFTER_CONFIRMS)
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = DEFAULT_HARDEN_AFTER_CONFIRMS
    return n if n > 0 else DEFAULT_HARDEN_AFTER_CONFIRMS


# ============================================================
# 注册表解析（lenses/README.md 的 markdown 表）
# ============================================================
def _parse_registry_table(text):
    """解析 lenses/README.md 中的固化注册表，返回 dict 列表。

    表头标记列：固化日期。表行以 `|` 起，分隔行（---）跳过，遇非 `|` 行即表结束。
    每条：{name, source_claim_id, hardened_date, defect_category, false_positive_rate}。
    """
    entries = []
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and "固化日期" in line:
            header_idx = i
            break
    if header_idx is None:
        return entries
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break  # 表结束
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # 跳过分隔行（|---|---|...）
        if all(c.startswith("-") for c in cells if c.strip()):
            continue
        if len(cells) >= 5:
            try:
                fpr = float(cells[4])
            except (ValueError, TypeError):
                fpr = 0.0
            entries.append({
                "name": cells[0],
                "source_claim_id": cells[1],
                "hardened_date": cells[2],
                "defect_category": cells[3],
                "false_positive_rate": fpr,
            })
    return entries


def get_hardened_lenses():
    """读 lenses/README.md 注册表，返回已固化检查器列表。

    每条 dict：{name, source_claim_id, hardened_date, defect_category, false_positive_rate}。
    """
    p = pathlib.Path(LENS_REGISTRY_PATH)
    if not p.exists():
        return []
    return _parse_registry_table(p.read_text(encoding="utf-8"))


def is_already_hardened(suggested_checker):
    """该 suggested_checker 是否已在 lenses/README.md 注册表登记。"""
    return any(e["name"] == suggested_checker for e in get_hardened_lenses())


# ============================================================
# should_harden：是否达到固化阈值
# ============================================================
def should_harden(claim, confirmed_history, policy=None):
    """是否应把该 claim 的 suggested_checker 固化为确定性 lens。

    条件：
    1. claim 带 suggested_checker 字段
    2. confirmed_history 中同一 suggested_checker 被 REPRODUCED 确认的次数
       >= policy.review.harden_after_confirms（默认 2）

    confirmed_history: 已确认 claim 记录列表（dict）。每条若带 verdict 字段，
    仅 verdict == "REPRODUCED" 计数；无 verdict 字段则视为已确认（既在
    confirmed_history 中即已确认）。

    返回 (should_harden: bool, reason: str)。
    """
    if not isinstance(claim, dict):
        return False, "claim is not a dict"
    suggested = claim.get("suggested_checker")
    if not suggested:
        return False, "claim has no suggested_checker field"
    threshold = _harden_after_confirms(policy)
    count = 0
    for item in (confirmed_history or []):
        if not isinstance(item, dict):
            continue
        if item.get("suggested_checker") != suggested:
            continue
        verdict = item.get("verdict")
        if verdict is None or verdict == "REPRODUCED":
            count += 1
    if count >= threshold:
        return True, (f"suggested_checker '{suggested}' confirmed {count} time(s) "
                      f">= harden_after_confirms({threshold})")
    return False, (f"suggested_checker '{suggested}' confirmed {count} time(s) "
                   f"< harden_after_confirms({threshold})")


# ============================================================
# create_harden_card：开「写检查器」Card
# ============================================================
def create_harden_card(claim, role="materializer"):
    """开 GitHub issue（Card）请求把 suggested_checker 实现为确定性 lens。

    单向阀门：复用 materialize._enforce_role(role, "Card")——只有 materializer
    （及 incident）可造 Card。Card 的 role 字段为 "impl"（由 impl 落地 lens）。

    Card 字段：state=ready / tier=standard / role=impl / paths=[lenses/<name>.sh]，
    验收标准必含「新检查器能在不调用任何 LLM 的情况下重现该缺陷」，并引用来源 claim_id。
    """
    from conductor import materialize
    materialize._enforce_role(role, "Card")
    if not isinstance(claim, dict):
        raise ValueError("create_harden_card: claim must be a dict")
    suggested = claim.get("suggested_checker")
    if not suggested:
        raise ValueError("create_harden_card: claim has no suggested_checker")
    claim_id = claim.get("id", "")
    lens_path = f"lenses/{suggested}.sh"
    card = {
        "schema": 1,
        "id": f"HARDEN-{suggested}",
        "state": "ready",
        "tier": "standard",
        "role": "impl",
        "claim_id": claim_id,
        "source_claim_id": claim_id,
        "suggested_checker": suggested,
        "objective": f"将已确认的 suggested_checker '{suggested}' 固化为确定性 lens",
        "paths": [lens_path],
        "acceptance": [
            "新检查器能在不调用任何 LLM 的情况下重现该缺陷",
            f"lenses/{suggested}.sh 在缺陷存在时非零退出、缺陷消失时 exit 0（确定性行为）",
            f"在 lenses/README.md 注册表登记：register_lens('{suggested}', '{claim_id}', ...)",
        ],
    }
    body = f"""```json loop
{json.dumps(card, indent=2, ensure_ascii=False)}
```

**来源 claim:** {claim_id or '(未提供)'}
**Objective:** {card['objective']}
**Tier:** standard  **Role:** impl
**Paths:** {lens_path}

## Acceptance Criteria
"""
    for i, ac in enumerate(card["acceptance"], 1):
        body += f"{i}. {ac}\n"
    body += (
        f"\n> 本卡由 conductor/harden.py 按 R12-6「信任单调下降」原则生成："
        f"同一 suggested_checker `{suggested}` 已被强模型验收环复现确认达 "
        f"policy.yml review.harden_after_confirms 阈值，需固化为确定性 lens。\n"
    )
    args = ["issue", "create", "-R", materialize.REPO,
            "--title", f"[Card] HARDEN-{suggested} — 固化确定性 lens",
            "--label", "card",
            "--body", body]
    p = materialize.gh(*args)
    if p.returncode == 0:
        url = p.stdout.strip()
        print(f"  → Harden Card created: {url}")
        return url
    print(f"  ⚠ Harden Card creation failed for '{suggested}': {p.stderr}")
    return None


# ============================================================
# register_lens：在 lenses/README.md 登记已固化检查器（幂等）
# ============================================================
def register_lens(name, source_claim_id, defect_category, false_positive_rate=0.0):
    """在 lenses/README.md 注册表追加一行；同名 lens 已存在则不重复登记。

    返回 True 表示新增了一行；False 表示已存在（幂等 no-op）。
    """
    p = pathlib.Path(LENS_REGISTRY_PATH)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if any(e["name"] == name for e in _parse_registry_table(text)):
        print(f"register_lens: '{name}' already registered (idempotent, no-op)")
        return False
    today = datetime.date.today().isoformat()
    fpr_str = f"{float(false_positive_rate)}"
    new_row = f"| {name} | {source_claim_id} | {today} | {defect_category} | {fpr_str} |"
    lines = text.splitlines(keepends=True)
    # 定位表头行（含「固化日期」）
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and "固化日期" in line:
            header_idx = i
            break
    if header_idx is None:
        # 表不存在：在文件末尾追加一个完整的注册表小节
        section = (
            "\n\n## 已固化检查器\n\n"
            "| lens 名 | 来源 claim id | 固化日期 | 覆盖缺陷类别 | 误报率 |\n"
            "|---|---|---|---|---|\n"
            f"{new_row}\n"
        )
        p.write_text(text.rstrip("\n") + "\n" + section, encoding="utf-8")
        print(f"register_lens: created registry section and registered '{name}'")
        return True
    # 表存在：在表尾（第一行非 `|` 行）前插入新行
    insert_at = None
    for j in range(header_idx + 1, len(lines)):
        if not lines[j].strip().startswith("|"):
            insert_at = j
            break
    if insert_at is None:
        insert_at = len(lines)
    lines.insert(insert_at, new_row + "\n")
    p.write_text("".join(lines), encoding="utf-8")
    print(f"register_lens: registered '{name}' "
          f"(source={source_claim_id}, category={defect_category})")
    return True


# ============================================================
# demote_future_claims：已固化类别 → 降权
# ============================================================
def _lens_script_path(suggested_checker):
    """lenses/<suggested_checker>.sh 的绝对路径（基于注册表所在目录）。"""
    reg = pathlib.Path(LENS_REGISTRY_PATH)
    if not reg.is_absolute():
        reg = pathlib.Path(REPO_ROOT) / reg
    return reg.parent / f"{suggested_checker}.sh"


def _checker_is_green(suggested_checker):
    """运行 lenses/<suggested_checker>.sh；exit 0 视为绿。

    检查器缺失 / 崩溃 / 超时 / 非零退出 → False（保守：无法确认绿则不降权）。
    """
    lens_path = _lens_script_path(suggested_checker)
    if not lens_path.exists():
        return False
    try:
        proc = subprocess.run(
            [str(lens_path)],
            capture_output=True, text=True,
            timeout=LENS_RUN_TIMEOUT_SEC,
            cwd=REPO_ROOT,
        )
        return proc.returncode == 0
    except Exception:
        return False


def demote_future_claims(suggested_checker, claim, policy=None):
    """若该缺陷类别已固化且确定性检查器当前绿 → 给 claim 打 already_hardened 标记并置信度 ×0.5。

    未固化 / 检查器非绿 / 无法确认绿 → 原样返回（不降权）。
    返回（可能修改过的）claim dict。policy 参数预留，当前不影响判定。
    """
    if not isinstance(claim, dict):
        return claim
    if not is_already_hardened(suggested_checker):
        return claim
    if not _checker_is_green(suggested_checker):
        return claim
    claim["already_hardened"] = True
    claim["already_hardened_by"] = suggested_checker
    conf = claim.get("confidence")
    if isinstance(conf, (int, float)):
        claim["confidence"] = conf * 0.5
    return claim
