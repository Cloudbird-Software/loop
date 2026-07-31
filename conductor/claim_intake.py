#!/usr/bin/env python3
"""conductor/claim_intake.py — R12-4: 把校验通过的 claim 物化为 state=unconfirmed 的 F-card issue。

reviewer 产出的 claim 经 conductor/claims.py 校验通过后，由本模块在产品仓
（或 loop 仓，视 LOOP_REPO 而定——REPO 复用 materialize.py 的解析）开一张带
`claim` 标签的 GitHub issue，issue 正文里嵌一个 ```json loop``` 块，块内是该
claim 的 F-card 表示（复用 .loop/schemas/finding.json 的 lens/severity/message/
path/evidence 字段），state 初始为 `unconfirmed`。

未复现（state=unconfirmed）的 claim F-card 不可被 impl 领取——这是 wave-level
gate #2 的硬约束。loopd.h_next 与 conductor.tick.race_mode_handler 在领取前
必须调用 is_claim_pickable_by_impl 做显式排除（cards(states=('ready',)) 已按
state 过滤，本函数是 defense-in-depth，确保 state 字段意外被改成 unconfirmed
也不会被领）。

状态机（由 conductor 基于 reproduction 记录推进，reproducer 不自行决定 next_action）：
  REPRODUCED     → state: ready（conductor 自动推进，impl 可领取修复）
  NOT_REPRODUCED → 自动关闭 issue + 评论说明（不进入修复流）
  INCONCLUSIVE   → 进入仲裁队列（加 await-arbitration 标签，不改 state）
"""
import json, pathlib, datetime, tempfile

from conductor.materialize import _enforce_role, REPO, gh
from conductor.blocks import extract_block, inject_block


class CLAIM_NOT_REPRODUCED(Exception):
    """wave-level gate #2：未复现的 claim 不可被路由到 fix。"""


# severity → tier 映射：让转 ready 后的 F-card 能按 prio() 排序
_SEVERITY_TO_TIER = {
    "critical": "critical",
    "high": "critical",
    "medium": "standard",
    "low": "trivial",
}


