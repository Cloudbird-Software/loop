#!/usr/bin/env python3
"""conductor/retro.py — 每周五产出 retro Finding（OPC-v4 P6 五个问题）。

只回答 P6 的五个问题，数据来自 journal（或本地伪造 fixtures）：
  Q1. 本周哪一类卡系统性失败？（按 tier/lens/paths 聚类，给数字）
  Q2. 失败的共同前置条件是什么？（例：契约未先行 / 卡粒度过大 / AC 理解分叉）
  Q3. session_ordinal 与首次 CI 通过率的关系如何？（若第 k 张之后通过率下降 >10% → 建议 max_cards_per_session = k-1）
  Q4. 哪一条应该变成检查器或流程改动？（具体到文件的改法，最多 2 条）
  Q5. 上周复盘提出的改动落地了吗？（有/无/半，给证据）

结构：
  - 零 LLM 汇总部分（纯数字 / 纯统计）——本脚本直接产出
  - LLM 归因部分（为什么会这样）——暂留 plan-ops adapter（stub，写入 _pending_adapter）
"""
import json, os, subprocess, sys, time, datetime, collections, pathlib, hashlib, tempfile, re

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
LOOP_ROOT = pathlib.Path(E.get("LOOP_ROOT", "/workspace"))
JOURNAL_DIR = LOOP_ROOT / ".loop" / "journal"
RETRO_OUTBOX = LOOP_ROOT / ".loop" / "retro"
RETRO_PREV = LOOP_ROOT / ".loop" / "retro" / "prev_action_items.json"
POLICY_FILE = E.get("LOOP_POLICY", "policy.yml")
LLM_ATTRIBUTION_ADAPTER = "plan-ops"   # 以后可以换成 plan-ops-1 sandbox 接口；目前只写 stub

# ==================================================================
# 通用
# ==================================================================
def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)

def gh(*a):
    return sh("gh", *a)

def extract_block(body):
    m = "```json loop"
    if m not in (body or ""): return None
    seg = body.split(m,1)[1].split("```",1)[0]
    try: return json.loads(seg)
    except Exception: return None

def inject_block(body, blk):
    m = "```json loop"
    if m not in (body or ""):
        return (body or "") + "\n\n```json loop\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```\n"
    head, rest = body.split(m,1); tail = rest.split("```",1)[1]
    return head + "```json loop\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```" + tail

def load_policy():
    try:
        import yaml
        with open(POLICY_FILE) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return {}

POLICY = load_policy()

def week_range():
    """返回本周 ISO 周范围（周一 00:00 ~ 周日 23:59 UTC-approx）。"""
    now = datetime.datetime.utcnow()
    monday = now - datetime.timedelta(days=now.weekday())
    monday0 = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_num = monday0.isocalendar()[1]
    year = monday0.year
    return (year, week_num, monday0, now)

# ==================================================================
# 数据采集：从 journal/ 或 从 issues/PR runs 就地采集
# ==================================================================
def _collect_card_lifecycles(since_iso):
    """近 7 天所有 Card 的 state/attempt/verdict/tier/paths/session_ordinal。"""
    cards = []
    # 从 repo issues 抓（journal/ 是 mirror，这里直接读源）
    p = gh("issue","list","-R",REPO,"--state","all","--limit","200",
           "--json","number,title,body,state,updatedAt,labels,createdAt,comments")
    try:
        items = json.loads(p.stdout or "[]")
    except Exception:
        return cards
    since = datetime.datetime.fromisoformat(since_iso.replace("Z","")) if isinstance(since_iso, str) else since_iso
    for it in items:
        blk = extract_block(it["body"])
        if not blk: continue
        try:
            upd = datetime.datetime.fromisoformat(it["updatedAt"].replace("Z",""))
            cre = datetime.datetime.fromisoformat(it["createdAt"].replace("Z",""))
        except Exception:
            continue
        if upd < since and cre < since:
            continue
        verdict_sha = blk.get("verify", {}).get("verdict_sha") if isinstance(blk.get("verify"), dict) else None
        cards.append({
            "number": it["number"],
            "id": blk.get("id", f"#{it['number']}"),
            "tier": blk.get("tier", "standard"),
            "paths": blk.get("paths", []),
            "attempt": blk.get("attempt", 0),
            "session_ordinal": blk.get("session_ordinal"),
            "model": blk.get("model"),
            "sandbox": blk.get("sandbox"),
            "verdict_sha": verdict_sha,
            "state": blk.get("state", it["state"]),
            "failed": blk.get("attempt", 0) >= 2 or it["state"] == "open" and blk.get("state") not in ("closed","done","merged"),
            "labels": [l.get("name","") for l in it.get("labels",[])],
            "charter": blk.get("charter", []),
            "verify_required": blk.get("verify",{}).get("required", False) if isinstance(blk.get("verify"),dict) else False,
        })
    return cards

