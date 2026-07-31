#!/usr/bin/env python3
"""bench/metrics.py — 四指标采集与对比（升级环第 8 环判定核心）。

四指标（OPC-v4 第 8 周起）：
  first_ci_pass_rate   N 张卡首次 CI 通过的比例
  reopen_count         N 张卡 reopen 次数总和
  avg_diff_lines       N 张卡平均 diff 行数
  single_card_cost_yuan 单卡平均成本（元）

用法：
  # 采集基线（读 replay/*.json 的 baseline_metrics 聚合）
  python bench/metrics.py baseline --replay-dir bench/replay --out bench/baseline.json

  # 对比（after 由调用方通过 --after-json 传入，或 --after-stdin 读 JSON）
  python bench/metrics.py compare --baseline bench/baseline.json --after-json after.json
  退出码：0=不劣化  1=劣化（任一指标超阈值）

  # 聚合 N 张卡的重放结果行（replay.sh 输出）为四指标
  python bench/metrics.py aggregate --results <file>   # 每行: R-NNN PASS|FAIL diff reopen cost
"""
import argparse, json, os, sys, pathlib, datetime

def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# 劣化阈值（默认；与 bench/README.md 一致）
DEFAULT_THRESHOLDS = {
    "first_ci_pass_rate_drop": 0.05,   # after < before - 0.05 → REGRESSED
    "reopen_count_increase": 1,        # after > before + 1   → REGRESSED
    "avg_diff_lines_increase_ratio": 0.20,  # after > before * 1.20 → REGRESSED
    "single_card_cost_increase_ratio": 0.30, # after > before * 1.30 → REGRESSED
}

METRIC_KEYS = ["first_ci_pass_rate", "reopen_count", "avg_diff_lines", "single_card_cost_yuan"]

# ── CHARTER Q 指标阈值（与 CHARTER.md 的 G0~G5 定量指标逐条对应）──
# direction: "ge" = 值 ≥ target 才达标；"le" = 值 ≤ target 才达标。
# 这张表是 check_q_thresholds 的默认基准，也是 upgrade_ring 判定是否开 Incident 的依据。
CHARTER_Q_TARGETS = {
    "Q0": {"target": 0.8,   "direction": "ge", "unit": "closure_rate",
           "desc": "Q0 闭环成功率 ≥80%（CHARTER Q0.3）"},
    "Q1": {"target": 1800,  "direction": "le", "unit": "seconds",
           "desc": "Q1 僵尸回收延迟 ≤30 分钟（CHARTER Q1.1）"},
    "Q2": {"target": 5,     "direction": "le", "unit": "points",
           "desc": "Q2 fork 后改动点 ≤5（CHARTER Q2.1）"},
    "Q3": {"target": 0,     "direction": "le", "unit": "count",
           "desc": "Q3 假绿数 = 0（CHARTER Q3.1）"},
    "Q4": {"target": 1.0,   "direction": "ge", "unit": "ratio",
           "desc": "Q4 进入修复的 claim 100% 有 REPRODUCED（CHARTER Q4.1）"},
    "Q5": {"target": 1.0,   "direction": "ge", "unit": "composite",
           "desc": "Q5 产品仓对齐 + 依赖升级成功率（CHARTER Q5.1~Q5.3）"},
}


def load_replay_cards(replay_dir):
    cards = []
    d = pathlib.Path(replay_dir)
    if not d.exists():
        return cards
    for f in sorted(d.glob("R-*.json")):
        try:
            cards.append(json.loads(f.read_text()))
        except json.JSONDecodeError as e:
            print(f"WARN: skip {f}: {e}", file=sys.stderr)
    return cards


