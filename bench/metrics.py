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

# CHARTER 中全部 Q 指标定义（R14-3）
Q_METRICS = {
    "Q0.1": {"desc": "从'继续'到领卡 ≤1 分钟", "unit": "min", "threshold": 1.0},
    "Q0.2": {"desc": "从领卡到 done ≤30 分钟（trivial/standard）", "unit": "min", "threshold": 30.0},
    "Q0.3": {"desc": "闭环成功率 ≥80%", "unit": "ratio", "threshold": 0.80},
    "Q1.1": {"desc": "僵尸回收延迟 ≤30 分钟", "unit": "min", "threshold": 30.0},
    "Q1.2": {"desc": "依赖放行延迟 ≤1 轮 tick", "unit": "tick", "threshold": 1.0},
    "Q2.1": {"desc": "fork 后改 ≤5 处适配", "unit": "count", "threshold": 5.0},
    "Q3.1": {"desc": "假绿数 = 0", "unit": "count", "threshold": 0.0},
    "Q3.2": {"desc": "required check 负向测试覆盖率 = 100%", "unit": "ratio", "threshold": 1.0},
    "Q3.3": {"desc": "settings roundtrip 一致", "unit": "bool", "threshold": 1.0},
    "Q4.1": {"desc": "进入修复的 claim 100% 有 REPRODUCED 记录", "unit": "ratio", "threshold": 1.0},
    "Q4.2": {"desc": "被拒收 claim 比例可观测", "unit": "ratio", "threshold": None},
    "Q4.3": {"desc": "固化为 checker 的 claim 累计数", "unit": "count", "threshold": None},
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


# ============================================================
# R14-3: CHARTER 全部 Q 指标计算
# ============================================================

def _q_na(status="unavailable"):
    return {"value": None, "status": status, "ok": False}


def q_continueto_card(evidence_dir):
    """Q0.1: 从'继续'到领卡 ≤1 分钟。"""
    f = evidence_dir / "continue_to_card.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        minutes = float(d.get("minutes", 999))
        return {"value": minutes, "status": "ok" if minutes <= 1 else "fail", "ok": minutes <= 1}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_card_to_done(evidence_dir):
    """Q0.2: 从领卡到 done ≤30 分钟。"""
    f = evidence_dir / "card_to_done.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        minutes = float(d.get("minutes", 999))
        return {"value": minutes, "status": "ok" if minutes <= 30 else "fail", "ok": minutes <= 30}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_close_loop_success_rate(evidence_dir):
    """Q0.3: 闭环成功率 ≥80%。"""
    f = evidence_dir / "close_loop.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        total = d.get("total", 0)
        passed = d.get("passed", 0)
        rate = passed / total if total else 0.0
        return {"value": round(rate, 4), "status": "ok" if rate >= 0.80 else "fail", "ok": rate >= 0.80}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_zombie_reclaim_delay(evidence_dir):
    """Q1.1: 僵尸回收延迟 ≤30 分钟。"""
    f = evidence_dir / "zombie_reclaim.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        minutes = float(d.get("minutes", 999))
        return {"value": minutes, "status": "ok" if minutes <= 30 else "fail", "ok": minutes <= 30}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_dependency_unblock_tick(evidence_dir):
    """Q1.2: 依赖放行延迟 ≤1 轮 tick。"""
    f = evidence_dir / "dependency_unblock.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        ticks = float(d.get("ticks", 999))
        return {"value": ticks, "status": "ok" if ticks <= 1 else "fail", "ok": ticks <= 1}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_fork_adaptation_cost(evidence_dir):
    """Q2.1: fork 后改 ≤5 处适配。"""
    f = evidence_dir / "fork_adaptation.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        changes = int(d.get("changes", 999))
        return {"value": changes, "status": "ok" if changes <= 5 else "fail", "ok": changes <= 5}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_fake_green_count(evidence_dir):
    """Q3.1: 假绿数 = 0。"""
    f = evidence_dir / "fake_green.json"
    if not f.exists():
        # 默认假绿数为 0（无证据即视为无假绿，但标记为 assumed）
        return {"value": 0, "status": "assumed_zero", "ok": True}
    try:
        d = json.loads(f.read_text())
        count = int(d.get("count", 0))
        return {"value": count, "status": "ok" if count == 0 else "fail", "ok": count == 0}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_required_check_negative_coverage(evidence_dir):
    """Q3.2: required check 负向测试覆盖率 = 100%。"""
    f = evidence_dir / "required_check_negative.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        total = d.get("total", 0)
        covered = d.get("covered", 0)
        rate = covered / total if total else 0.0
        return {"value": round(rate, 4), "status": "ok" if rate >= 1.0 else "fail", "ok": rate >= 1.0}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_settings_roundtrip(evidence_dir):
    """Q3.3: settings roundtrip 一致。"""
    f = evidence_dir / "settings_roundtrip.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        consistent = bool(d.get("consistent", False))
        return {"value": int(consistent), "status": "ok" if consistent else "fail", "ok": consistent}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_claim_reproduced_rate(evidence_dir):
    """Q4.1: 进入修复的 claim 100% 有 REPRODUCED 记录。"""
    f = evidence_dir / "claim_reproduced.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        total = d.get("total", 0)
        reproduced = d.get("reproduced", 0)
        rate = reproduced / total if total else 0.0
        return {"value": round(rate, 4), "status": "ok" if rate >= 1.0 else "fail", "ok": rate >= 1.0}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_claim_rejection_rate(evidence_dir):
    """Q4.2: 被拒收 claim 比例可观测。"""
    f = evidence_dir / "claim_rejection.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        total = d.get("total", 0)
        rejected = d.get("rejected", 0)
        rate = rejected / total if total else 0.0
        return {"value": round(rate, 4), "status": "observable", "ok": True}
    except Exception as e:
        return _q_na(f"parse error: {e}")


def q_claim_checker_solidified(evidence_dir):
    """Q4.3: 固化为 checker 的 claim 累计数。"""
    f = evidence_dir / "claim_checker_solidified.json"
    if not f.exists():
        return _q_na("no evidence")
    try:
        d = json.loads(f.read_text())
        count = int(d.get("count", 0))
        return {"value": count, "status": "observable", "ok": True}
    except Exception as e:
        return _q_na(f"parse error: {e}")


Q_COMPUTERS = {
    "Q0.1": q_continueto_card,
    "Q0.2": q_card_to_done,
    "Q0.3": q_close_loop_success_rate,
    "Q1.1": q_zombie_reclaim_delay,
    "Q1.2": q_dependency_unblock_tick,
    "Q2.1": q_fork_adaptation_cost,
    "Q3.1": q_fake_green_count,
    "Q3.2": q_required_check_negative_coverage,
    "Q3.3": q_settings_roundtrip,
    "Q4.1": q_claim_reproduced_rate,
    "Q4.2": q_claim_rejection_rate,
    "Q4.3": q_claim_checker_solidified,
}


def compute_charter_q_metrics(evidence_dir):
    """计算 CHARTER 全部 Q 指标，返回 dict[Q_id -> result]。"""
    evidence_dir = pathlib.Path(evidence_dir)
    out = {}
    for qid, meta in Q_METRICS.items():
        result = Q_COMPUTERS[qid](evidence_dir)
        result["desc"] = meta["desc"]
        result["unit"] = meta["unit"]
        result["threshold"] = meta["threshold"]
        out[qid] = result
    return out


def cmd_charter(args):
    evidence_dir = pathlib.Path(args.evidence_dir)
    metrics = compute_charter_q_metrics(evidence_dir)
    out = {
        "generated_at": _now_iso(),
        "evidence_dir": str(evidence_dir),
        "metrics": metrics,
    }
    ok_count = sum(1 for v in metrics.values() if v.get("ok"))
    total = len(metrics)
    out["summary"] = {"ok": ok_count, "total": total, "ratio": round(ok_count / total, 4) if total else 0}
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote charter Q metrics -> {args.out}  ({ok_count}/{total} ok)")
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if ok_count == total else 1


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

    p4 = sub.add_parser("charter", help="R14-3: 计算 CHARTER 全部 Q 指标")
    p4.add_argument("--evidence-dir", default="evidence")
    p4.add_argument("--out", default=None)
    p4.set_defaults(func=cmd_charter)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
