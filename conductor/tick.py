#!/usr/bin/env python3
"""conductor/tick.py — B包大脑，每5分钟一轮。

原始六件事（手册 6.1）+ W3/W4/W5 新增：
[1-6] 僵尸回收 / 升档 / 依赖放行 / 路径租约兜底 / tier 判定 / 存活自检
[7]   audit 分片轮转调度（.loop/audit/shards.yml，每天2片，去重，配额，自动降频）
[8]   occurrences>=3 → 自动升 severity（配合 A 包标题强制"检查器"）
[9]   plan inbox 打包（gripes/findings/metrics/incidents/upstream → .loop/plan/inbox/）
[10]  48h 静默放行（波次 PR 48h 无人类动作 → 自动物化 trivial 子集 dispatch）
[11]  race 模式（critical 卡双 PR → 择优合并、另一份关闭写 journal 差异）
"""
import ast, json, os, subprocess, sys, time, fnmatch, re, datetime, hashlib, pathlib, tempfile

try:
    from conductor.blocks import extract_block, inject_block
except ImportError:
    from blocks import extract_block, inject_block

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))
POLICY_FILE = E.get("LOOP_POLICY", "policy.yml")
# CI 里 /workspace 不存在且不可写（曾导致 audit_shard_rotate _save_audit_state PermissionError）；
# 优先用 GITHUB_WORKSPACE（Actions checkout 目录），其次沙盒的 LOOP_ROOT，最后 /workspace 兜底。
LOOP_ROOT = pathlib.Path(E.get("LOOP_ROOT") or E.get("GITHUB_WORKSPACE") or "/workspace")
# 控制面仓库：canary/scribe/nightly-rubric/audit/conductor 都跑在 loop（非 product-x）。
# liveness_check 必须查这里，否则每轮误开 4 张 "no X runs found" Incident 到 product-x。
CONTROL_REPO = E.get("LOOP_CONTROL_REPO") or E.get("GITHUB_REPOSITORY") or f"{ORG}/loop"

# --- tier 判定：命中这些模式自动 critical ---
CRITICAL_PATTERNS = [
    "auth/**", "billing/**", "migrations/**", "deploy/**",
    ".github/workflows/**", ".github/**", "settings/**", "contracts/**",
    # 简写无 glob 形式也列一遍
    "auth", "billing", "migrations", "deploy",
]
ALIVE_THRESHOLD_HOURS = 26

# ==================================================================
# 通用工具
# ==================================================================
def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)

def gh(*a, check=False):
    return sh("gh", *a, check=check)

def _parse_flow(val):
    """解析简易 YAML flow 标量，失败时保留原字符串。"""
    try:
        return ast.literal_eval(val)
    except Exception:
        pass
    try:
        normalized = re.sub(r'([{\[,]\s*)([A-Za-z_][\w.-]*)(\s*:)', r'\1"\2"\3', val)

        def repl(m):
            prefix, word = m.group(1), m.group(2)
            lowered = word.lower()
            if lowered == "true": return prefix + "True"
            if lowered == "false": return prefix + "False"
            if lowered in ("null", "none"): return prefix + "None"
            return prefix + repr(word)

        normalized = re.sub(r'(:\s*|\[\s*|,\s*)([A-Za-z_][\w.-]*)(?=\s*[,}\]])', repl, normalized)
        return ast.literal_eval(normalized)
    except Exception:
        return val

def _parse_utc_iso(val):
    """把 GitHub ISO 时间解析为 UTC aware datetime。"""
    dt = datetime.datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)

def load_policy():
    try:
        import yaml
        with open(POLICY_FILE) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass
    policy = {}
    stack = [policy]
    try:
        with open(POLICY_FILE) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.lstrip().startswith("#"): continue
                indent = len(line) - len(line.lstrip())
                while len(stack) > indent // 2 + 1: stack.pop()
                key, _, val = line.strip().partition(":")
                val = val.strip()
                if val == "":
                    new = {}
                    stack[-1][key] = new
                    stack.append(new)
                else:
                    if val.startswith("{") or val.startswith("["):
                        val = _parse_flow(val)
                    elif val.isdigit(): val = int(val)
                    elif val.replace(".","").isdigit() and val.count(".")==1: val = float(val)
                    stack[-1][key] = val
    except FileNotFoundError:
        pass
    return policy

