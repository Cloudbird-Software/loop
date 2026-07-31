#!/usr/bin/env python3
"""conductor/claims.py — 断言的收发口与拒收规则（R12-1）。

依 .loop/schemas/claim.json 与 .loop/schemas/reproduction.json 实现校验。
校验器**不判断 claim 是否为真**，只判断它是否『有资格被检验』。
任何试图在此处引入真值判断的实现直接拒收。

铁律（与 loopd.py 的 _validate_finding 同风格：标准库逐字段校验，不依赖 jsonschema 运行时）：
- 缺 repro.cmd / repro.expected / falsifier / predicted_observation / severity / confidence 任一项即拒收
- 语义拒收：命中主观词表且无可执行 repro 的 claim 一律拒收
- claim id 强制 ^CL-\\d{3}$，同一评审轮内唯一
- confidence 越界（<0 或 >1）拒收；低于 policy.yml review.min_confidence 的 claim 丢弃（非拒收，是 budget drop）

CLI:
  python3 conductor/claims.py validate <file>   # 校验单个 claim 文件，退出码 0/1
  python3 conductor/claims.py ingest <file>     # 校验并登记（打印分配后的结构），退出码 0/1
"""
import json, os, re, sys, datetime

CLAIM_ID_RE = re.compile(r"^CL-[0-9]{3}$")
SUBJECTIVE_DEFAULT = [
    "优雅", "清晰", "更好", "建议重构", "最佳实践", "我觉得", "可能",
    "似乎", "应该", "感觉", "大概", "建议考虑", "不够优雅", "可读性差",
    "代码味道", "坏味道", "理想情况下", "理论上",
]
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_VERDICTS = {"REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE"}


