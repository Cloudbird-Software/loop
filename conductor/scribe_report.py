#!/usr/bin/env python3
"""conductor/scribe_report.py — 零 LLM 确定性日报。

读取 journal-snapshot/ 下的 JSON，输出含以下五字段的日报（OPC-v4 第 2.2 节环 7）：
  1. confirm_taps   —— 点击器确认次数（从 taps.log 行数统计）
  2. bypass 点名    —— 绕过 ruleset 的 actor 列表（从 rule-suites 解析）
  3. 僵尸卡         —— lease 过期但仍 claimed/in_progress 的卡
  4. canary         —— 合成工单链路最近运行状态
  5. 成本           —— Actions 运行分钟数 × 单价（确定性，无 billing API）

所有字段均由本仓库导出的 JSON 派生，零 LLM 调用，可重复生成。
"""
import json
import sys
import os
import pathlib
import datetime

# Actions 公开定价（Linux，2 核）：$0.008/分钟。仅作确定性估算，非真实账单。
ACTIONS_RATE_USD_PER_MIN = 0.008
USD_TO_CNY = 7.2


def load(name, snap_dir):
    p = pathlib.Path(snap_dir) / name
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except Exception:
        return []
    # GitHub API 常把列表包在对象里：{"workflow_runs":[...]}, {"rule_suites":[...]}
    if isinstance(data, dict):
        for key in ("workflow_runs", "rule_suites", "items", "value"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    if isinstance(data, list):
        return data
    return []


def load_text(name, snap_dir):
    p = pathlib.Path(snap_dir) / name
    if not p.exists():
        return ""
    return p.read_text()


def count_confirm_taps(snap_dir):
    """统计 taps.log 的非空行数。点击器每次点击 append 一行，每小时 push 到 journal/taps/。

    snapshot 阶段把当日的 taps.log 拉到 journal-snapshot/taps.log。
    无文件则记 0（目标恒为 0，>20 触发 Incident）。
    """
    text = load_text("taps.log", snap_dir)
    if not text:
        return 0, []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines), lines


def detect_bypass_actors(rule_suites):
    """从 rule-suites 提取 bypass_actor，去重并计数。

    GitHub rule-suites API 的 bypass 字段：result=bypass 时带 bypass_actor.login。
    """
    actors = {}
    for rs in rule_suites or []:
        # 兼容两种结构：list 直接是 suites，或 {"rule_suites": [...]}
        if isinstance(rs, dict) and "rule_suites" in rs:
            for sub in rs["rule_suites"]:
                _tally(sub, actors)
            continue
        _tally(rs, actors)
    return actors


def _tally(rs, actors):
    if not isinstance(rs, dict):
        return
    result = (rs.get("result") or "").lower()
    actor = (rs.get("bypass_actor") or {}).get("login") if isinstance(rs.get("bypass_actor"), dict) else None
    if result == "bypass" or actor:
        key = actor or rs.get("actor", {}).get("login", "unknown")
        actors[key] = actors.get(key, 0) + 1


def detect_zombie_cards(issues, ref_ts):
    """僵尸卡：state ∈ {claimed, in_progress} 且 lease_until < ref_ts。"""
    zombie = []
    for it in issues:
        body = it.get("body", "") or ""
        if "```json loop" not in body:
            continue
        seg = body.split("```json loop", 1)[1].split("```", 1)[0]
        try:
            blk = json.loads(seg)
        except Exception:
            continue
        if blk.get("state") not in ("claimed", "in_progress"):
            continue
        lease = blk.get("lease_until", 0)
        try:
            lease_f = float(lease)
        except (TypeError, ValueError):
            lease_f = 0
        if lease_f and lease_f < ref_ts:
            zombie.append({
                "number": it.get("number"),
                "id": blk.get("id", "?"),
                "state": blk.get("state"),
                "lease_until": lease_f,
                "sandbox": blk.get("sandbox", "?"),
            })
    return zombie