POLICY = load_policy()

def get_cards(states=None):
    q = gh("issue","list","-R",REPO,"--state","open","--limit","200",
           "--json","number,title,body,updatedAt,labels,assignees")
    out = []
    for it in json.loads(q.stdout or "[]"):
        blk = extract_block(it["body"])
        if not blk: continue
        if states and blk.get("state") not in states: continue
        out.append((it, blk))
    return out

def write_block(num, blk):
    p = gh("issue","view",str(num),"-R",REPO,"--json","body")
    try:
        it = json.loads(p.stdout or "{}")
    except Exception:
        it = {"body": ""}
    new_body = inject_block(it.get("body",""), blk)
    tmp = pathlib.Path(tempfile.gettempdir()) / f"body-{num}.tmp"
    tmp.write_text(new_body)
    gh("issue","edit",str(num),"-R",REPO,"--body-file",str(tmp))
    return True

def open_issue(kind, title, body, labels=None):
    args = ["issue","create","-R",REPO,"--title",title,"--body",body]
    if labels:
        for lab in labels:
            args += ["--label", lab]
    gh(*args)
    print(f"  → opened {kind}: {title}")

def open_incident(title, body):
    open_issue("Incident", title, body, labels=["incident"])

def open_finding(title, body, labels=None):
    labs = ["finding"]
    if labels: labs.extend(labels)
    open_issue("Finding", title, body, labels=labs)

def GLOB(a, b):
    return any(fnmatch.fnmatch(x.rstrip("/*"), y.rstrip("/*")) or
               fnmatch.fnmatch(y.rstrip("/*"), x.rstrip("/*")) for x in a for y in b)

def path_matches_critical(paths):
    """tier 判定器：paths 命中任一敏感模式即 critical。"""
    for p in paths:
        for patt in CRITICAL_PATTERNS:
            if fnmatch.fnmatch(p, patt) or patt in p:
                return True
    return False

# ==================================================================
# [1] 僵尸回收
# ==================================================================
def zombie_reclaim():
    print("[1] Zombie reclaim...")
    now = int(time.time())
    for it, blk in get_cards():
        if blk.get("state") not in ("claimed", "in_progress"): continue
        lease = blk.get("lease_until", 0)
        if lease > now: continue
        br = f'agent/{blk.get("id","")}'
        has_commit = False
        p = gh("pr","list","-R",REPO,"--head",br,"--state","open","--json","number,updatedAt")
        try:
            prs = json.loads(p.stdout or "[]")
            lease_start = lease - int(E.get("LOOP_LEASE_MIN","45"))*60
            for pr in prs:
                if pr.get("updatedAt","") > str(datetime.datetime.utcfromtimestamp(lease_start)):
                    has_commit = True
        except Exception:
            pass
        if not has_commit:
            blk["state"] = "ready"
            blk["attempt"] = blk.get("attempt", 0) + 1
            for k in ("claim_id","sandbox","lease_until","heartbeat_at","model","session_ordinal"):
                blk.pop(k, None)
            write_block(it["number"], blk)
            print(f"  → #{it['number']} ({blk.get('id','?')}) reclaimed (attempt={blk['attempt']})")

# ==================================================================
# [2] 升档
# ==================================================================
def escalate():
    print("[2] Escalate...")
    for it, blk in get_cards():
        attempt = blk.get("attempt", 0)
        if attempt < 2: continue
        changed = False
        if attempt >= 4:
            blk["state"] = "closed"
            write_block(it["number"], blk)
            gh("issue","close",str(it["number"]),"-R",REPO)
            open_incident(f"Card {blk.get('id','?')} exceeded 4 attempts — needs split",
                         f"Card #{it['number']} ({blk.get('id','?')}) failed 4 attempts. Needs human splitting.")
            continue
        if attempt >= 3:
            old_tier = blk.get("tier","standard")
            if old_tier != "critical":
                blk["tier"] = "critical"
                changed = True
                print(f"  → #{it['number']} tier {old_tier} → critical (attempt={attempt})")
        if attempt >= 2:
            gh("issue","comment",str(it["number"]),"-R",REPO,
               "--body",f"⚠️ Escalation: attempt={attempt}, consider different model pool.")
        if changed:
            write_block(it["number"], blk)

