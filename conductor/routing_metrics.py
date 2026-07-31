#!/usr/bin/env python3
"""conductor/routing_metrics.py — 路由级 claim 精度聚合与降权（R12-7）。

把强模型验收环（review）产出的 claim/reproduction 汇总成「每条 route 的精度指标」，
回填进 ROUTING.yaml 的 metrics 段，并据此判定是否降权某个 reviewer_model。

铁律（与 conductor/claims.py、conductor/reproduce.py 同源）：
- claim 精度按 reviewer_model 聚合（.loop/schemas/claim.json 规定 reviewer_model
  是接缝 A 解析后的真实模型名，记分按此字段聚合，回填 ROUTING.yaml 对应 route）。
- 复现三态 REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE；只有 REPRODUCED 计入
  claims_reproduced，NOT_REPRODUCED 计入 claims_refuted，INCONCLUSIVE 两者都不计。
- 降权决策受 policy.yml review.precision_floor / review.min_samples_for_demotion 约束：
  样本不足 → 打印 INSUFFICIENT_SAMPLES 不降权；精度低于 floor → 返回降权建议。
- 回填 ROUTING.yaml 必须幂等且保留注释/顺序（ruamel 不可用，故用文本外科手术）。

外部入口：
  aggregate_metrics(claims, reproductions)   — 聚合，返回 {route_key: metrics}
  backfill_routing_metrics(metrics, path)    — 幂等回填 ROUTING.yaml 的 metrics 段
  compute_demotion(route_metrics, policy)    — 判定是否降权
  apply_demotion(demotion, path)             — 落地降权（加 status: demoted + 警告）
  add_experiment_field(idx, experiment, p)   — 给 route 加 experiment 字段（A/B）
  replay_from_evidence(evidence_dir)         — 从证据目录重放，幂等
"""
import json
import os

ROUTING_PATH = os.environ.get("ROUTING_PATH", "ROUTING.yaml")
POLICY_PATH = os.environ.get("POLICY_PATH", "policy.yml")

DEFAULT_PRECISION_FLOOR = 0.5
DEFAULT_MIN_SAMPLES_FOR_DEMOTION = 10


# ============================================================
# YAML / JSON 装载（标准库 + 可选 PyYAML，与 reproduce.py 同风格）
# ============================================================
def _load_yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_routing(path=None):
    return _load_yaml(path or ROUTING_PATH)


def _load_policy(path=None):
    return _load_yaml(path or POLICY_PATH)