def _collect_ci_stats(since_iso):
    """近 7 天的 CI 首次通过率、失败分布。"""
    p = gh("run","list","-R",REPO,"--limit","200","--created",">="+since_iso,
           "--json","name,conclusion,headBranch,createdAt,event")
    try:
        runs = json.loads(p.stdout or "[]")
    except Exception:
        return {"total": 0, "successes": 0, "failures_by_wf": {}}
    fbw = collections.Counter()
    ok = 0
    for r in runs:
        if r.get("conclusion") == "success":
            ok += 1
        elif r.get("conclusion") in ("failure", "cancelled", "timed_out"):
            fbw[r.get("name","?")] += 1
    return {"total": len(runs), "successes": ok, "failures_by_wf": dict(fbw)}

def _collect_prev_action_items():
    try:
        return json.loads(RETRO_PREV.read_text())
    except Exception:
        return {}

# ==================================================================
# Q1: 系统性失败聚类
# ==================================================================
def q1_systemic_failures(cards):
    by_tier = collections.Counter()
    by_path_prefix = collections.Counter()
    by_charter = collections.Counter()
    failed_total = 0
    for c in cards:
        if not c["failed"]: continue
        failed_total += 1
        by_tier[c["tier"]] += 1
        for p in c["paths"]:
            pref = p.split("/")[0] if "/" in p else p
            by_path_prefix[pref] += 1
        for ch in c["charter"]:
            by_charter[ch] += 1
    total = len(cards) or 1
    ans = {
        "total_cards_window": len(cards),
        "failed_total": failed_total,
        "failure_rate": round(failed_total / total, 3),
        "by_tier": dict(by_tier.most_common()),
        "by_path_prefix_top5": dict(by_path_prefix.most_common(5)),
        "by_charter": dict(by_charter.most_common()),
    }
    # 系统性：某一类失败率 >= 35% 且 样本 >= 2
    systemic = []
    if by_tier:
        tmax, tcnt = by_tier.most_common(1)[0]
        if tcnt / max(failed_total,1) >= 0.35 and tcnt >= 2:
            systemic.append(f"tier={tmax}: {tcnt}/{failed_total} 失败")
    if by_path_prefix:
        pmax, pcnt = by_path_prefix.most_common(1)[0]
        if pcnt / max(failed_total,1) >= 0.35 and pcnt >= 2:
            systemic.append(f"path_prefix={pmax}: {pcnt}/{failed_total} 失败")
    ans["systemic_callouts"] = systemic or ["无明显系统性失败聚类"]
    return ans

# ==================================================================
# Q2: 共同前置条件
# ==================================================================
def q2_common_preconditions(cards, ci_stats):
    failed = [c for c in cards if c["failed"]]
    precond = collections.Counter()
    for c in failed:
        # 粒度过大：attempt>=4 或 attempt>=3+diff>600
        if c["attempt"] >= 3:
            precond["attempt>=3 (粒度过大或模型不适配)"] += 1
        # verify 强制盲半但失败
        if c["verify_required"] and c["attempt"] >= 2:
            precond["verify_required=True 但 AC 理解分叉 (attempt>=2)"] += 1
        # tier=critical but attempt>=2
        if c["tier"] == "critical" and c["attempt"] >= 2:
            precond["critical+attempt>=2 (复杂度+风险叠加)"] += 1
        # 没有 charter 映射
        if not c.get("charter"):
            precond["charter 映射缺失"] += 1
    # CI failure top workflow
    ci_top = ci_stats.get("failures_by_wf", {})
    ci_list = sorted(ci_top.items(), key=lambda x: -x[1])[:3]
    return {
        "top_preconditions": dict(precond.most_common()),
        "ci_failure_top3": ci_list,
        "ci_total_runs": ci_stats.get("total", 0),
        "ci_first_pass_rate": round(ci_stats.get("successes",0)/max(ci_stats.get("total",1),1), 3),
    }