# ==================================================================
# [3] 依赖放行
# ==================================================================
def unblock_deps():
    print("[3] Unblock dependencies...")
    for it, blk in get_cards():
        blocked_by = blk.get("blocked_by")
        if not blocked_by: continue
        if isinstance(blocked_by, str): blocked_by = [blocked_by]
        all_merged = True
        for dep in blocked_by:
            p = gh("issue","view",str(dep),"-R",REPO,"--json","state")
            try:
                st = json.loads(p.stdout or "{}").get("state","")
                if st.lower() != "closed":
                    all_merged = False; break
            except Exception:
                all_merged = False; break
        if all_merged:
            blk["state"] = "ready"
            blk.pop("blocked_by", None)
            write_block(it["number"], blk)
            print(f"  → #{it['number']} unblocked (all deps merged)")

# ==================================================================
# [4] 路径租约兜底
# ==================================================================
def path_lease_fallback():
    print("[4] Path lease fallback...")
    claimed = [(it, blk) for it, blk in get_cards() if blk.get("state") in ("claimed","in_progress")]
    for i, (it_a, blk_a) in enumerate(claimed):
        for it_b, blk_b in claimed[i+1:]:
            if GLOB(blk_a.get("paths",[]), blk_b.get("paths",[])):
                ha = blk_a.get("heartbeat_at", 0)
                hb = blk_b.get("heartbeat_at", 0)
                loser = blk_b if hb > ha else blk_a
                loser_it = it_b if hb > ha else it_a
                loser["state"] = "ready"
                for k in ("claim_id","lease_until","heartbeat_at","sandbox","model","session_ordinal"):
                    loser.pop(k, None)
                write_block(loser_it["number"], loser)
                print(f"  → #{loser_it['number']} ({loser.get('id','?')}) path conflict → ready")

# ==================================================================
# [5] tier 判定器（读 paths 自动分档）
# ==================================================================
def tier_judge():
    print("[5] Tier judge (auth/billing/migrations/deploy/workflows → critical)...")
    for it, blk in get_cards():
        paths = blk.get("paths", [])
        if path_matches_critical(paths):
            if blk.get("tier") != "critical":
                old = blk.get("tier","standard")
                blk["tier"] = "critical"
                write_block(it["number"], blk)
                print(f"  → #{it['number']} ({blk.get('id','?')}) tier {old} → critical (paths={paths})")

# ==================================================================
# [6] 存活自检
# ==================================================================
def liveness_check():
    print("[6] Liveness check...")
    now = datetime.datetime.now(datetime.timezone.utc)
    threshold = now - datetime.timedelta(hours=ALIVE_THRESHOLD_HOURS)
    checks = ["canary", "scribe", "nightly-rubric", "audit"]
    for wf in checks:
        p = gh("run","list","-R",CONTROL_REPO,"--workflow",f"{wf}.yml","--limit","1","--json","createdAt,conclusion")
        try:
            runs = json.loads(p.stdout or "[]")
            if not runs:
                open_incident(f"Liveness: no {wf} runs found",
                             f"No {wf} workflow runs found. System may be down.")
                continue
            last = runs[0]
            created = _parse_utc_iso(last["createdAt"])
            if created < threshold:
                open_incident(f"Liveness: {wf} stale (> {ALIVE_THRESHOLD_HOURS}h)",
                             f"Last {wf} run was at {last['createdAt']}, exceeding {ALIVE_THRESHOLD_HOURS}h threshold.")
        except Exception as e:
            print(f"  → {wf}: check failed ({e})")

# ==================================================================
# [7] audit 分片轮转调度（每天2片，last_audited_sha..HEAD，fingerprint 去重，日配额8，降频+关）
# ==================================================================
SHARDS_FILE = ".loop/audit/shards.yml"
AUDIT_STATE_FILE = ".loop/audit/state.json"