def _build_fcard(claim, review_doc):
    """把一条 claim 转成 F-card 的 ```json loop``` 块 dict。

    复用 finding.json schema 字段（lens/severity/message/path/evidence），
    并补 state/role/tier/claim_id 等卡片机箱字段，使其能被 loopd.cards() 读取。
    """
    cid = claim.get("id", "")
    cpath = claim.get("path", "")
    rd = review_doc if isinstance(review_doc, dict) else {}
    return {
        "schema": 1,
        "id": cid,
        "state": "unconfirmed",
        "role": "impl",                       # 复现后转 ready 即可被 impl 领取修复
        "tier": _SEVERITY_TO_TIER.get(claim.get("severity", "medium"), "standard"),
        "lens": "review-claim",
        "severity": claim.get("severity", "medium"),
        "message": claim.get("claim", ""),
        "path": cpath,
        "evidence": [{
            "tool": "reviewer",
            "rule_id": cid,
            "location": cpath,
        }],
        "claim_id": cid,
        "paths": [cpath] if cpath else [],
        "review_id": rd.get("review_id", ""),
        "reviewer_model": rd.get("reviewer_model", ""),
        "head_sha": rd.get("head_sha", ""),
        "filed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _claim_issue_body(fcard, claim, review_doc):
    """组装 issue 正文：```json loop``` 块 + 完整 claim JSON（可追溯）+ 评审上下文。"""
    loop_block = f"```json loop\n{json.dumps(fcard, indent=2, ensure_ascii=False)}\n```"
    claim_json = json.dumps(claim, indent=2, ensure_ascii=False)
    rd = review_doc if isinstance(review_doc, dict) else {}
    ctx = {k: rd.get(k) for k in ("review_id", "reviewer_model", "head_sha", "generated_at")
           if rd.get(k) is not None}
    review_json = json.dumps(ctx, indent=2, ensure_ascii=False)
    return (
        f"{loop_block}\n\n"
        f"## Claim (full JSON for traceability)\n\n"
        f"```json\n{claim_json}\n```\n\n"
        f"## Review context\n\n"
        f"```json\n{review_json}\n```\n\n"
        f"> 该 F-card 当前 `state: unconfirmed`——未复现的 claim 不可被 impl 领取"
        f"（R12-4, wave-level gate #2）。待 reproducer 给出 REPRODUCED 裁决后"
        f"由 conductor 推进到 `state: ready`。\n"
    )


def intake_claim(claim, review_doc, role="reviewer"):
    """把一条校验通过的 claim 物化为 state=unconfirmed 的 F-card issue。

    1. 调用 _enforce_role(role, "Claim") 做角色阀门检查（reviewer 才能造 Claim）。
    2. 在 REPO 开 GitHub issue：标签 `claim`，正文含 ```json loop``` 块
       （F-card，state=unconfirmed，复用 finding.json 字段）。
    3. 正文同时包含完整 claim JSON 以便追溯。
    返回 issue number（int）。失败抛异常。
    """
    _enforce_role(role, "Claim")
    if not isinstance(claim, dict):
        raise ValueError("intake_claim: claim must be a dict")
    fcard = _build_fcard(claim, review_doc)
    body = _claim_issue_body(fcard, claim, review_doc)
    title = f"[Claim] {claim.get('id','?')} — {claim.get('claim','')[:60]}"
    p = gh("issue", "create", "-R", REPO,
           "--title", title,
           "--label", "claim",
           "--body", body)
    if p.returncode != 0 or not (p.stdout or "").strip():
        raise RuntimeError(f"intake_claim: gh issue create failed: {p.stderr}")
    return int(p.stdout.strip().split("/")[-1])


def _read_issue_block(issue_num):
    """读 issue 的 ```json loop``` 块 + body，返回 (body, blk) 或 (body, None)。"""
    view = gh("issue", "view", str(issue_num), "-R", REPO, "--json", "body")
    try:
        meta = json.loads(view.stdout or "{}")
    except json.JSONDecodeError:
        return "", None
    body = meta.get("body", "") or ""
    return body, extract_block(body)


def transition_state(issue_num, new_state, reproduction_record=None):
    """根据 reproduction 裁决推进 claim F-card 的状态（conductor 调用）。

    - REPRODUCED     → 把 ```json loop``` 块的 state 推进到 `ready`
                       （CAS：读 body → 替换块 → gh issue edit 写回 → 回读确认）。
    - NOT_REPRODUCED → 自动关闭 issue，并评论说明（引用 reproduction_record）。
    - INCONCLUSIVE   → 加 `await-arbitration` 标签 + 评论，进入仲裁队列
                       （不关、不改 state，仍 unconfirmed 故仍不可被 impl 领）。

    返回 (ok: bool, msg: str)。
    """
    rep = reproduction_record if isinstance(reproduction_record, dict) else {}

    if new_state == "REPRODUCED":
        body, blk = _read_issue_block(issue_num)
        if blk is None:
            return False, f"#{issue_num}: no ```json loop``` block to transition"
        blk["state"] = "ready"
        blk["reproduction_verdict"] = "REPRODUCED"
        blk["reproduced_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if rep.get("reproducer_model"):
            blk["reproducer_model"] = rep.get("reproducer_model")
        new_body = inject_block(body, blk)
        tmp = pathlib.Path(tempfile.gettempdir()) / f"claim-body-{issue_num}.tmp"
        tmp.write_text(new_body)
        gh("issue", "edit", str(issue_num), "-R", REPO, "--body-file", str(tmp))
        # 写后回读确认（CAS 后置校验）
        _, back_blk = _read_issue_block(issue_num)
        if back_blk and back_blk.get("state") == "ready":
            return True, f"#{issue_num}: state → ready (REPRODUCED)"
        return False, f"#{issue_num}: CAS write verification failed"

    if new_state == "NOT_REPRODUCED":
        comment = (
            "🔒 Claim NOT_REPRODUCED — auto-closing (不进入修复流).\n\n"
            f"- reproducer_model: {rep.get('reproducer_model','?')}\n"
            f"- observed.cmd: {(rep.get('observed') or {}).get('cmd','?')}\n"
            f"- diff_note: {rep.get('diff_note','(none)')}\n\n"
            "> 未复现的 claim 不进入修复流（R12-4, wave-level gate #2）。"
        )
        gh("issue", "close", str(issue_num), "-R", REPO, "--comment", comment)
        return True, f"#{issue_num}: closed (NOT_REPRODUCED)"

    if new_state == "INCONCLUSIVE":
        gh("issue", "edit", str(issue_num), "-R", REPO, "--add-label", "await-arbitration")
        note = (
            "⚖ Claim INCONCLUSIVE — entered arbitration queue (label: await-arbitration).\n\n"
            f"- reproducer_model: {rep.get('reproducer_model','?')}\n"
            f"- diff_note: {rep.get('diff_note','(none)')}\n\n"
            "> state 仍为 unconfirmed，不可被 impl 领取；待 planner 仲裁。"
        )
        gh("issue", "comment", str(issue_num), "-R", REPO, "--body", note)
        return True, f"#{issue_num}: await-arbitration (INCONCLUSIVE)"

    return False, f"transition_state: unknown new_state={new_state}"


def is_claim_pickable_by_impl(card_block):
    """显式排除函数：未复现（state=unconfirmed）的 claim F-card 不可被 impl 领取。

    wave-level gate #2 的硬约束。在 loopd.h_next 与 conductor.tick.race_mode_handler
    领取前调用本函数做防御性检查——cards(states=('ready',)) 已按 state 过滤，此处为
    defense-in-depth，确保即使 state 字段意外保留为 unconfirmed 也不会被领。

    返回 True 表示可领；返回 False 表示必须跳过（未复现的 claim）。
    """
    if not isinstance(card_block, dict):
        return True  # 非 dict 块交由其它校验处理，不在此处拦
    if card_block.get("state") == "unconfirmed":
        return False
    return True


def assert_reproduced(card_block):
    """wave-level gate #2 守卫：若 card 仍处于 unconfirmed 状态却要被路由到 fix，抛 CLAIM_NOT_REPRODUCED。

    任何试图把未复现的 claim 直接推进到修复流的代码路径都必须先调用本函数。
    """
    if isinstance(card_block, dict) and card_block.get("state") == "unconfirmed":
        raise CLAIM_NOT_REPRODUCED(
            f"CLAIM_NOT_REPRODUCED: card {card_block.get('id','?')} "
            f"(claim_id={card_block.get('claim_id','?')}) is still state=unconfirmed "
            f"— 未复现的 claim 不可被路由到 fix（R12-4, wave-level gate #2）"
        )