# ==================================================================
# Q3: session_ordinal vs 首次 CI 通过率
# ==================================================================
def q3_session_ordinal_vs_pass(cards):
    by_ord = collections.defaultdict(lambda: [0, 0])  # ord -> [passed, failed]
    for c in cards:
        so = c.get("session_ordinal")
        if so is None: continue
        if c["failed"]:
            by_ord[so][1] += 1
        else:
            by_ord[so][0] += 1
    series = {}
    for k in sorted(by_ord.keys()):
        p, f = by_ord[k]
        tot = p+f
        series[k] = {"total": tot, "passed": p, "failed": f, "pass_rate": round(p/max(tot,1), 3)}
    # 找建议值：若 ord=k 的通过率相对 ord=k-1 下降 >10% → 建议 max=k-1
    exe_sec = POLICY.get("execute", {})
    if not isinstance(exe_sec, dict): exe_sec = {}
    max_session = exe_sec.get("max_cards_per_session", 6)
    try: max_session = int(max_session)
    except Exception: max_session = 6
    global_pass = sum(v[0] for v in by_ord.values()) / max(sum(v[0]+v[1] for v in by_ord.values()), 1)
    recommended = max_session
    reason = f"全局 pass_rate={round(global_pass,3)}；当前 policy max={max_session}"
    sorted_keys = sorted(by_ord.keys())
    for idx in range(1, len(sorted_keys)):
        k_cur = sorted_keys[idx]
        k_prev = sorted_keys[idx-1]
        if k_cur - k_prev != 1: continue   # 只看相邻 ord
        prev_pr = series.get(k_prev, {}).get("pass_rate", 0)
        cur_pr = series.get(k_cur, {}).get("pass_rate", 0)
        tot_prev = series.get(k_prev, {}).get("total", 0)
        tot_cur = series.get(k_cur, {}).get("total", 0)
        if tot_prev < 3 or tot_cur < 3: continue
        drop = prev_pr - cur_pr
        if drop > 0.10 and k_prev < recommended:
            recommended = k_prev
            reason = (f"ord={k_prev} pass_rate={prev_pr} → ord={k_cur} pass_rate={cur_pr}，"
                      f"下降 {round(drop,3)}>10%；建议 max_cards_per_session={k_prev}")
            break
    return {"series": series, "recommended_max_cards_per_session": recommended, "reason": reason}

# ==================================================================
# Q4: 检查器 / 流程改动建议（最多 2 条）
# ==================================================================
def q4_checker_proposals(q1, q2):
    proposals = []
    # 启发式：若某 tier/path 系统性失败 → 加检查器
    s = q1.get("systemic_callouts", [])
    if s and s[0] != "无明显系统性失败聚类":
        for sc in s[:1]:
            if "path_prefix=" in sc:
                pref = sc.split("path_prefix=")[1].split(":")[0]
                proposals.append({
                    "kind": "checker",
                    "file_hint": f"gates/gate_{pref}_bundle.py",
                    "change": f"为 {pref}/** 加一个变更前 lint 检查器（gate），在 PR 阶段阻断"
                              f" 已知易踩坑模式；参考 gates/gate_paths.py 写法（≤60行）。",
                    "triggered_by": sc,
                })
    # CI failure top1 若是 gates 相关 → 加流程
    ciftop = q2.get("ci_failure_top3", [])
    if ciftop:
        wf, cnt = ciftop[0]
        if "gate" in wf.lower() or "verify" in wf.lower():
            proposals.append({
                "kind": "process",
                "file_hint": ".github/workflows/_gate.yml",
                "change": f"CI 失败最高频 {wf}（{cnt}次）：在 loop verify 之前追加"
                          f" `--dry-run` 自检环节，把易失败点离线前置。",
                "triggered_by": f"wf={wf} failures={cnt}",
            })
    # 至少给一条占位（避免为空）
    if not proposals:
        proposals.append({
            "kind": "process",
            "file_hint": "policy.yml -> execute.max_cards_per_session",
            "change": "按 Q3 建议调整单会话卡上限；无其他明显系统性缺陷。",
            "triggered_by": "fallback",
        })
    return proposals[:2]

# ==================================================================
# Q5: 上周行动项落地检查
# ==================================================================
def q5_prev_action_items_landed(prev_items):
    if not prev_items:
        return {"status": "none", "n": 0, "evidence": []}
    n = len(prev_items)
    landed = 0; partial = 0; missed = 0
    evidence = []
    for key, item in prev_items.items():
        expected_kw = item.get("expected_change_sha_or_keyword", "")
        # 简化版：查 git log 是否含关键词（此处 stub，标记"半"）
        # 真实版：subprocess.run(["git","log","--oneline","-50"]) 搜
        if expected_kw:
            evidence.append(f"{key}: 半 — 未验证（journal mirror 或 git log 未检查到）")
            partial += 1
        else:
            evidence.append(f"{key}: 有 — expected 字段为空视为落地")
            landed += 1
    status = "checked"
    return {"status": status, "n": n, "landed": landed, "partial": partial, "missed": missed, "evidence": evidence}