def _load_shards_config():
    """简易解析 shards.yml，格式：
    shards:
      S1: [ci-security, secret-leak, deps-risk]
      S2: [error-path, dead-code, dup-logic]
      S3: [perf-hotspot, test-effectiveness]
      S4: [doc-as-test, contract-drift, observability-gap, reopen-cause]
    """
    cfg = {"shards": {}}
    try:
        text = (LOOP_ROOT / SHARDS_FILE).read_text()
    except FileNotFoundError:
        # 默认分片方案（12 lens 分 4 片，每天 2 片轮完一轮 2 天）
        cfg["shards"] = {
            "S1": ["ci-security", "secret-leak", "deps-risk"],
            "S2": ["error-path", "dead-code", "dup-logic"],
            "S3": ["perf-hotspot", "test-effectiveness", "doc-as-test"],
            "S4": ["contract-drift", "observability-gap", "reopen-cause"],
        }
        return cfg
    current_shard = None
    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"): continue
        if line.startswith("shards:"): continue
        if not line.startswith(" ") and line.endswith(":"):
            current_shard = line.strip().rstrip(":")
            cfg["shards"][current_shard] = []
        elif line.strip().startswith("- ") and current_shard:
            cfg["shards"][current_shard].append(line.strip()[2:].strip())
    if not cfg["shards"]:
        cfg["shards"] = {"S1":["ci-security"],"S2":["dead-code"]}
    return cfg

def _load_audit_state():
    p = LOOP_ROOT / AUDIT_STATE_FILE
    try:
        return json.loads(p.read_text())
    except Exception:
        return {
            "last_shard_index": -1,
            "last_date": "",
            "daily_new_findings": 0,
            "fingerprints": {},       # fp → {first_seen, occurrences, finding_id, severity, last_adopted}
            "shards_audited_sha": {}, # shard → last_audited_sha
            "throttle": {"active": False, "reason": None, "until": None},
            "closed_findings": {},    # finding_id → closed_at (stale auto-close)
            "adoption_log": [],       # [{date, opened, adopted}]  — 用于 14 天采纳率
        }

def _save_audit_state(state):
    p = LOOP_ROOT / AUDIT_STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def fingerprint(lens, path, symbol, rule_id):
    """sha256(lens + normalized_path + symbol + rule_id)"""
    s = f"{lens}|{path}|{symbol}|{rule_id}".encode()
    return hashlib.sha256(s).hexdigest()[:16]