def aggregate_baseline(cards):
    """从 replay 卡的 baseline_metrics 聚合四指标。"""
    n = len(cards)
    if n == 0:
        return {k: 0.0 for k in METRIC_KEYS}, 0
    pass_count = sum(1 for c in cards if c.get("baseline_metrics", {}).get("first_ci_pass", False))
    reopen_sum = sum(c.get("baseline_metrics", {}).get("reopen_count", 0) for c in cards)
    diff_sum = sum(c.get("baseline_metrics", {}).get("diff_lines", 0) for c in cards)
    cost_sum = sum(c.get("baseline_metrics", {}).get("cost_yuan", 0.0) for c in cards)
    metrics = {
        "first_ci_pass_rate": round(pass_count / n, 4),
        "reopen_count": reopen_sum,
        "avg_diff_lines": round(diff_sum / n, 2),
        "single_card_cost_yuan": round(cost_sum / n, 4),
    }
    return metrics, n


def aggregate_results_lines(lines):
    """把 replay.sh 的结果行聚合成四指标。
    每行格式: R-NNN <PASS|FAIL> <diff_lines> <reopen> <cost_yuan>
    """
    n = 0; pass_count = 0; reopen = 0; diff = 0; cost = 0.0
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or not ln.startswith("R-"):
            continue
        parts = ln.split()
        if len(parts) < 5:
            continue
        n += 1
        if parts[1].upper() == "PASS":
            pass_count += 1
        diff += int(parts[2])
        reopen += int(parts[3])
        cost += float(parts[4])
    if n == 0:
        return {k: 0.0 for k in METRIC_KEYS}, 0
    return {
        "first_ci_pass_rate": round(pass_count / n, 4),
        "reopen_count": reopen,
        "avg_diff_lines": round(diff / n, 2),
        "single_card_cost_yuan": round(cost / n, 4),
    }, n


def compare(before, after, thresholds=None):
    """返回 (regressed_metrics_list, details_dict)。
    regressed_metrics_list 为空表示不劣化。
    """
    t = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        t.update(thresholds)
    regressed = []
    details = {}

    b = before.get("first_ci_pass_rate", 0.0); a = after.get("first_ci_pass_rate", 0.0)
    delta = round(a - b, 4)
    ok = a >= b - t["first_ci_pass_rate_drop"]
    details["first_ci_pass_rate"] = {"before": b, "after": a, "delta": delta, "ok": ok}
    if not ok:
        regressed.append(("first_ci_pass_rate", delta))

    b = before.get("reopen_count", 0); a = after.get("reopen_count", 0)
    delta = a - b
    ok = a <= b + t["reopen_count_increase"]
    details["reopen_count"] = {"before": b, "after": a, "delta": delta, "ok": ok}
    if not ok:
        regressed.append(("reopen_count", delta))

    b = before.get("avg_diff_lines", 0.0); a = after.get("avg_diff_lines", 0.0)
    delta = round(a - b, 2)
    ok = (b == 0 and a == 0) or a <= b * (1 + t["avg_diff_lines_increase_ratio"])
    details["avg_diff_lines"] = {"before": b, "after": a, "delta": delta, "ok": ok}
    if not ok:
        regressed.append(("avg_diff_lines", delta))

    b = before.get("single_card_cost_yuan", 0.0); a = after.get("single_card_cost_yuan", 0.0)
    delta = round(a - b, 4)
    ok = (b == 0 and a == 0) or a <= b * (1 + t["single_card_cost_increase_ratio"])
    details["single_card_cost_yuan"] = {"before": b, "after": a, "delta": delta, "ok": ok}
    if not ok:
        regressed.append(("single_card_cost_yuan", delta))

    return regressed, details


def render_table(details, before_n=None, after_n=None):
    rows = []
    rows.append("| metric | before | after | delta | ok |")
    rows.append("|---|---|---|---|---|")
    for k in METRIC_KEYS:
        d = details[k]
        rows.append(f"| {k} | {d['before']} | {d['after']} | {d['delta']} | {'yes' if d['ok'] else 'NO'} |")
    if before_n is not None and after_n is not None:
        rows.append(f"| replayed_cards | {before_n} | {after_n} | - | - |")
    return "\n".join(rows)