def summarize_canary(runs, ref_ts):
    """canary 链路状态：最近 N 次运行的成功/失败计数 + 最近一次结论。"""
    canary_runs = [r for r in runs if "canary" in (r.get("name") or "").lower()]
    total = len(canary_runs)
    ok = 0
    fail = 0
    latest = None
    latest_ts = ""
    for r in canary_runs:
        concl = (r.get("conclusion") or "").lower()
        if concl == "success":
            ok += 1
        elif concl in ("failure", "cancelled", "timed_out", "action_required"):
            fail += 1
        # 找最近一次（ISO 字符串字典序 == 时间序）
        ts = r.get("run_started_at") or r.get("created_at") or ""
        if ts > latest_ts:
            latest_ts = ts
            latest = r
    latest_info = "n/a"
    if latest:
        latest_info = f"#{latest.get('id','?')} ({latest.get('conclusion','?')}) @ {latest_ts}"
    return {"total": total, "success": ok, "failure": fail, "latest": latest_info}


def compute_cost(runs):
    """成本估算：Actions 运行分钟数 × 公开单价。

    无 billing API 权限时，用 workflow runs 的 run_duration_ms 累加估算。
    返回 (minutes, usd, cny)。
    """
    total_ms = 0
    for r in runs or []:
        dur = r.get("run_duration_ms") or r.get("duration_ms")
        if dur:
            try:
                total_ms += float(dur)
            except (TypeError, ValueError):
                pass
    minutes = total_ms / 60000.0
    usd = minutes * ACTIONS_RATE_USD_PER_MIN
    cny = usd * USD_TO_CNY
    return minutes, usd, cny


def main():
    snap = sys.argv[1] if len(sys.argv) > 1 else "journal-snapshot/"
    # 参考时间：优先用环境变量（确定性），否则取当前 UTC。
    ref_env = os.environ.get("SCRIBE_REF_TS")
    if ref_env:
        try:
            ref_ts = float(ref_env)
        except ValueError:
            ref_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    else:
        ref_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    now_str = datetime.datetime.fromtimestamp(ref_ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    issues = load("issues.json", snap)
    prs = load("prs.json", snap)
    runs = load("runs.json", snap)
    # 合并 loop 控制面 runs（含 canary/scribe/drift），使 canary 字段可见
    loop_runs = load("loop-runs.json", snap)
    all_runs = list(runs) + list(loop_runs)
    rule_suites = load("rule-suites.json", snap)

    # 1. confirm_taps
    tap_count, tap_lines = count_confirm_taps(snap)

    # 2. bypass 点名
    bypass = detect_bypass_actors(rule_suites)

    # 3. 僵尸卡
    zombie = detect_zombie_cards(issues, ref_ts)

    # 4. canary（扫描 product-x + loop 控制面 runs）
    canary = summarize_canary(all_runs, ref_ts)

    # 5. 成本（合并 product-x + loop runs 的运行时长）
    minutes, usd, cny = compute_cost(all_runs)

    lines = [
        f"# Daily Report — {now_str}",
        "",
        f"- issues: {len(issues)}",
        f"- prs: {len(prs)}",
        f"- runs: {len(runs)} (product-x) + {len(loop_runs)} (loop) = {len(all_runs)}",
        f"- rule-suites: {len(rule_suites) if isinstance(rule_suites, list) else 0}",
        "",
        "## confirm_taps",
        f"**total: {tap_count}**  (目标恒为 0；单波次 > 20 触发 Incident)",
        "",
        "## Bypass actors",
    ]
    if bypass:
        for actor, n in sorted(bypass.items(), key=lambda x: -x[1]):
            lines.append(f"- @{actor}: {n} 次")
    else:
        lines.append("(none detected)")

    lines += ["", "## Zombie cards", f"**count: {len(zombie)}**"]
    if zombie:
        for z in zombie:
            lease_str = datetime.datetime.fromtimestamp(z["lease_until"], datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"- #{z['number']} ({z['id']}) state={z['state']} lease_until={lease_str} sandbox={z['sandbox']}")
    else:
        lines.append("(none)")

    lines += [
        "",
        "## Canary",
        f"- total runs: {canary['total']}",
        f"- success: {canary['success']}",
        f"- failure: {canary['failure']}",
        f"- latest: {canary['latest']}",
    ]

    lines += [
        "",
        "## Cost",
        f"- actions minutes (estimated): {minutes:.1f}",
        f"- estimated USD: ${usd:.4f}",
        f"- estimated CNY: ¥{cny:.4f}",
        f"- rate: ${ACTIONS_RATE_USD_PER_MIN}/min (Linux 2-core public price), 1 USD = {USD_TO_CNY} CNY",
        "- 注：本字段为确定性估算（runs.run_duration_ms 累加），非真实账单；真实账单待 billing API 接入后替换。",
    ]

    print("\n".join(lines))


if __name__ == "__main__":
    main()