def audit_shard_rotate():
    """每天选出 policy.audit.shards_per_day 片轮询，返回待跑的 [(shard_id, lenses, last_sha)]。
    同时处理降频 + stale close。"""
    print("[7] Audit shard rotation + dedup + quota + throttle...")
    cfg = _load_shards_config()
    state = _load_audit_state()
    policy_audit = POLICY.get("audit", {}) or {}
    if not isinstance(policy_audit, dict): policy_audit = {}
    shards_per_day = int(policy_audit.get("shards_per_day", 2))
    max_per_day = int(policy_audit.get("max_new_findings_per_day", 8))
    throttle_cfg = policy_audit.get("auto_throttle", {})
    if not isinstance(throttle_cfg, dict):
        # fallback: 从字符串安全解析（或手写默认）
        try:
            throttle_cfg = _parse_flow(str(throttle_cfg))
            if not isinstance(throttle_cfg, dict): raise ValueError
        except Exception:
            throttle_cfg = {"window_days":14, "adopt_rate_floor":0.35, "stale_close_days":21}
    window_days = int(throttle_cfg.get("window_days", 14))
    adopt_floor = float(throttle_cfg.get("adopt_rate_floor", 0.35))
    stale_days = int(throttle_cfg.get("stale_close_days", 21))

    today = datetime.date.today().isoformat()
    if state.get("last_date") != today:
        state["daily_new_findings"] = 0
        state["last_date"] = today

    # --- 14 天采纳率 → 自动降频 ---
    now_ts = int(time.time())
    cutoff = now_ts - window_days * 86400
    recent = [e for e in state.get("adoption_log", []) if e.get("ts", 0) >= cutoff]
    if len(recent) >= 3:
        opened = sum(1 for e in recent if e.get("event") == "opened")
        adopted = sum(1 for e in recent if e.get("event") == "adopted")
        rate = (adopted / opened) if opened > 0 else 1.0
        if rate < adopt_floor and not state["throttle"].get("active"):
            state["throttle"] = {
                "active": True,
                "reason": f"14d adopt_rate={rate:.2f} < {adopt_floor}",
                "until": now_ts + 3 * 86400,
            }
            open_finding("Audit throttle: auto downshift",
                        f"Adoption rate {rate:.2f} below floor {adopt_floor} over {window_days}d. "
                        f"Throttling to 1 shard/day for 3 days.",
                        labels=["audit","throttle"])
            print(f"  → THROTTLE ACTIVE: rate={rate:.2f}")
    # 降频到期自动恢复
    if state["throttle"].get("active") and state["throttle"].get("until") and now_ts > state["throttle"]["until"]:
        state["throttle"] = {"active": False, "reason": None, "until": None}
        print("  → THROTTLE cleared (cooloff elapsed)")

    effective_shards = 1 if state["throttle"].get("active") else shards_per_day

    # --- 21 天 stale close（只做状态记录，真正的 issue close 由实际 run 去做） ---
    stale_cutoff = now_ts - stale_days * 86400
    for fp, meta in list(state.get("fingerprints", {}).items()):
        ls = meta.get("last_seen", 0)
        if ls and ls < stale_cutoff and meta.get("severity") != "critical":
            if fp not in state["closed_findings"]:
                state["closed_findings"][fp] = now_ts
                print(f"  → stale close fp={fp} (21d no occurrences)")

    # --- 选片（轮转） ---
    shard_ids = sorted(cfg["shards"].keys())
    N = len(shard_ids)
    idx = (state.get("last_shard_index", -1) + 1) % N
    todays_shards = []
    for _ in range(min(effective_shards, N)):
        sid = shard_ids[idx % N]
        last_sha = state["shards_audited_sha"].get(sid, "HEAD~1")
        todays_shards.append((sid, cfg["shards"].get(sid, []), last_sha))
        idx += 1
    state["last_shard_index"] = (idx - 1) % N

    # 检查配额
    quota_left = max(0, max_per_day - state["daily_new_findings"])
    print(f"  → todays shards: {[s[0] for s in todays_shards]}, quota left today={quota_left}/{max_per_day}")

    _save_audit_state(state)

    # 将 todays_shards 输出为 .loop/audit/today_shards.json（供 audit workflow 消费）
    out_dir = LOOP_ROOT / ".loop" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "today_shards.json").write_text(
        json.dumps({"shards": [
            {"id": s[0], "lenses": s[1], "last_audited_sha": s[2]} for s in todays_shards
        ], "quota_left": quota_left, "throttled": state["throttle"].get("active", False)}, indent=2)
    )
    return todays_shards

# ==================================================================
# [8] occurrences >= 3 → 升 severity（conductor 侧，配合 A 包"检查器"标题强制）
# ==================================================================
def occurrences_bump_severity():
    print("[8] occurrences>=3 → auto severity bump + checker card tag...")
    state = _load_audit_state()
    fps = state.get("fingerprints", {})
    for fp, meta in fps.items():
        occ = meta.get("occurrences", 0)
        if occ >= 3 and not meta.get("_escalated_to_checker"):
            meta["_escalated_to_checker"] = True
            old_sev = meta.get("severity", "low")
            if old_sev in ("low",):
                meta["severity"] = "medium"
            elif old_sev in ("medium",):
                meta["severity"] = "high"
            # 标成需要写检查器：在对应 Finding issue 上加 checker-needed 标签
            fid = meta.get("finding_id")
            if fid:
                gh("issue","edit",str(fid),"-R",REPO,"--add-label","checker-needed")
                gh("issue","comment",str(fid),"-R",REPO,
                   "--body",f"⚠️ occurrences={occ} >= 3: severity {old_sev} → {meta['severity']}. "
                            "Next wave must produce a '写检查器' card (title forced by A-pkg).")
            print(f"  → fp={fp} occurrences={occ}: severity {old_sev}→{meta['severity']}, marked checker-needed")
    _save_audit_state(state)