# ==================================================================
# main
# ==================================================================
def main():
    year, week, monday0, now = week_range()
    since = (monday0 - datetime.timedelta(days=1)).isoformat()
    print(f"=== retro {year}-W{week:02d} (from {since}) ===")
    RETRO_OUTBOX.mkdir(parents=True, exist_ok=True)

    cards = _collect_card_lifecycles(since)
    ci_stats = _collect_ci_stats(since)
    print(f"cards in window: {len(cards)}; CI runs: {ci_stats.get('total',0)}")

    a1 = q1_systemic_failures(cards)
    a2 = q2_common_preconditions(cards, ci_stats)
    a3 = q3_session_ordinal_vs_pass(cards)
    a4 = q4_checker_proposals(a1, a2)
    a5 = q5_prev_action_items_landed(_collect_prev_action_items())

    # 零 LLM 汇总块
    retro_block = {
        "schema": "retro-v1",
        "week": f"{year}-W{week:02d}",
        "generated_at": now.isoformat(),
        "zero_llm": True,
        "q1_systemic_failures": a1,
        "q2_common_preconditions": a2,
        "q3_session_ordinal": a3,
        "q4_checker_proposals": a4,
        "q5_prev_landed": a5,
    }

    # 保存行动项（为下周 Q5 检查用）
    action_items = {}
    for i, p in enumerate(a4):
        key = f"{year}W{week:02d}-{i+1:02d}"
        action_items[key] = {
            "kind": p.get("kind"),
            "file": p.get("file_hint"),
            "expected_change_sha_or_keyword": p.get("change","")[:40],
            "change": p.get("change"),
        }
    RETRO_PREV.write_text(json.dumps(action_items, indent=2, ensure_ascii=False))
    print(f"saved {len(action_items)} action items → {RETRO_PREV}")

    # LLM 归因部分：plan-ops adapter（stub，等真实接口后替换）
    llm_attr = {
        "schema": "llm-attribution-stub",
        "adapter": LLM_ATTRIBUTION_ADAPTER,
        "channel": "plan-ops",
        "status": "pending",
        "generated_at": now.isoformat(),
        "questions": {
            "why_systemic": "（stub）调用 plan-ops sandbox 让 LLM 回答：为什么 Q1 该类系统性失败会出现？（附 journal + CI stats 上下文）",
            "why_preconditions": "（stub）调用 plan-ops sandbox 让 LLM 回答：如何从 Q2 前置条件上游拦截？",
        },
        "input_summary_keys": ["q1_systemic_failures.systemic_callouts","q2_common_preconditions.top_preconditions"],
    }
    llm_path = RETRO_OUTBOX / f"llm_attribution_{year}W{week:02d}.json"
    llm_path.write_text(json.dumps(llm_attr, indent=2, ensure_ascii=False))
    print(f"LLM attribution stub → {llm_path}")

    # 产出 Finding issue 正文（markdown）
    issue_body = f"""# 周度 Retro {year}-W{week:02d}（zero_llm + LLM attribution via plan-ops）

> 生成时间：{now.isoformat()} UTC  
> 数据窗口：{since} ~ {now.isoformat()} UTC  
> 卡片样本：{len(cards)} 张；CI 运行：{ci_stats.get('total',0)} 次

## Q1. 本周哪一类卡系统性失败？（按 tier/lens/paths 聚类，给数字）

```json
{json.dumps(a1, indent=2, ensure_ascii=False)}
```

## Q2. 失败的共同前置条件是什么？

```json
{json.dumps(a2, indent=2, ensure_ascii=False)}
```

## Q3. session_ordinal vs 首次 CI 通过率

```json
{json.dumps(a3, indent=2, ensure_ascii=False)}
```

## Q4. 应该变成检查器或流程改动的项（最多 2 条）

```json
{json.dumps(a4, indent=2, ensure_ascii=False)}
```

## Q5. 上周复盘提出的改动落地了吗？

```json
{json.dumps(a5, indent=2, ensure_ascii=False)}
```

## 五份 JSON 输出 artifact 清单

- retro JSON：`.loop/retro/retro_{year}W{week:02d}.json`
- LLM 归因（plan-ops adapter, pending）：`.loop/retro/llm_attribution_{year}W{week:02d}.json`
- 本周行动项（下周 Q5 检查）：`.loop/retro/prev_action_items.json`
- issue 正文：`.loop/retro/retro_{year}W{week:02d}_issue.md`
"""

    md_path = RETRO_OUTBOX / f"retro_{year}W{week:02d}_issue.md"
    md_path.write_text(issue_body, encoding="utf-8")
    print(f"retro issue body → {md_path}")

    # 开 Finding issue（失败不阻塞）
    try:
        p = subprocess.run(
            ["gh","issue","create","-R",REPO,
             "--title",f"Retro-{year}W{week:02d} 五问零 LLM 汇总",
             "--label","finding","--label","retro",
             "--body-file", str(md_path)],
            capture_output=True, text=True,
        )
        print(f"opened retro Finding issue: {p.stdout.strip()}")
    except Exception as e:
        print(f"open retro issue failed (non-fatal): {e}")

    # 保存 JSON artifact（完整 retro block）
    json_path = RETRO_OUTBOX / f"retro_{year}W{week:02d}.json"
    json_path.write_text(json.dumps(retro_block, indent=2, ensure_ascii=False))
    print(f"retro JSON artifact → {json_path}")

if __name__ == "__main__":
    main()