def _load_policy():
    """加载 policy.yml（标准库，不依赖 PyYAML 运行时——但 policy.yml 已是项目依赖）。"""
    try:
        import yaml
        with open("policy.yml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_subjective_words(policy=None):
    """从 policy.yml review.subjective_words 读取主观词表，缺失时用内置默认。"""
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    words = review.get("subjective_words") if isinstance(review, dict) else None
    if isinstance(words, list) and words:
        return [w.lower() for w in words if isinstance(w, str)]
    return [w.lower() for w in SUBJECTIVE_DEFAULT]


def get_min_confidence(policy=None):
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    mc = review.get("min_confidence", 0.6) if isinstance(review, dict) else 0.6
    try:
        return float(mc)
    except (TypeError, ValueError):
        return 0.6


# ============================================================
# claim 校验
# ============================================================
def validate_claim_document(doc, policy=None):
    """校验一份完整的 claim 文档（对应 claim.json 顶层结构）。

    返回 (errors, warnings, valid_claims)。
    errors 非空 → 拒收整份文档。
    warnings → 某些 claim 被丢弃（如 confidence 过低）但不阻塞整批。
    """
    if not isinstance(doc, dict):
        return ["document must be a JSON object"], [], []

    errors = []
    warnings = []

    # 顶层必填字段
    top_required = ["schema", "review_id", "reviewer_model", "head_sha", "generated_at", "claims"]
    missing_top = [f for f in top_required if f not in doc]
    if missing_top:
        errors.append(f"MISSING_TOP_FIELDS: {missing_top}")
        return errors, warnings, []

    if doc.get("schema") != 1:
        errors.append(f"BAD_SCHEMA: expected 1, got {doc.get('schema')}")

    for f in ("review_id", "reviewer_model", "head_sha", "generated_at"):
        if not isinstance(doc.get(f), str) or not doc[f].strip():
            errors.append(f"EMPTY_FIELD: {f}")

    if len(doc.get("head_sha", "")) < 7:
        errors.append("SHORT_HEAD_SHA: head_sha must be >= 7 chars")

    claims = doc.get("claims")
    if not isinstance(claims, list) or len(claims) < 1:
        errors.append("NO_CLAIMS: claims array must have >=1 item")
        return errors, warnings, []

    min_conf = get_min_confidence(policy)
    seen_ids = set()
    valid_claims = []

    for i, claim in enumerate(claims):
        cerrs = validate_single_claim(claim, seen_ids, get_subjective_words(policy), min_conf)
        for e in cerrs:
            if e.startswith("LOW_CONFIDENCE:"):
                warnings.append(f"claim[{i}] {e}")
            else:
                errors.append(f"claim[{i}] ({claim.get('id', '?')}): {e}")
        if not cerrs:
            valid_claims.append(claim)

    return errors, warnings, valid_claims


def validate_single_claim(claim, seen_ids=None, subjective_words=None, min_conf=0.6):
    """校验单条 claim。返回 errors 列表（空=通过）。

    LOW_CONFIDENCE 前缀的 error 是 budget drop（丢弃但非拒收），
    validate_claim_document 会把它归入 warnings 而非 errors。
    """
    if seen_ids is None:
        seen_ids = set()
    if subjective_words is None:
        subjective_words = [w.lower() for w in SUBJECTIVE_DEFAULT]

    errs = []
    if not isinstance(claim, dict):
        return ["claim must be a JSON object"]

    required = ["id", "claim", "severity", "confidence", "repro", "predicted_observation", "falsifier"]
    missing = [f for f in required if f not in claim]
    if missing:
        errs.append(f"MISSING_FIELDS: {missing}")
        return errs

    # id 格式 + 唯一性
    cid = claim.get("id", "")
    if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
        errs.append(f"BAD_ID: '{cid}' does not match ^CL-[0-9]{{3}}$")
    elif cid in seen_ids:
        errs.append(f"DUPLICATE_ID: {cid}")
    else:
        seen_ids.add(cid)

    # claim 文本非空
    if not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
        errs.append("EMPTY_FIELD: claim")

    # severity
    if claim.get("severity") not in VALID_SEVERITIES:
        errs.append(f"BAD_SEVERITY: {claim.get('severity')} (must be one of {sorted(VALID_SEVERITIES)})")

    # confidence
    conf = claim.get("confidence")
    if not isinstance(conf, (int, float)):
        errs.append(f"BAD_CONFIDENCE: not a number ({conf})")
    else:
        if conf < 0 or conf > 1:
            errs.append(f"CONFIDENCE_OUT_OF_RANGE: {conf} (must be 0..1)")
        elif conf < min_conf:
            errs.append(f"LOW_CONFIDENCE: {conf} < min_confidence({min_conf}) — claim dropped (not rejected)")

    # 语义拒收：主观措辞
    claim_text = str(claim.get("claim", "")).lower()
    hit_words = [w for w in subjective_words if w in claim_text]
    if hit_words:
        repro = claim.get("repro", {})
        has_executable_cmd = isinstance(repro, dict) and isinstance(repro.get("cmd"), str) and repro["cmd"].strip()
        if not has_executable_cmd:
            errs.append(f"SUBJECTIVE_WORD_WITHOUT_REPRO: hit {hit_words} but no executable repro.cmd")

    # repro 结构
    repro = claim.get("repro")
    if not isinstance(repro, dict):
        errs.append("BAD_REPRO: repro must be an object")
    else:
        repro_required = ["cmd", "expected", "actual", "env"]
        repro_missing = [f for f in repro_required if f not in repro]
        if repro_missing:
            errs.append(f"MISSING_REPRO_FIELDS: {repro_missing}")
        else:
            for f in repro_required:
                if not isinstance(repro.get(f), str) or not repro[f].strip():
                    errs.append(f"EMPTY_REPRO_FIELD: {f}")

    # predicted_observation 非空
    if not isinstance(claim.get("predicted_observation"), str) or not claim["predicted_observation"].strip():
        errs.append("EMPTY_FIELD: predicted_observation")

    # falsifier 非空
    if not isinstance(claim.get("falsifier"), str) or not claim["falsifier"].strip():
        errs.append("EMPTY_FIELD: falsifier")

    return errs


def next_id(existing_ids):
    """分配下一个可用的 CL-NNN id。existing_ids 是已占用的 id 集合。"""
    n = 1
    while True:
        cid = f"CL-{n:03d}"
        if cid not in existing_ids:
            return cid
        n += 1


# ============================================================
# reproduction 校验
# ============================================================
def validate_reproduction(rep, reviewer_model=None, policy=None):
    """校验一条 reproduction 记录（对应 reproduction.json）。

    reviewer_model: 若提供，校验 reproducer_model != reviewer_model（异构强制）。
    返回 errors 列表（空=通过）。
    """
    errs = []
    if not isinstance(rep, dict):
        return ["reproduction must be a JSON object"]

    required = ["schema", "claim_id", "review_id", "verdict", "reproducer_model", "observed", "env", "generated_at"]
    missing = [f for f in required if f not in rep]
    if missing:
        errs.append(f"MISSING_FIELDS: {missing}")
        return errs

    if rep.get("schema") != 1:
        errs.append(f"BAD_SCHEMA: expected 1, got {rep.get('schema')}")

    if not CLAIM_ID_RE.match(str(rep.get("claim_id", ""))):
        errs.append(f"BAD_CLAIM_ID: {rep.get('claim_id')}")

    if rep.get("verdict") not in VALID_VERDICTS:
        errs.append(f"BAD_VERDICT: {rep.get('verdict')} (must be one of {sorted(VALID_VERDICTS)})")

    rm = rep.get("reproducer_model")
    if not isinstance(rm, str) or not rm.strip():
        errs.append("EMPTY_FIELD: reproducer_model")
    elif reviewer_model and rm == reviewer_model:
        errs.append(f"SELF_ADJUDICATION: reproducer_model({rm}) == reviewer_model({reviewer_model}) — 异构强制 violated")

    observed = rep.get("observed")
    if not isinstance(observed, dict):
        errs.append("BAD_OBSERVED: observed must be an object")
    else:
        obs_required = ["cmd", "exit_code", "stdout_excerpt"]
        obs_missing = [f for f in obs_required if f not in observed]
        if obs_missing:
            errs.append(f"MISSING_OBSERVED_FIELDS: {obs_missing}")
        else:
            if not isinstance(observed.get("cmd"), str) or not observed["cmd"].strip():
                errs.append("EMPTY_OBSERVED: cmd")
            if not isinstance(observed.get("exit_code"), int):
                errs.append(f"BAD_EXIT_CODE: {observed.get('exit_code')} must be integer")
            if not isinstance(observed.get("stdout_excerpt"), str):
                errs.append("BAD_STDOUT_EXCERPT: must be string")

    # diff_note 在非 REPRODUCED 时必填
    verdict = rep.get("verdict")
    if verdict in ("NOT_REPRODUCED", "INCONCLUSIVE"):
        dn = rep.get("diff_note")
        if not isinstance(dn, str) or not dn.strip():
            errs.append(f"MISSING_DIFF_NOTE: verdict={verdict} requires non-empty diff_note")

    # next_action 由 conductor 填写，沙盒模型不自行决定
    na = rep.get("next_action")
    if na is not None:
        valid_na = {"open_fix_card", "await_arbitration", "escalate_env_diff", "close_refuted"}
        if na not in valid_na:
            errs.append(f"BAD_NEXT_ACTION: {na} (must be one of {sorted(valid_na)})")

    return errs


# ============================================================
# CLI
# ============================================================
def _cmd_validate(path):
    if not os.path.exists(path):
        print(f"FILE_NOT_FOUND: {path}")
        return 1
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON_PARSE_ERROR: {e}")
        return 1
    errors, warnings, valid = validate_claim_document(doc)
    if errors:
        print("REJECTED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    if warnings:
        print("ACCEPTED (with budget drops):")
        for w in warnings:
            print(f"  - {w}")
    print(f"OK: {len(valid)} valid claim(s)")
    return 0


def _cmd_ingest(path):
    if not os.path.exists(path):
        print(f"FILE_NOT_FOUND: {path}")
        return 1
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON_PARSE_ERROR: {e}")
        return 1
    errors, warnings, valid = validate_claim_document(doc)
    if errors:
        print("REJECTED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    # ingest: 分配/确认 id，打印结构化结果
    result = {
        "review_id": doc.get("review_id"),
        "reviewer_model": doc.get("reviewer_model"),
        "head_sha": doc.get("head_sha"),
        "ingested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "accepted_claims": len(valid),
        "dropped_claims": len(warnings),
        "claim_ids": [c.get("id") for c in valid],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    if len(sys.argv) < 3:
        print("usage: conductor/claims.py <validate|ingest> <file>")
        return 2
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == "validate":
        return _cmd_validate(path)
    elif cmd == "ingest":
        return _cmd_ingest(path)
    else:
        print(f"UNKNOWN_COMMAND: {cmd} (expected validate|ingest)")
        return 2


if __name__ == "__main__":
    sys.exit(main())