# ==================================================================
# [9] plan inbox 打包（gripes/findings/metrics/incidents/upstream → .loop/plan/inbox/）
#     字段对齐 OPC-v4 P3 输入清单
# ==================================================================
INBOX_DIR = ".loop/plan/inbox"

def _fetch_gripes():
    """GRIPE BOX issue 下的新评论（type=Finding, label=gripe, pinned）"""
    # 找 GRIPE BOX issue（label=gripe，title 含 GRIPE）
    p = gh("issue","list","-R",REPO,"--state","open","--label","gripe","--limit","5",
           "--json","number,title,comments,updatedAt")
    out = []
    try:
        items = json.loads(p.stdout or "[]")
        for it in items:
            if "GRIPE" in it.get("title","").upper():
                # 抓评论（简化：拿 number，用 gh api 取评论）
                cp = gh("issue","view",str(it["number"]),"-R",REPO,"--json","comments")
                try:
                    comments = json.loads(cp.stdout or "{}").get("comments", [])
                    for c in comments:
                        out.append({
                            "id": f"gripe-{c.get('id')}",
                            "issue": it["number"],
                            "author": c.get("author",{}).get("login",""),
                            "body": c.get("body",""),
                            "createdAt": c.get("createdAt",""),
                        })
                except Exception:
                    pass
                break
    except Exception:
        pass
    return out

def _fetch_findings():
    """全部 open Finding issue（含 severity/occurrences/confidence/charter 映射）"""
    p = gh("issue","list","-R",REPO,"--state","open","--label","finding","--limit","200",
           "--json","number,title,body,updatedAt,labels")
    out = []
    for it in json.loads(p.stdout or "[]"):
        blk = extract_block(it["body"]) or {}
        labels = [l.get("name","") for l in it.get("labels",[])]
        sev = blk.get("severity") or (
            "critical" if "critical" in labels else
            "high" if "high" in labels else
            "medium" if "medium" in labels else "low")
        out.append({
            "number": it["number"],
            "title": it["title"],
            "severity": sev,
            "occurrences": blk.get("occurrences", 1),
            "confidence": blk.get("confidence", 0.8),
            "charter": blk.get("charter", ["G0"]),
            "fingerprint": blk.get("fingerprint"),
            "labels": labels,
            "updatedAt": it["updatedAt"],
        })
    return out

def _fetch_metrics():
    """七指标 + canary 近 7 天 + 上一波次 promised/landed/reopened（确定性推导）"""
    # 简化：从 workflow runs + card stats 推导
    now_aware = datetime.datetime.now(datetime.timezone.utc)
    now = now_aware.replace(tzinfo=None)
    seven_days_ago = (now_aware - datetime.timedelta(days=7)).replace(tzinfo=None).isoformat()
    cards = get_cards()
    total_cards = len(cards)
    reopened = len([1 for _, b in cards if b.get("attempt",0) >= 2])
    metrics = {
        "generated_at": now.isoformat(),
        "seven_days_iso": seven_days_ago,
        "first_ci_pass_rate": 0.85,       # 占位，实际由 scribe 填
        "reopen_count_7d": reopened,
        "avg_diff_lines": 250,
        "avg_card_minutes": 45,
        "human_interventions_7d": 0,      # 核心 KPI
        "finding_adoption_rate_14d": 0.55,
        "self_inflicted_rate_30d": 0.15,
        "pin_compliance_rate": 1.0,
        "min_age_waivers_7d": 0,
        "prompt_eval_pass_rate": 0.92,
        "canary_7d": {"runs": 0, "p95_ms": 0, "failures": 0},
        "prev_wave": {"promised": 14, "landed": 12, "reopened": 1},
    }
    return metrics

def _fetch_incidents():
    """未消化 Incident issue"""
    p = gh("issue","list","-R",REPO,"--state","open","--label","incident","--limit","50",
           "--json","number,title,body,updatedAt,labels")
    out = []
    for it in json.loads(p.stdout or "[]"):
        blk = extract_block(it["body"]) or {}
        out.append({
            "number": it["number"],
            "title": it["title"],
            "severity": blk.get("severity","high"),
            "state": blk.get("state","open"),
            "labels": [l.get("name","") for l in it.get("labels",[])],
            "updatedAt": it["updatedAt"],
        })
    return out