def _load_json_records(path):
    """装载一个 JSON 文件；可以是单个对象或对象数组。返回 dict 列表。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _normalize_input(obj):
    """接受 路径(str) / 路径列表 / dict列表 / 单个dict，返回 dict 列表。"""
    if obj is None:
        return []
    if isinstance(obj, str):
        return _load_json_records(obj)
    if isinstance(obj, dict):
        return [obj]
    if isinstance(obj, (list, tuple)):
        out = []
        for item in obj:
            if isinstance(item, str):
                out.extend(_load_json_records(item))
            elif isinstance(item, dict):
                out.append(item)
        return out
    return []


# ============================================================
# 路由解析：reviewer_model → (domain, action, provider)
# ============================================================
def _resolve_route_for_model(model, routing=None):
    """按 reviewer_model 在 ROUTING.yaml 里找其所属 route，返回 (domain, action, provider)。

    claim 由 review/accept 路由的模型产出，故优先匹配 domain=review/action=accept；
    找不到时回落 (review, accept, unknown)。
    """
    if routing is None:
        routing = _load_routing()
    routes = routing.get("routes", []) if isinstance(routing, dict) else []
    candidates = [r for r in routes if isinstance(r, dict) and r.get("model") == model]
    if candidates:
        for r in candidates:
            if r.get("domain") == "review" and r.get("action") == "accept":
                return (r.get("domain", "review"),
                        r.get("action", "accept"),
                        r.get("provider", "unknown"))
        r = candidates[0]
        return (r.get("domain", "review"),
                r.get("action", "accept"),
                r.get("provider", "unknown"))
    return "review", "accept", "unknown"


def _route_key(domain, action, provider, model):
    return f"{domain}/{action}/{provider}/{model}"


# ============================================================
# aggregate_metrics
# ============================================================
def aggregate_metrics(claims, reproductions):
    """按 (domain, action, provider, model) 聚合 claim 精度。

    claims: 路径 / 路径列表 / claim 文档列表（每个含 reviewer_model + claims[]）。
    reproductions: 路径 / 路径列表 / reproduction 记录列表（每个含 claim_id + verdict）。

    返回 dict，键为 "domain/action/provider/model"，值为：
      {claims_total, claims_reproduced, claims_refuted, precision, cost,
       domain, action, provider, model, route_key}
    （附带 domain/action/provider/model/route_key 元数据，供 compute_demotion 使用）
    """
    claim_docs = _normalize_input(claims)
    repro_records = _normalize_input(reproductions)
    routing = _load_routing()

    # claim_id -> verdict（同一 claim 多次复现时取最后一次，通常唯一）
    verdict_map = {}
    for rep in repro_records:
        cid = rep.get("claim_id")
        verdict = rep.get("verdict")
        if cid and verdict:
            verdict_map[cid] = verdict

    metrics = {}
    for doc in claim_docs:
        reviewer_model = doc.get("reviewer_model", "unknown")
        # 允许 claim 文档显式声明路由归属（前向兼容），否则从 ROUTING.yaml 解析
        domain = doc.get("route_domain")
        action = doc.get("route_action")
        provider = doc.get("route_provider")
        if not (domain and action and provider):
            d, a, p = _resolve_route_for_model(reviewer_model, routing)
            domain = domain or d
            action = action or a
            provider = provider or p
        key = _route_key(domain, action, provider, reviewer_model)
        entry = metrics.setdefault(key, {
            "domain": domain, "action": action,
            "provider": provider, "model": reviewer_model,
            "route_key": key,
            "claims_total": 0,
            "claims_reproduced": 0,
            "claims_refuted": 0,
            "precision": 0.0,
            "cost": 0,
        })
        claims_list = doc.get("claims", []) or []
        for claim in claims_list:
            if not isinstance(claim, dict):
                continue
            entry["claims_total"] += 1
            cid = claim.get("id")
            verdict = verdict_map.get(cid) if cid else None
            if verdict == "REPRODUCED":
                entry["claims_reproduced"] += 1
            elif verdict == "NOT_REPRODUCED":
                entry["claims_refuted"] += 1

    for entry in metrics.values():
        total = entry["claims_total"]
        entry["precision"] = (entry["claims_reproduced"] / total) if total else 0.0
        entry["cost"] = 0  # 占位，R14-3 填真实成本

    return metrics


# ============================================================
# ROUTING.yaml 文本外科手术（ruamel 不可用，手写保注释/顺序/幂等）
# ============================================================
def _parse_field(kv_str, cur):
    """把 'key: value' 串解析进 cur dict；处理引号与空值。"""
    if ":" not in kv_str:
        return
    k, v = kv_str.split(":", 1)
    k = k.strip()
    v = v.strip()
    if v == "" or v.startswith("#"):
        cur[k] = None
        return
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    cur[k] = v


def _fmt_precision(p):
    """格式化 precision：去尾零但保留 'X.0' 形式，幂等。"""
    s = f"{float(p):.4f}".rstrip("0")
    if s.endswith("."):
        s += "0"
    return s


def _format_metrics_block(entry):
    """生成 route 的 metrics 块（5 行，4/6 空格缩进）。cost 暂不入文件（R14-3）。"""
    if entry is None:
        total, reproduced, refuted, precision = 0, 0, 0, 0.0
    else:
        total = int(entry.get("claims_total", 0) or 0)
        reproduced = int(entry.get("claims_reproduced", 0) or 0)
        refuted = int(entry.get("claims_refuted", 0) or 0)
        precision = float(entry.get("precision", 0.0) or 0.0)
    return (
        "    metrics:\n"
        f"      claims_total: {total}\n"
        f"      claims_reproduced: {reproduced}\n"
        f"      claims_refuted: {refuted}\n"
        f"      precision: {_fmt_precision(precision)}"
    )


def backfill_routing_metrics(metrics_dict, routing_path="ROUTING.yaml"):
    """把聚合指标幂等回填进 ROUTING.yaml 各 route 的 metrics 段。

    幂等：对同一 metrics_dict 跑两次，产物文件逐字相同。
    保留全部注释/顺序/结构：只改写「匹配 route」的 metrics 段；未匹配的 route
    其既有 metrics 原样保留（不抹零、不丢数据）。
    """
    with open(routing_path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    out = []
    cur = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # route 起始：'  - field: ...'
        if line.startswith("  - "):
            cur = {}
            _parse_field(line[4:], cur)
            out.append(line)
            i += 1
            continue
        # route 内 4 空格字段：'    key: value'
        if line.startswith("    ") and not line.startswith("     ") and ":" in line:
            _parse_field(line[4:], cur)
            key_part = line[4:].split(":", 1)[0].strip()
            if key_part == "metrics":
                key = _route_key(
                    cur.get("domain", ""),
                    cur.get("action", ""),
                    cur.get("provider", ""),
                    cur.get("model", ""),
                )
                if metrics_dict and key in metrics_dict:
                    # 吞掉旧的 metrics 子块（6+ 空格缩进的后续行），写新块
                    j = i + 1
                    while j < n and lines[j].startswith("      "):
                        j += 1
                    out.append(_format_metrics_block(metrics_dict[key]))
                    i = j
                    continue
                # 未匹配 → 保留既有 metrics（含其子块），原样透传
            out.append(line)
            i += 1
            continue
        # 其余行（注释/空行/providers 段/default 段/6+ 缩进子块）原样透传
        out.append(line)
        i += 1

    new_text = "\n".join(out)
    if new_text != text:
        with open(routing_path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return routing_path


# ============================================================
# compute_demotion / apply_demotion
# ============================================================
def compute_demotion(route_metrics, policy=None):
    """判定 review 域某模型是否应降权。

    - claims_total < policy.review.min_samples_for_demotion（默认 10）：
      打印 INSUFFICIENT_SAMPLES，返回 None（不降权）。
    - precision < policy.review.precision_floor（默认 0.5）：
      返回降权建议 dict。
    - 否则返回 None。
    """
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    if not isinstance(review, dict):
        review = {}
    min_samples = review.get("min_samples_for_demotion", DEFAULT_MIN_SAMPLES_FOR_DEMOTION)
    try:
        min_samples = int(min_samples)
    except (TypeError, ValueError):
        min_samples = DEFAULT_MIN_SAMPLES_FOR_DEMOTION
    floor = review.get("precision_floor", DEFAULT_PRECISION_FLOOR)
    try:
        floor = float(floor)
    except (TypeError, ValueError):
        floor = DEFAULT_PRECISION_FLOOR

    if not isinstance(route_metrics, dict):
        return None

    total = int(route_metrics.get("claims_total", 0) or 0)
    if total < min_samples:
        print("INSUFFICIENT_SAMPLES")
        return None

    precision = float(route_metrics.get("precision", 0.0) or 0.0)
    if precision < floor:
        provider = route_metrics.get("provider", "unknown")
        model = route_metrics.get("model", "unknown")
        current_route = route_metrics.get("route_key") or _route_key(
            route_metrics.get("domain", "review"),
            route_metrics.get("action", "accept"),
            provider, model,
        )
        return {
            "provider": provider,
            "model": model,
            "current_route": current_route,
            "reason": f"precision {precision} < floor {floor} ({total} samples)",
            "suggested_action": "demote",
        }
    return None


def apply_demotion(demotion, routing_path="ROUTING.yaml"):
    """落地降权：给匹配 route 加 status: demoted 并打印警告（Incident 暂为桩）。

    若 demotion 为 None，直接返回。幂等：重复调用不会重复加 status: demoted，
    也不会改写 route 已有的其它 status 值以外的结构。保留注释/顺序。
    """
    if demotion is None:
        return None
    target_provider = demotion.get("provider")
    target_model = demotion.get("model")
    print(
        f"WARNING: demoting model {target_model} (provider={target_provider}) "
        f"route={demotion.get('current_route', '')} "
        f"reason={demotion.get('reason', '')}; opening Incident "
        f"(stub: status:demoted recorded in {routing_path})"
    )

    with open(routing_path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    out = []
    cur = {}
    in_routes = False

    def _matches():
        return (cur.get("domain") == "review"
                and cur.get("provider") == target_provider
                and cur.get("model") == target_model)

    def _needs_status():
        return in_routes and _matches() and cur.get("status") != "demoted"

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # 4+ 空格缩进 → route 内容（4 空格字段或更深的子块），原样保留并解析 4 空格字段
        if line.startswith("    "):
            if in_routes and not line.startswith("     ") and ":" in line:
                _parse_field(line[4:], cur)
            out.append(line)
            i += 1
            continue
        # 非 4 空格行：可能正离开当前 route 内容 → 先补 status（若需要）
        if _needs_status():
            out.append("    status: demoted")
            cur["status"] = "demoted"
        if line.rstrip() == "routes:":
            in_routes = True
            cur = {}
        elif line.startswith("  - "):
            cur = {}
            _parse_field(line[4:], cur)
        elif line and not line.startswith(" ") and not line.startswith("#"):
            in_routes = False
            cur = {}
        out.append(line)
        i += 1

    # EOF：若仍停在匹配 route 内
    if _needs_status():
        out.append("    status: demoted")
        cur["status"] = "demoted"

    new_text = "\n".join(out)
    if new_text != text:
        with open(routing_path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return demotion


# ============================================================
# add_experiment_field：A/B 实验字段（不改调度骨架）
# ============================================================
def add_experiment_field(route_index, experiment, routing_path="ROUTING.yaml"):
    """给第 route_index 条 route 加 experiment: {name, variant, traffic_share} 字段。

    用于在不改动调度骨架的前提下对新方法做 A/B。route_index 为 routes 列表的 0 基索引。
    幂等：若该 route 已有 experiment 字段则不重复添加。保留注释/顺序。
    """
    if not isinstance(experiment, dict):
        raise TypeError("experiment must be a dict")
    with open(routing_path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    out = []
    in_routes = False
    cur_idx = -1
    flushed = False
    cur = {}

    def _exp_line():
        parts = []
        for k in ("name", "variant", "traffic_share"):
            v = experiment.get(k)
            if v is not None and v != "":
                parts.append(f"{k}: {v}")
        return "    experiment: {" + ", ".join(parts) + "}"

    def _needs_flush():
        return (in_routes and cur_idx == route_index and not flushed
                and cur.get("experiment") is None)

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("    "):
            if in_routes and not line.startswith("     ") and ":" in line:
                _parse_field(line[4:], cur)
            out.append(line)
            i += 1
            continue
        if _needs_flush():
            out.append(_exp_line())
            flushed = True
        if line.rstrip() == "routes:":
            in_routes = True
            cur = {}
        elif line.startswith("  - "):
            cur = {}
            _parse_field(line[4:], cur)
            cur_idx += 1
            flushed = False
        elif line and not line.startswith(" ") and not line.startswith("#"):
            in_routes = False
            cur = {}
        out.append(line)
        i += 1

    if _needs_flush():
        out.append(_exp_line())
        flushed = True

    new_text = "\n".join(out)
    if new_text != text:
        with open(routing_path, "w", encoding="utf-8") as f:
            f.write(new_text)
    return routing_path


# ============================================================
# replay_from_evidence：从证据目录幂等重放
# ============================================================
def replay_from_evidence(evidence_dir):
    """读取 evidence_dir 下全部 claim/reproduction JSON，重算指标。

    幂等：不写任何文件；按排序后的文件名读取，两次重放得到完全相同的数字。
    文件按内容归类：含 claims+reviewer_model → claim 文档；含 claim_id+verdict → reproduction。
    """
    claims = []
    reproductions = []
    if not os.path.isdir(evidence_dir):
        return {}
    files = sorted(os.listdir(evidence_dir))
    for name in files:
        path = os.path.join(evidence_dir, name)
        if not os.path.isfile(path):
            continue
        if not name.endswith(".json"):
            continue
        records = _load_json_records(path)
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if "claims" in rec and "reviewer_model" in rec:
                claims.append(rec)
            elif "claim_id" in rec and "verdict" in rec:
                reproductions.append(rec)
    return aggregate_metrics(claims, reproductions)