# ============================================================
# CHARTER Q 指标（R14-3）：从 evidence 计算 Q0~Q5，可回放、可横向比较、可写看板
# ============================================================
def _meets(value, target, direction):
    """判定 value 是否达标。None/非数 → 视为不达标（fail-safe，不静默放行）。"""
    if value is None or target is None:
        return False
    try:
        v = float(value)
        t = float(target)
    except (TypeError, ValueError):
        return False
    if direction == "le":
        return v <= t
    if direction == "eq":
        return v == t
    return v >= t  # 默认 ge


def _q_entry(value, target, direction, unit="", desc="", note="", sub=None):
    """构造单个 Q 指标条目：value/target/status + 子指标。"""
    return {
        "value": value,
        "target": target,
        "direction": direction,
        "status": "pass" if _meets(value, target, direction) else "fail",
        "unit": unit,
        "desc": desc,
        "note": note,
        "sub": sub or {},
    }


def _as_record_list(data):
    """JSON 解析结果归一为 dict 列表（单 dict 包成单元素列表）。"""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _load_all_records(evidence_dir):
    """递归读取 evidence_dir 下全部 .json（按路径排序），返回 dict 记录列表。
    纯函数：只读文件、不读时间/网络；按路径排序 → 同一份 evidence 任意时刻重算得相同结果。"""
    root = pathlib.Path(evidence_dir)
    if not root.exists():
        return []
    out = []
    for f in sorted(root.rglob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.extend(_as_record_list(data))
    return out


def _collect_num(records, key):
    """从全部记录里收集某字段的数值（bool 不当数字，避免 True 被当 1）。"""
    out = []
    for r in records:
        if not isinstance(r, dict):
            continue
        v = r.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.append(v)
    return out


def _median(values):
    """中位数；空列表返回 0。"""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2:
        return round(s[n // 2], 4)
    return round((s[n // 2 - 1] + s[n // 2]) / 2, 4)


def _max_or_zero(values):
    return max(values) if values else 0


def _is_rejected_claim(claim):
    """claim 缺 repro 或缺 falsifier → 拒收（CHARTER N9.3）。"""
    repro = claim.get("repro")
    falsifier = claim.get("falsifier")
    return not (isinstance(repro, dict) and repro.get("cmd") and falsifier)


def compute_q_metrics(evidence_dir="."):
    """从 evidence 目录计算 CHARTER 全部 Q 指标（Q0~Q5）。

    纯函数：只读 evidence_dir 下的 JSON，不读网络、不读时间。同一份 evidence 任意
    时刻重算得到相同数字（可回放）。evidence 缺失返回默认/零值，不抛异常。

    evidence 按内容自动归类（无需固定目录结构）：
      - baseline_metrics            → Q0 闭环成功率与领卡时延（replay 卡）
      - continue_to_claim_seconds /
        claim_to_done_seconds /
        closure_success             → Q0 子指标
      - recycle_delay_seconds /
        zombie.delay                → Q1 自治自愈时延
      - dependency_release_ticks    → Q1 依赖放行延迟
      - fork_points                 → Q2 样板可复用性
      - fake_green_count /
        negative_test_coverage /
        settings_roundtrip_ok       → Q3 可信度地基
      - claims + reviewer_model     → Q4 claim 文档
      - claim_id + verdict          → Q4 复现记录（REPRODUCED/NOT_REPRODUCED/INCONCLUSIVE）
      - solidified_checkers         → Q4 固化为 checker 的累计数
      - upgrade_ok / bump_result /
        (pkg + regressed)           → Q5 依赖升级成功率
      - pin_lag_tags / pin_lag_days → Q5 pin 新鲜度
      - mechanism_copy_count /
        template_sync_exemptions    → Q5 机制副本数 / 豁免数

    返回 {Q0: {...}, Q1: {...}, ..., Q5: {...}}，每个含
    value/target/direction/status/unit/desc/note/sub。
    """
    records = _load_all_records(evidence_dir)

    # ── Q0：闭环成功率与领卡时延 ──
    replay_cards = [r for r in records if isinstance(r.get("baseline_metrics"), dict)]
    n0 = len(replay_cards)
    pass_count = sum(1 for c in replay_cards
                     if c["baseline_metrics"].get("first_ci_pass"))
    replay_pass_rate = round(pass_count / n0, 4) if n0 else 0.0
    continue_secs = _collect_num(records, "continue_to_claim_seconds")
    done_secs = _collect_num(records, "claim_to_done_seconds")
    closure_flags = [r.get("closure_success") for r in records
                     if r.get("closure_success") is not None]
    if closure_flags:
        closure_rate = round(sum(1 for f in closure_flags if f) / len(closure_flags), 4)
    else:
        closure_rate = replay_pass_rate
    q0_1 = _q_entry(_median(continue_secs), 60, "le", "seconds", "Q0.1 从继续到领卡 ≤1 分钟")
    q0_2 = _q_entry(_median(done_secs), 1800, "le", "seconds", "Q0.2 从领卡到 done ≤30 分钟")
    q0_3 = _q_entry(closure_rate, 0.8, "ge", "closure_rate", "Q0.3 闭环成功率 ≥80%")
    Q0 = _q_entry(q0_3["value"], 0.8, "ge", "closure_rate", "Q0 闭环成功率与领卡时延",
                  note=("no replay evidence" if not n0 and not closure_flags else ""),
                  sub={"Q0.1": q0_1, "Q0.2": q0_2, "Q0.3": q0_3})

    # ── Q1：自治自愈时延 ──
    zombie_delays = _collect_num(records, "recycle_delay_seconds")
    zombie_delays += [r["zombie"]["delay"] for r in records
                      if isinstance(r.get("zombie"), dict)
                      and isinstance(r["zombie"].get("delay"), (int, float))
                      and not isinstance(r["zombie"].get("delay"), bool)]
    dep_ticks = _collect_num(records, "dependency_release_ticks")
    q1_1 = _q_entry(_max_or_zero(zombie_delays), 1800, "le", "seconds", "Q1.1 僵尸回收延迟 ≤30 分钟")
    q1_2 = _q_entry(_max_or_zero(dep_ticks), 1, "le", "ticks", "Q1.2 依赖放行延迟 ≤1 轮 tick")
    Q1 = _q_entry(q1_1["value"], 1800, "le", "seconds", "Q1 自治自愈时延",
                  note=("no zombie evidence" if not zombie_delays else ""),
                  sub={"Q1.1": q1_1, "Q1.2": q1_2})

    # ── Q2：样板可复用性 ──
    fork_points = _collect_num(records, "fork_points")
    q2_1 = _q_entry(fork_points[0] if fork_points else 0, 5, "le", "points",
                    "Q2.1 fork 后改动点 ≤5")
    Q2 = _q_entry(q2_1["value"], 5, "le", "points", "Q2 样板可复用性",
                  note=("no fork audit" if not fork_points else ""),
                  sub={"Q2.1": q2_1})

    # ── Q3：可信度地基（假绿为零 + 门禁负向测试）──
    fake_green = sum(_collect_num(records, "fake_green_count"))
    neg_cov_vals = _collect_num(records, "negative_test_coverage")
    neg_cov = neg_cov_vals[-1] if neg_cov_vals else 0.0
    settings_vals = [r.get("settings_roundtrip_ok") for r in records
                     if r.get("settings_roundtrip_ok") is not None]
    settings_ok = all(bool(v) for v in settings_vals) if settings_vals else True
    q3_1 = _q_entry(fake_green, 0, "le", "count", "Q3.1 假绿数 = 0")
    q3_2 = _q_entry(neg_cov, 1.0, "ge", "ratio", "Q3.2 required check 负向测试覆盖率 = 100%")
    q3_3 = _q_entry(1.0 if settings_ok else 0.0, 1.0, "ge", "bool",
                    "Q3.3 settings 与线上 ruleset 逐字一致")
    Q3 = _q_entry(q3_1["value"], 0, "le", "count", "Q3 可信度地基",
                  note=("no gate audit" if not settings_vals
                        and not _collect_num(records, "fake_green_count") else ""),
                  sub={"Q3.1": q3_1, "Q3.2": q3_2, "Q3.3": q3_3})

    # ── Q4：强模型验收（claim 必先被复现）──
    claim_docs = [r for r in records
                  if isinstance(r.get("claims"), list) and "reviewer_model" in r]
    reproductions = [r for r in records if "claim_id" in r and "verdict" in r]
    total_claims = sum(len(d.get("claims", [])) for d in claim_docs)
    rejected = sum(1 for d in claim_docs for c in d.get("claims", [])
                   if isinstance(c, dict) and _is_rejected_claim(c))
    reproduced = sum(1 for r in reproductions if r.get("verdict") == "REPRODUCED")
    total_repro = len(reproductions)
    q4_1 = _q_entry(round(reproduced / total_repro, 4) if total_repro else 1.0,
                    1.0, "ge", "ratio", "Q4.1 进入修复的 claim 100% 有 REPRODUCED")
    q4_2 = _q_entry(round(rejected / total_claims, 4) if total_claims else 0.0,
                    1.0, "le", "ratio", "Q4.2 被拒收 claim 比例可观测且下降")
    solidified = _collect_num(records, "solidified_checkers")
    q4_3 = _q_entry(solidified[-1] if solidified else 0, 3, "ge", "count",
                    "Q4.3 固化为 checker 的 claim ≥3/季度")
    Q4 = _q_entry(q4_1["value"], 1.0, "ge", "ratio", "Q4 强模型验收",
                  note=("no claim evidence" if not total_claims and not total_repro else ""),
                  sub={"Q4.1": q4_1, "Q4.2": q4_2, "Q4.3": q4_3})

    # ── Q5：产品仓对齐 + 依赖升级成功率 ──
    upgrade_results = [r for r in records
                       if "bump_result" in r or "upgrade_ok" in r
                       or ("pkg" in r and "regressed" in r)]
    up_total = len(upgrade_results)
    up_ok = sum(1 for r in upgrade_results
                if r.get("upgrade_ok") is True
                or (r.get("upgrade_ok") is None and r.get("regressed") is False
                    and "pkg" in r))
    upgrade_success_rate = round(up_ok / up_total, 4) if up_total else 0.0
    pin_lag_tags = _collect_num(records, "pin_lag_tags") + _collect_num(records, "loop_version_lag_tags")
    pin_lag_days = _collect_num(records, "pin_lag_days")
    tags_val = _max_or_zero(pin_lag_tags)
    days_val = _max_or_zero(pin_lag_days)
    pin_fresh = tags_val <= 2 and days_val <= 30
    copies = sum(_collect_num(records, "mechanism_copy_count"))
    exemptions = sum(_collect_num(records, "template_sync_exemptions"))
    copies_seen = bool(_collect_num(records, "mechanism_copy_count"))
    exemp_seen = bool(_collect_num(records, "template_sync_exemptions"))
    q5_1 = _q_entry(1.0 if pin_fresh else 0.0, 1.0, "ge", "bool",
                    "Q5.1 loop_version 落后主干 ≤2 tag 且 ≤30 天")
    q5_2 = _q_entry(copies, 0, "le", "count", "Q5.2 loop 机制文件副本数 = 0")
    q5_3 = _q_entry(exemptions, 0, "le", "count", "Q5.3 template-sync PR 豁免数 = 0")
    q5_4 = _q_entry(upgrade_success_rate, 1.0, "ge", "ratio", "Q5.4 依赖升级成功率")
    # headline：取已观测分量的最小值（任一不达标即不达标）；无证据 → 0.0（不静默放行）
    components = []
    if up_total:
        components.append(upgrade_success_rate)
    if pin_lag_tags or pin_lag_days:
        components.append(1.0 if pin_fresh else 0.0)
    if copies_seen:
        components.append(1.0 if copies == 0 else 0.0)
    if exemp_seen:
        components.append(1.0 if exemptions == 0 else 0.0)
    q5_value = round(min(components), 4) if components else 0.0
    Q5 = _q_entry(q5_value, 1.0, "ge", "composite", "Q5 产品仓对齐与依赖升级",
                  note=("no upgrade/pin evidence" if not components else ""),
                  sub={"Q5.1": q5_1, "Q5.2": q5_2, "Q5.3": q5_3, "Q5.4": q5_4})

    return {"Q0": Q0, "Q1": Q1, "Q2": Q2, "Q3": Q3, "Q4": Q4, "Q5": Q5}


def check_q_thresholds(metrics, charter_targets=None):
    """检查 Q 指标是否达标，返回未达标项列表（空 = 全达标）。

    metrics 为 compute_q_metrics 的输出。charter_targets 默认 CHARTER_Q_TARGETS；
    可传入覆盖阈值（用于实验维度收紧/放宽基线）。未达标不静默：调用方据此开 Incident。
    """
    if charter_targets is None:
        charter_targets = CHARTER_Q_TARGETS
    failed = []
    for k in sorted(metrics):
        m = metrics[k]
        if not isinstance(m, dict):
            continue
        tgt = charter_targets.get(k)
        if not tgt:
            # 回退到 metrics 自带的 target/direction
            tgt = {"target": m.get("target"), "direction": m.get("direction", "ge")}
        target = tgt.get("target")
        direction = tgt.get("direction", "ge")
        value = m.get("value")
        if not _meets(value, target, direction):
            failed.append({
                "metric": k,
                "value": value,
                "target": target,
                "direction": direction,
                "note": m.get("note", ""),
            })
    return failed


def compare_experiments(baseline_metrics, experiment_metrics):
    """A/B 实验横向比较：baseline_metrics / experiment_metrics 为 compute_q_metrics
    的输出（或同结构的度量表）。

    与 R12-7 的 experiment 维度共用同一张度量表——任意 A/B 实验的效果用同一套 Q 指标
    横向比较，无需为实验另造度量。返回 {rows, summary}；缺字段不崩（记 None）。
    """
    b = baseline_metrics or {}
    e = experiment_metrics or {}
    rows = []
    keys = sorted(set(k for k in b if isinstance(b.get(k), dict))
                  | set(k for k in e if isinstance(e.get(k), dict)))
    for k in keys:
        be = b.get(k, {}) or {}
        ee = e.get(k, {}) or {}
        bv = be.get("value")
        ev = ee.get("value")
        delta = None
        if (isinstance(bv, (int, float)) and not isinstance(bv, bool)
                and isinstance(ev, (int, float)) and not isinstance(ev, bool)):
            delta = round(ev - bv, 4)
        direction = be.get("direction") or ee.get("direction") or "ge"
        rows.append({
            "metric": k,
            "baseline_value": bv,
            "experiment_value": ev,
            "delta": delta,
            "direction": direction,
            "baseline_status": be.get("status"),
            "experiment_status": ee.get("status"),
            "target": be.get("target") if be.get("target") is not None else ee.get("target"),
        })

    def _better(r):
        d = r["delta"]
        if d is None:
            return False
        return d < 0 if r["direction"] == "le" else d > 0

    def _worse(r):
        d = r["delta"]
        if d is None:
            return False
        return d > 0 if r["direction"] == "le" else d < 0

    return {
        "rows": rows,
        "summary": {
            "better": sum(1 for r in rows if _better(r)),
            "worse": sum(1 for r in rows if _worse(r)),
            "total": len(rows),
        },
    }


def write_dashboard(metrics, out_path="bench/dashboard.json"):
    """把最新指标写成仓库内静态看板 JSON（每次运行覆盖写），不引入外部依赖。

    dashboard 含时间戳（快照用，非回放产物——回放走 compute_q_metrics 纯函数）。
    """
    dashboard = {
        "generated_at": _now_iso(),
        "charter_targets": CHARTER_Q_TARGETS,
        "metrics": metrics,
        "failed": check_q_thresholds(metrics),
    }
    p = pathlib.Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n")
    return str(p)


def cmd_compute_q(args):
    metrics = compute_q_metrics(args.evidence_dir)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    if args.check:
        failed = check_q_thresholds(metrics)
        if failed:
            print("\nQ_THRESHOLD_FAILED:")
            for f in failed:
                print(f"Q_THRESHOLD_FAILED: {f['metric']} value={f['value']} "
                      f"target={f['target']} direction={f['direction']}")
            return 1
    return 0


def cmd_dashboard(args):
    metrics = compute_q_metrics(args.evidence_dir)
    path = write_dashboard(metrics, args.out)
    failed = check_q_thresholds(metrics)
    print(f"wrote dashboard -> {path}  (failed={len(failed)})")
    for f in failed:
        print(f"Q_THRESHOLD_FAILED: {f['metric']} value={f['value']} target={f['target']}")
    return 1 if (args.check and failed) else 0


def cmd_baseline(args):
    cards = load_replay_cards(args.replay_dir)
    metrics, n = aggregate_baseline(cards)
    out = {
        "generated_at": _now_iso(),
        "replayed_cards": n,
        "metrics": metrics,
        "thresholds": DEFAULT_THRESHOLDS,
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n")
        print(f"wrote baseline -> {args.out}  ({n} cards, pass_rate={metrics['first_ci_pass_rate']})")
    else:
        print(text)
    return 0


def cmd_compare(args):
    before = json.loads(pathlib.Path(args.baseline).read_text())
    if args.after_json:
        after = json.loads(pathlib.Path(args.after_json).read_text())
    elif args.after_stdin:
        after = json.loads(sys.stdin.read())
    else:
        print("error: need --after-json or --after-stdin", file=sys.stderr)
        return 2
    bm = before.get("metrics", before)
    am = after.get("metrics", after)
    regressed, details = compare(bm, am, before.get("thresholds"))
    print(render_table(details, before.get("replayed_cards"), after.get("replayed_cards")))
    if regressed:
        print("\nREGRESSED:")
        for m, d in regressed:
            print(f"  REGRESSED: {m} delta={d}")
        return 1
    print("\nOK: no metric regressed past threshold")
    return 0


def cmd_aggregate(args):
    if args.results == "-":
        lines = sys.stdin.read().splitlines()
    else:
        lines = pathlib.Path(args.results).read_text().splitlines()
    metrics, n = aggregate_results_lines(lines)
    out = {"replayed_cards": n, "metrics": metrics}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="bench 四指标采集与对比")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("baseline", help="从 replay 卡聚合基线")
    p1.add_argument("--replay-dir", default="bench/replay")
    p1.add_argument("--out", default=None)
    p1.set_defaults(func=cmd_baseline)

    p2 = sub.add_parser("compare", help="对比 before/after，劣化退出 1")
    p2.add_argument("--baseline", default="bench/baseline.json")
    p2.add_argument("--after-json", default=None)
    p2.add_argument("--after-stdin", action="store_true")
    p2.set_defaults(func=cmd_compare)

    p3 = sub.add_parser("aggregate", help="把 replay.sh 结果行聚合为四指标")
    p3.add_argument("--results", default="-")
    p3.set_defaults(func=cmd_aggregate)

    p4 = sub.add_parser("compute-q", help="从 evidence 计算 CHARTER 全部 Q 指标")
    p4.add_argument("--evidence-dir", default=".", help="evidence 目录（递归读 *.json）")
    p4.add_argument("--check", action="store_true", help="检查 Q 阈值，未达标退出 1")
    p4.set_defaults(func=cmd_compute_q)

    p5 = sub.add_parser("dashboard", help="写静态看板 dashboard.json（覆盖写）")
    p5.add_argument("--out", default="bench/dashboard.json")
    p5.add_argument("--evidence-dir", default=".")
    p5.add_argument("--check", action="store_true", help="未达标退出 1")
    p5.set_defaults(func=cmd_dashboard)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