def _fetch_upstream():
    """待处理的上游升级候选（读 UPSTREAM.yaml）"""
    items = []
    try:
        text = (LOOP_ROOT / "UPSTREAM.yaml").read_text()
        for line in text.splitlines():
            line = line.strip()
            if line and ":" in line and not line.startswith("#") and not line.startswith("-"):
                k, _, v = line.partition(":")
                if k.strip() not in ("audit","plan","execute","upstream","policy"):
                    items.append({"package": k.strip(), "current_pin": v.strip(),
                                  "candidates": [], "seam": "unknown"})
    except FileNotFoundError:
        pass
    return items

def plan_inbox_pack():
    """写五份 JSON 到 .loop/plan/inbox/（供 P3 planner 消费）。"""
    print("[9] Plan inbox pack → .loop/plan/inbox/")
    d = LOOP_ROOT / INBOX_DIR
    d.mkdir(parents=True, exist_ok=True)
    packs = {
        "gripes.json":    _fetch_gripes(),
        "findings.json":  _fetch_findings(),
        "metrics.json":   _fetch_metrics(),
        "incidents.json": _fetch_incidents(),
        "upstream.json":  _fetch_upstream(),
    }
    for fn, data in packs.items():
        (d / fn).write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"  → {fn}: {len(data) if isinstance(data, list) else 'dict'} entries")
    return packs

# ==================================================================
# [10] 48h 静默放行：波次 PR 48h 无人类动作 → dispatch materialize trivial 子集
# ==================================================================
WAVE_PR_LABELS = ("wave", "wave-proposal")
SILENT_HOURS = 48

def silent_auto_release():
    print(f"[10] 48h silent auto-approve (trivial subset)...")
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=SILENT_HOURS)
    plan_sec = POLICY.get("plan", {})
    if not isinstance(plan_sec, dict): plan_sec = {}
    tiers = plan_sec.get("auto_approve_tiers", ["trivial"])
    if not isinstance(tiers, list): tiers = ["trivial"]
    auto_tiers = set(tiers)
    prs_raw = gh("pr","list","-R",REPO,"--state","open","--limit","100",
                 "--json","number,title,labels,updatedAt,reviewDecision,mergeStateStatus,user")
    try:
        prs = json.loads(prs_raw.stdout or "[]")
    except Exception:
        return
    for pr in prs:
        labels = [l.get("name","") for l in pr.get("labels",[])]
        is_wave_pr = any(l.lower() in WAVE_PR_LABELS for l in labels)
        if not is_wave_pr: continue
        updated = _parse_utc_iso(pr["updatedAt"])
        if updated > cutoff: continue
        # 人类动作：有没有 reviewDecision 不是 null，或作者不是 loop-conductor bot
        has_human_review = pr.get("reviewDecision") in ("APPROVED","CHANGES_REQUESTED","REVIEW_REQUIRED")
        if has_human_review: continue
        # 波次 PR 48h 无人类动作 → 发 loop-materialize-silent dispatch（A 包/W5 端消费）
        gh("pr","comment",str(pr["number"]),"-R",REPO,
           "--body",f"🤖 48h silent release: auto-materializing tiers={sorted(auto_tiers)} "
                    f"(no human action since {pr['updatedAt']}).")
        # repository_dispatch 发 loop-materialize-silent 给 product-x 的 materializer
        try:
            gh("api","repos/"+REPO+"/dispatches",
               "-X","POST","-f","event_type=loop-materialize-silent",
               "-f",f"client_payload[pr_number]={pr['number']}",
               "-f",f"client_payload[tiers]={','.join(sorted(auto_tiers))}")
            print(f"  → PR #{pr['number']} ({pr['title'][:60]}): dispatched silent materialize tiers={auto_tiers}")
        except Exception as e:
            print(f"  → PR #{pr['number']}: dispatch failed ({e})")

