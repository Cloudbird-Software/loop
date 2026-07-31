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
  - LLM 归因部分（为什么会这样）——retro 未集成 LLM 调用，标注为 human-verify 并生成待办（不假实现）
  - 波次验收部分（run_wave_acceptance）——解析 Wave 文件的『本波次的检查方法』段，逐条执行机器可执行检查
  - 通知部分（notify）——走 GitHub Issue 评论 / 开 Incident issue，作为真实可送达通道
"""
import json, os, subprocess, sys, time, datetime, collections, pathlib, hashlib, tempfile, re

try:
    from conductor.blocks import extract_block, inject_block
except ImportError:
    from blocks import extract_block, inject_block

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
LOOP_ROOT = pathlib.Path(E.get("LOOP_ROOT", "/workspace"))
JOURNAL_DIR = LOOP_ROOT / ".loop" / "journal"
RETRO_OUTBOX = LOOP_ROOT / ".loop" / "retro"
RETRO_PREV = LOOP_ROOT / ".loop" / "retro" / "prev_action_items.json"
POLICY_FILE = E.get("LOOP_POLICY", "policy.yml")
LLM_ATTRIBUTION_ADAPTER = "plan-ops"   # 通道：plan-ops；retro 未集成 LLM 调用，归因标注为 human-verify（不假实现）

# ==================================================================
# 通用
# ==================================================================
def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)

def gh(*a):
    return sh("gh", *a)

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
    now_aware = datetime.datetime.now(datetime.timezone.utc)
    monday = now_aware - datetime.timedelta(days=now_aware.weekday())
    monday0_aware = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    monday0 = monday0_aware.replace(tzinfo=None)
    now = now_aware.replace(tzinfo=None)
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
    # 真实实现：查近 50 条 git log 是否含行动项的关键词
    try:
        p = subprocess.run(["git", "log", "--oneline", "-50"],
                           capture_output=True, text=True, cwd=str(LOOP_ROOT))
        git_log = p.stdout if p.returncode == 0 else ""
    except Exception:
        git_log = ""
    for key, item in prev_items.items():
        expected_kw = item.get("expected_change_sha_or_keyword", "")
        if not expected_kw:
            evidence.append(f"{key}: 有 — expected 字段为空视为落地")
            landed += 1
            continue
        # 在 git log 中搜关键词（真实检查，非 stub）
        if expected_kw in git_log:
            evidence.append(f"{key}: 有 — git log 命中关键词『{expected_kw}』")
            landed += 1
        else:
            evidence.append(f"{key}: 无 — git log 未命中『{expected_kw}』（需 human-verify 是否落地）")
            missed += 1
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

    # LLM 归因部分：retro 未集成 LLM 调用，明确标注为 human-verify 并生成待办（不假实现）
    # 真实 LLM 归因待 plan-ops sandbox 接口就绪后接入；在此之前不静默挂起，而是产出待办推给人类
    llm_attr = {
        "schema": "llm-attribution-human-verify",
        "adapter": LLM_ATTRIBUTION_ADAPTER,
        "channel": "plan-ops",
        "status": "needs_human",
        "generated_at": now.isoformat(),
        "reason": "retro 未集成 LLM 调用；归因需人类基于下列输入判定，已生成待办不静默挂起",
        "questions": {
            "why_systemic": "human-verify：基于 Q1 的 systemic_callouts，人类判定为什么该类系统性失败会出现（附 journal + CI stats 上下文）",
            "why_preconditions": "human-verify：基于 Q2 的 top_preconditions，人类判定如何从上游拦截",
        },
        "input_summary_keys": ["q1_systemic_failures.systemic_callouts","q2_common_preconditions.top_preconditions"],
        "todo": [
            "人工回答 why_systemic（输入：q1_systemic_failures.systemic_callouts + journal + CI stats）",
            "人工回答 why_preconditions（输入：q2_common_preconditions.top_preconditions）",
        ],
    }
    llm_path = RETRO_OUTBOX / f"llm_attribution_{year}W{week:02d}.json"
    llm_path.write_text(json.dumps(llm_attr, indent=2, ensure_ascii=False))
    print(f"LLM attribution (human-verify, needs_human) → {llm_path}")

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
- LLM 归因（human-verify, needs_human）：`.loop/retro/llm_attribution_{year}W{week:02d}.json`
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

# ==================================================================
# 波次验收：run_wave_acceptance / notify / close_wave_parent（R14-2）
# ==================================================================
# 通知通道选型见 DECISIONS.md ADR-013：GitHub Issue 评论（贴到 Wave 父 issue）/
# 开 Incident issue，作为真实可送达的落地通道，不引入外部 webhook 依赖。

# human-verify 关键词：检查项文本命中即标为需人类验证
_HUMAN_VERIFY_KEYWORDS = (
    "人为", "人类", "人工", "签署", "reviewer", "观察", "需人", "人需",
    "异构", "签署", "7 天", "连续", "无人值守",
)

# 已知可机检的检查模式 → 命令（让现有 Wave 文件的散文检查项也能被机检）
_KNOWN_MACHINE_CHECKS = [
    (re.compile(r"no-fake-green|假绿"), "bash lenses/no-fake-green.sh"),
    (re.compile(r"pytest.*全绿|测试.*全绿|全.*测试"), "python3 -m pytest tests/ -q"),
    (re.compile(r"loop-conformance|副本.*为零|副本为零"), "python3 gates/run_gates.py --gate conformance"),
]

# 机器命令首词白名单：反引号片段以这些开头才视为可执行命令
_CMD_FIRSTWORDS = ("python", "python3", "pytest", "bash", "sh", "gh", "git", "make", "npm", "node")


def _extract_wave_id(wave_file):
    """从文件名或内容提取 wave id（如 WAVE-14）。"""
    name = os.path.basename(str(wave_file))
    m = re.match(r"(WAVE-\d+)", name)
    if m:
        return m.group(1)
    try:
        text = pathlib.Path(wave_file).read_text(encoding="utf-8")
        m = re.search(r"(WAVE-\d+)", text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "WAVE-UNKNOWN"


def _parse_acceptance_section(wave_file):
    """解析 waves/WAVE-XX.md 的『本波次的检查方法』段，返回检查项列表。

    每项：{"id": int, "text": str, "command": str|None}
    command 来源：① 行内反引号包裹的可执行 shell 命令；② 命中 _KNOWN_MACHINE_CHECKS 模式。
    都没有则 command=None（后续按 human-verify 关键词或默认归为 human-verify）。
    """
    text = pathlib.Path(wave_file).read_text(encoding="utf-8")
    # 定位段：从『## 本波次的检查方法』到下一个二级标题或文件结束
    m = re.search(r"##\s*本波次的检查方法[^\n]*\n", text)
    if not m:
        return []
    start = m.end()
    m2 = re.search(r"\n##\s", text[start:])
    end = start + m2.start() if m2 else len(text)
    section = text[start:end]
    # 解析顶格编号项 N. （多行直到下一个编号项）
    items = []
    current = None
    for line in section.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            if current:
                items.append(current)
            current = {"id": int(m.group(1)), "text": m.group(2)}
        elif current and line.strip():
            current["text"] += "\n" + line.strip()
    if current:
        items.append(current)
    # 提取 command
    for it in items:
        it["command"] = _extract_command(it["text"])
    return items


def _extract_command(text):
    """从检查项文本中提取可执行命令。优先反引号命令，其次已知模式。均无则 None。"""
    # ① 反引号里以命令首词开头的片段
    for c in re.findall(r"`([^`]+)`", text):
        first = c.strip().split()[0] if c.strip() else ""
        if first in _CMD_FIRSTWORDS:
            return c.strip()
    # ② 已知可机检模式
    for pat, cmd in _KNOWN_MACHINE_CHECKS:
        if pat.search(text):
            return cmd
    return None


def _classify_check(item):
    """判定检查项类型：machine / human-verify。"""
    text = item.get("text", "")
    if item.get("command"):
        return "machine"
    # 命中 human-verify 关键词 → 需人类验证
    if any(kw in text for kw in _HUMAN_VERIFY_KEYWORDS):
        return "human-verify"
    # 无命令又无 human 关键词 → 保守归为 human-verify（不假机检）
    return "human-verify"


def run_wave_acceptance(wave_file, repo_root="."):
    """执行 Wave 文件声明的『本波次的检查方法』，逐条机检或标 human-verify。

    返回验收报告 dict（同时写入 evidence/wave-acceptance/<wave-id>.json）：
      status: passed | failed | needs_human
      human_verify_violation: bool  # human-verify 占比 > 1/3 即违规
      checks: [{id, description, kind, command, exit_code, stdout, stderr, passed}]
      human_verify_todos: [{id, description, action}]
    规则：
      - 任一 machine 检查失败 → status=failed
      - human-verify 占比 > 1/3 → human_verify_violation=True 且 status=failed（Wave 设计不合规）
      - 全部 machine 通过但有 human-verify 项（且未违规）→ status=needs_human（不能自动关闭）
      - 全部 machine 通过且无 human-verify → status=passed（可自动关闭 Wave 父 issue）
    """
    wave_id = _extract_wave_id(wave_file)
    items = _parse_acceptance_section(wave_file)
    repo_root = str(repo_root)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    checks = []
    machine_passed = 0
    machine_failed = 0
    human_verify_count = 0
    human_verify_todos = []

    for it in items:
        kind = _classify_check(it)
        entry = {
            "id": it["id"],
            "description": it["text"].split("\n", 1)[0][:200],
            "kind": kind,
            "command": it.get("command"),
            "exit_code": None,
            "stdout": None,
            "stderr": None,
            "passed": None,
        }
        if kind == "machine" and it.get("command"):
            try:
                p = subprocess.run(
                    it["command"], shell=True, cwd=repo_root,
                    capture_output=True, text=True, timeout=180,
                )
                entry["exit_code"] = p.returncode
                entry["stdout"] = p.stdout[-4000:] if p.stdout else ""
                entry["stderr"] = p.stderr[-2000:] if p.stderr else ""
                entry["passed"] = (p.returncode == 0)
            except Exception as e:
                entry["exit_code"] = -1
                entry["stderr"] = f"执行异常：{e}"
                entry["passed"] = False
            if entry["passed"]:
                machine_passed += 1
            else:
                machine_failed += 1
        else:
            human_verify_count += 1
            entry["passed"] = None
            human_verify_todos.append({
                "id": it["id"],
                "description": entry["description"],
                "action": f"需人类验证：{entry['description']}",
            })
        checks.append(entry)

    total = len(items)
    # human-verify 占比 > 1/3 即违规（Wave 设计不合规）
    human_verify_violation = (
        total > 0 and human_verify_count > 0 and human_verify_count * 3 > total
    )

    if machine_failed > 0:
        status = "failed"
    elif human_verify_violation:
        status = "failed"
    elif human_verify_count > 0:
        status = "needs_human"
    else:
        status = "passed"

    summary = (
        f"total={total}, machine_passed={machine_passed}, "
        f"machine_failed={machine_failed}, human_verify={human_verify_count}"
    )

    report = {
        "schema": "wave-acceptance-v1",
        "wave_id": wave_id,
        "wave_file": str(wave_file),
        "generated_at": now_iso,
        "status": status,
        "human_verify_violation": human_verify_violation,
        "summary": summary,
        "total_checks": total,
        "machine_checks_passed": machine_passed,
        "machine_checks_failed": machine_failed,
        "human_verify_count": human_verify_count,
        "checks": checks,
        "human_verify_todos": human_verify_todos,
    }

    # 归档进 evidence/wave-acceptance/<wave-id>.json（目录不存在则创建）
    evidence_dir = pathlib.Path(repo_root) / "evidence" / "wave-acceptance"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = evidence_dir / f"{wave_id}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["_report_path"] = str(report_path)

    return report


def _format_notify_message(event_type, payload):
    """按事件类型生成 markdown 通知正文。"""
    wave_id = payload.get("wave_id", "unknown")
    report = payload.get("report") or {}
    extra = payload.get("message", "")
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    header = f"## 波次通知：{event_type}（{wave_id}）\n\n> 生成时间：{now_iso} UTC\n\n"
    if event_type == "wave_passed":
        body = f"波次 **{wave_id}** 验收 **通过**（status=passed）。\n\n{report.get('summary','')}\n\n父 issue 将被自动关闭。"
    elif event_type == "wave_failed":
        body = f"波次 **{wave_id}** 验收 **失败**（status=failed）。\n\n{report.get('summary','')}\n\n失败检查项见 evidence 报告。"
    elif event_type == "needs_human":
        todos = report.get("human_verify_todos", [])
        todo_md = "\n".join(f"- [ ] #{t['id']} {t['action']}" for t in todos) or "- （无）"
        body = (f"波次 **{wave_id}** 验收需人类介入（status=needs_human）。\n\n"
                f"{report.get('summary','')}\n\n"
                f"### 待办清单（human-verify）\n{todo_md}")
    elif event_type == "incident":
        body = f"Incident 升级（{wave_id}）：{extra or '详见 issue 正文'}"
    else:
        body = f"事件 {event_type}（{wave_id}）：{extra}"
    return header + body


def notify(event_type, payload, repo=None):
    """通知通道（R14-2）：走 GitHub Issue 评论 / 开 Incident issue。

    event_type: "wave_passed" | "wave_failed" | "needs_human" | "incident"
    payload: dict，含 wave_id / parent_issue / report / message / title / labels / dry_run
    repo: "org/repo"，默认 REPO

    通道选型（DECISIONS.md ADR-013）：
      - wave_passed / wave_failed / needs_human → gh issue comment 贴到 Wave 父 issue
      - incident → gh issue create 开新 Incident issue（label: incident）

    dry-run：payload["dry_run"]=True 或 env LOOP_NOTIFY_DRY_RUN=1 → 不调 gh，只返回 would-send。
    """
    repo = repo or REPO
    dry_run = bool(payload.get("dry_run")) or E.get("LOOP_NOTIFY_DRY_RUN", "") == "1"
    parent_issue = payload.get("parent_issue")
    wave_id = payload.get("wave_id", "unknown")
    message = _format_notify_message(event_type, payload)

    sent = {
        "event_type": event_type,
        "wave_id": wave_id,
        "channel": "github-issue",
        "dry_run": dry_run,
        "repo": repo,
        "message": message,
    }

    if dry_run:
        sent["would_send"] = True
        sent["target"] = ("issue_create" if event_type == "incident"
                          else f"issue_comment#{parent_issue}")
        return sent

    if event_type == "incident":
        # 开新 Incident issue（真实可送达，不引入外部 webhook）
        title = payload.get("title") or f"Incident: {wave_id} 升级"
        labels = payload.get("labels") or ["incident"]
        cmd = ["gh", "issue", "create", "-R", repo, "--title", title, "--body", message]
        for lb in labels:
            cmd += ["--label", lb]
        p = subprocess.run(cmd, capture_output=True, text=True)
        sent["issue_url"] = p.stdout.strip()
        sent["returncode"] = p.returncode
        sent["stderr"] = p.stderr
        return sent

    # 波次通过/失败/需人类介入 → 评论到 Wave 父 issue
    if not parent_issue:
        sent["error"] = "parent_issue 缺失，无法评论（已生成正文，但未送达）"
        sent["returncode"] = -1
        return sent
    cmd = ["gh", "issue", "comment", str(parent_issue), "-R", repo, "--body", message]
    p = subprocess.run(cmd, capture_output=True, text=True)
    sent["comment_url"] = p.stdout.strip()
    sent["returncode"] = p.returncode
    sent["stderr"] = p.stderr
    return sent


def close_wave_parent(report, parent_issue, repo=None):
    """验收 passed 时关闭 Wave 父 issue（gh issue close）。

    非 passed 或缺 parent_issue 时返回未关闭原因，不抛异常。
    """
    repo = repo or REPO
    if report.get("status") != "passed":
        return {"closed": False, "reason": f"status={report.get('status')} != passed，不关闭"}
    if not parent_issue:
        return {"closed": False, "reason": "parent_issue 缺失，不关闭"}
    p = subprocess.run(["gh", "issue", "close", str(parent_issue), "-R", repo],
                       capture_output=True, text=True)
    return {"closed": p.returncode == 0, "returncode": p.returncode, "stderr": p.stderr}


def find_wave_parent_issue(wave_id, repo=None):
    """按标题搜索 Wave 父 issue 号（open 优先）。找不到返回 None。"""
    repo = repo or REPO
    p = gh("issue", "list", "-R", repo, "--state", "open", "--limit", "50",
           "--search", f"{wave_id} in:title", "--json", "number,title,state")
    try:
        items = json.loads(p.stdout or "[]")
    except Exception:
        return None
    for it in items:
        if wave_id in it.get("title", ""):
            return it.get("number")
    return None


def _wave_acceptance_cli(wave_file, parent_issue=None, repo_root=None, dry_run=False):
    """波次验收编排：run_wave_acceptance → notify → (passed 时) close。

    供 `python conductor/retro.py wave-acceptance <wave_file>` 调用。
    parent_issue 未传则按 wave_id 搜索（dry_run 时不搜索）。
    """
    repo_root = repo_root or str(LOOP_ROOT)
    report = run_wave_acceptance(wave_file, repo_root=repo_root)
    wave_id = report["wave_id"]
    print(f"=== 波次验收 {wave_id} ===")
    print(f"status={report['status']}  {report['summary']}")
    print(f"human_verify_violation={report['human_verify_violation']}")
    print(f"报告归档：{report.get('_report_path')}")

    status = report["status"]
    if status == "passed":
        event_type = "wave_passed"
    elif status == "needs_human":
        event_type = "needs_human"
    else:
        event_type = "wave_failed"

    # 解析父 issue（dry_run 时跳过 gh 搜索）
    if parent_issue is None and not dry_run:
        parent_issue = find_wave_parent_issue(wave_id)
        if parent_issue:
            print(f"找到 Wave 父 issue #{parent_issue}")

    payload = {
        "wave_id": wave_id,
        "parent_issue": parent_issue,
        "report": report,
        "dry_run": dry_run,
    }
    sent = notify(event_type, payload)
    print(f"notify {event_type}: dry_run={sent.get('dry_run')} returncode={sent.get('returncode','-')}")

    # passed 时自动关闭父 issue
    if status == "passed" and parent_issue:
        closed = close_wave_parent(report, parent_issue)
        print(f"close parent #{parent_issue}: {closed}")

    return report

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "wave-acceptance":
        # 波次验收模式：python conductor/retro.py wave-acceptance <wave_file> [--parent-issue N] [--dry-run]
        wave_file = sys.argv[2]
        parent_issue = None
        dry_run = False
        if "--parent-issue" in sys.argv:
            idx = sys.argv.index("--parent-issue")
            parent_issue = sys.argv[idx + 1]
        if "--dry-run" in sys.argv:
            dry_run = True
        _wave_acceptance_cli(wave_file, parent_issue=parent_issue, dry_run=dry_run)
    else:
        main()