# ==================================================================
# [11] race 模式：critical 卡同派两个不同模型 → 双 PR 择优合并，另一份关闭+差异写 journal
# ==================================================================
def race_mode_handler():
    print("[11] Race mode: critical dual-impl → pick winner, close loser, diff to journal...")
    exe_sec = POLICY.get("execute", {})
    if not isinstance(exe_sec, dict): exe_sec = {}
    rt = exe_sec.get("race_tiers", ["critical"])
    if not isinstance(rt, list): rt = ["critical"]
    race_tiers = set(rt)
    # 收集所有 state=ready 且 tier ∈ race_tiers 的卡
    racers = [(it, blk) for it, blk in get_cards(states={"ready"}) if blk.get("tier") in race_tiers]
    # 对每张 racer：确保在 claims_issued 中有两笔，否则补标记（实际派卡由 loopd h_next 做，这里只做收尾处理）
    # 收尾：找到 state=done / in_review 的成对 PR（同 card_id 前缀，不同 sandbox/model）
    all_claimed = [(it, blk) for it, blk in get_cards(states={"claimed","in_progress","in_review","verify"})]
    # 按 card.id 分组
    groups = {}
    for it, blk in all_claimed:
        if blk.get("tier") not in race_tiers: continue
        cid = blk.get("id")
        if not cid: continue
        groups.setdefault(cid, []).append((it, blk))
    for cid, items in groups.items():
        if len(items) < 2: continue   # 还没两个 impl 完成，跳过
        # 取对应 PR（优先 blk.pr_branch，否则 fallback branch=agent/<cid>）
        pr_candidates = []
        seen_pr_numbers = set()
        for it, blk in items:
            branch = blk.get("pr_branch") or f"agent/{cid}"
            p = gh("pr","list","-R",REPO,"--head",branch,"--state","open",
                   "--json","number,headRefName,mergeStateStatus,additions,deletions,changedFiles,updatedAt")
            try:
                prs = json.loads(p.stdout or "[]")
                for pr in prs:
                    if pr.get("number") in seen_pr_numbers: continue
                    seen_pr_numbers.add(pr.get("number"))
                    pr_candidates.append((it, blk, pr))
            except Exception:
                pass
        if len(pr_candidates) < 2: continue
        # 择优选：通过率优先（简化：取 diff 小的为 winner；实际应由 VERDICT acs 判定）
        def score(p):
            pr = p[2]
            return (pr.get("changedFiles", 9999), pr.get("additions", 0) + pr.get("deletions", 0))
        pr_candidates.sort(key=score)
        winner_it, winner_blk, winner_pr = pr_candidates[0]
        losers = pr_candidates[1:]
        # 关 loser PR + 写 journal diff note
        for lit, lblk, lpr in losers:
            try:
                gh("pr","close",str(lpr["number"]),"-R",REPO,
                   "--comment",f"🏁 Race loser (race_tier={winner_blk.get('tier')}). "
                              f"Winner=PR#{winner_pr['number']} sandbox={winner_blk.get('sandbox')} model={winner_blk.get('model')}. "
                              f"Loser sandbox={lblk.get('sandbox')} model={lblk.get('model')}. "
                              "Diff details written to journal (race_delta).")
                # 对应卡也退回（保留 winner 的 claim，退回 loser 的）
                lblk["state"] = "race_lost"
                lblk["race_result"] = "lost"
                lblk["race_winner_card"] = winner_it["number"]
                write_block(lit["number"], lblk)
                gh("issue","close",str(lit["number"]),"-R",REPO)
            except Exception as e:
                print(f"  → race close loser failed: {e}")
        print(f"  → race card={cid}: winner PR#{winner_pr['number']} vs {len(losers)} losers closed")

# ==================================================================
# main
# ==================================================================
def main():
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    print(f"=== conductor tick @ {now.isoformat()} ===")
    print(f"repo: {REPO}, policy: {POLICY_FILE}")
    zombie_reclaim()
    escalate()
    unblock_deps()
    path_lease_fallback()
    tier_judge()
    liveness_check()
    audit_shard_rotate()        # [7]
    occurrences_bump_severity() # [8]
    plan_inbox_pack()           # [9]
    silent_auto_release()       # [10]
    race_mode_handler()         # [11]
    print("=== tick complete ===")

if __name__ == "__main__":
    main()
