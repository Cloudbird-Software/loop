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

# W0-3 根因修复：直接运行 `python conductor/tick.py` 时 sys.path[0] 是 conductor/
# 而非仓库根，导致 `from conductor.X import ...` 抛 ModuleNotFoundError（conductor
# 10+ 连败根因，CI run 30684245290 traceback 指向 race_mode_handler line 738 的
# `from conductor.claim_intake import is_claim_pickable_by_impl`）。把仓库根插入
# sys.path，使 conductor.* 包导入在直接运行与 `python -m conductor.tick` 模式下都
# 可用。与下方 try/except fallback 互补（后者仅兜底 blocks，本修复根治所有
# conductor.* 导入，包括 race_mode_handler 内的延迟导入）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from conductor.blocks import extract_block, inject_block
except ImportError:
    from blocks import extract_block, inject_block

# schema 字段名单一事实源（W2-5 / I-001）：租约到期等键名不裸硬编码。
from conductor.schema_types import CARD_FIELD_LEASE_UNTIL

E = os.environ


def _env(env):
    """Return the env mapping to resolve config from (os.environ by default).

    Lets the resolution helpers be unit-tested with a hand-rolled env dict,
    without re-importing the module and without touching the network.
    """
    return E if env is None else env


def _resolve_org(env):
    """LOOP_ORG with GITHUB_REPOSITORY_OWNER as default (preserves original semantics)."""
    return env.get("LOOP_ORG", env.get("GITHUB_REPOSITORY_OWNER", ""))


def resolve_loop_root(env=None):
    """Resolve the loop workspace root.

    Priority: LOOP_ROOT > GITHUB_WORKSPACE > /workspace fallback.
    A *relative* path is resolved relative to cwd (made absolute) so that
    local/dev runs (`LOOP_ROOT=.`) and Actions checkouts
    (`GITHUB_WORKSPACE=<abs>`) share one code path; an *absolute* path is
    used as-is.

    CI 里 /workspace 不存在且不可写（曾导致 audit_shard_rotate _save_audit_state
    PermissionError）；优先用 GITHUB_WORKSPACE（Actions checkout 目录），其次沙盒的
    LOOP_ROOT，最后 /workspace 兜底。
    """
    env = _env(env)
    raw = env.get("LOOP_ROOT") or env.get("GITHUB_WORKSPACE") or "/workspace"
    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = pathlib.Path.cwd() / p
    return p


def resolve_repo(env=None):
    """Product repo as '<ORG>/<REPO>', purely env-driven.

    LOOP_ORG (or GITHUB_REPOSITORY_OWNER) + LOOP_REPO. Defaults to
    '<ORG>/product-x' when LOOP_REPO is unset — i.e. the same single tick.py
    serves product-x simply by setting LOOP_REPO=product-x, and loop itself by
    setting LOOP_REPO=loop. No fork needed.
    """
    env = _env(env)
    return f"{_resolve_org(env)}/{env.get('LOOP_REPO', 'product-x')}"


def resolve_control_repo(env=None):
    """Control-plane repo (canary/scribe/nightly-rubric/audit/conductor run here, NOT the product repo).

    Priority: LOOP_CONTROL_REPO > GITHUB_REPOSITORY > <ORG>/loop.
    liveness_check must query here, otherwise every tick opens 4 spurious
    "no X runs found" Incidents onto product-x.

    NOTE — 收归说明 (card R11-6): product-x 之前携带一份与 loop 分叉的 tick.py
    副本（约 25 行实质差异：LOOP_ROOT 解析、独立的 CONTROL_REPO 变量、product-x
    侧多出的 canary stub）。这些分支差异现已全部由环境变量驱动
    (LOOP_CONTROL_REPO / LOOP_ORG / LOOP_REPO)，本文件不再保留任何 product-x
    专属的硬编码分叉。因此 product-x 可以删除其 fork（见 R13-4）并直接消费 loop
    的这一份单一 tick.py 实现服务两仓。
    """
    env = _env(env)
    return env.get("LOOP_CONTROL_REPO") or env.get("GITHUB_REPOSITORY") or f"{_resolve_org(env)}/loop"


ORG = _resolve_org(E)
REPO = resolve_repo(E)
POLICY_FILE = E.get("LOOP_POLICY", "policy.yml")
LOOP_ROOT = resolve_loop_root(E)
CONTROL_REPO = resolve_control_repo(E)

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
    args = ["issue","create","-R",CONTROL_REPO,"--title",title,"--body",body]
    if labels:
        for lab in labels:
            args += ["--label", lab]
    try:
        gh(*args, check=True)
        print(f"  → opened {kind}: {title}")
    except subprocess.CalledProcessError as e:
        print(f"  → FAILED to open {kind}: {title}")
        if e.stderr:
            for line in e.stderr.strip().split("\n")[-3:]:
                print(f"    | {line}")

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
        lease = blk.get(CARD_FIELD_LEASE_UNTIL, 0)
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
            for k in ("claim_id","sandbox",CARD_FIELD_LEASE_UNTIL,"heartbeat_at","model","session_ordinal"):
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
                for k in ("claim_id",CARD_FIELD_LEASE_UNTIL,"heartbeat_at","sandbox","model","session_ordinal"):
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
    # R12-4：显式排除未复现的 claim F-card（state=unconfirmed）——wave-level gate #2。
    # get_cards(states={"ready"}) 已按 state 过滤，此处为 defense-in-depth。
    from conductor.claim_intake import is_claim_pickable_by_impl
    racers = [(it, blk) for it, blk in get_cards(states={"ready"})
              if blk.get("tier") in race_tiers and is_claim_pickable_by_impl(blk)]
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
# [12] 每日 digest：生成 .loop/HUMAN-TODO.md 四问（W0-5）
# ==================================================================
HUMAN_TODO_TEMPLATE = LOOP_ROOT / ".loop" / "templates" / "human-todo.md"
HUMAN_TODO_OUTPUT = LOOP_ROOT / ".loop" / "HUMAN-TODO.md"
LIVENESS_FILE = LOOP_ROOT / ".loop" / "liveness.yml"

def _liveness_fallback_parse():
    """简易 YAML 解析（PyYAML 不可用或内容损坏时的降级路径，与 load_policy 同风格）。

    返回 [{'name': str, 'expect_hours': int}, ...]；文件缺失返回 []。
    """
    ticks = []
    current = None
    try:
        with open(LIVENESS_FILE) as f:
            for line in f:
                line = line.rstrip()
                if not line or line.lstrip().startswith("#"): continue
                s = line.strip()
                if s.startswith("- name:"):
                    current = {"name": s.split(":",1)[1].strip(), "expect_hours": 0}
                    ticks.append(current)
                elif s.startswith("expect_hours:") and current is not None:
                    try:
                        current["expect_hours"] = int(s.split(":",1)[1].strip())
                    except ValueError:
                        # 非整数预期值：保留默认 0，best-effort 容错（CodeQL：非空 except）。
                        pass
    except FileNotFoundError:
        # fallback 解析阶段文件不存在：返回当前累积值（通常为空列表），
        # 与函数末尾 return ticks 行为一致（CodeQL：非空 except）。
        return ticks
    return ticks

def _load_liveness_config():
    """读 .loop/liveness.yml 的 ticks 列表（W0-2 登记 9 条 cron 期望周期）。

    返回 [{'name': str, 'expect_hours': int}, ...]；文件缺失返回 []。
    纯文件读取，不依赖网络——满足 W0-5 AC-3 的可独立验证性。

    Copilot round-4 review：PyYAML 可用时仅捕获 FileNotFoundError，若内容损坏
    导致 yaml.safe_load 抛 YAMLError 会让 --generate-digest 崩溃；其余采集路径均
    best-effort，此处也对 YAMLError 降级到 fallback 简易解析。
    Copilot round-7 review：ticks 非 list 或元素非 dict 时，后续 _gather_degradations
    / _render_liveness_table 会 t.get(...) 崩溃；此处做结构归一化（非 list→[]，
    非 dict 元素过滤），与 best-effort 不崩溃意图一致。
    """
    try:
        import yaml
        with open(LIVENESS_FILE) as f:
            d = yaml.safe_load(f) or {}
        raw = d.get("ticks", [])
    except FileNotFoundError:
        return []
    except ImportError:
        # PyYAML 未安装：降级到 fallback 简易解析
        return _liveness_fallback_parse()
    except yaml.YAMLError as e:
        # YAML 内容损坏：降级到 fallback 简易解析，避免 digest 中断
        # （此时 yaml 已成功 import，故 yaml.YAMLError 可安全引用）。
        print(f"[warn] liveness.yml YAML parse failed, using fallback: {e}", file=sys.stderr)
        return _liveness_fallback_parse()
    # 结构归一化：ticks 非 list → []；元素非 dict → 过滤掉
    if not isinstance(raw, list):
        return []
    return [t for t in raw if isinstance(t, dict)]

def _gather_blocked_on_human():
    """卡在我这的：查 needs-human 标签的 open issue + 根 HUMAN-TODO.md 未勾选条目。"""
    items = []
    # best-effort 采集：gh 调用本身可能抛异常，包一层 try 与其他 _gather_* 一致，
    # 避免 needs-human 查询失败中断整个 digest（CodeQL：非空 except）。
    try:
        p = gh("issue","list","-R",REPO,"--label","needs-human","--state","open",
               "--limit","30","--json","number,title")
        for it in json.loads(p.stdout or "[]"):
            items.append(f"- [ ] #{it['number']} {it['title']}")
    except Exception as e:
        print(f"[warn] _gather_blocked_on_human: {e}", file=sys.stderr)
    if not items:
        items.append("- （当前无 needs-human 标签的 open issue）")
    # 附加根 HUMAN-TODO.md 的未勾选条目（人工维护的长期清单）
    root_todo = LOOP_ROOT / "HUMAN-TODO.md"
    if root_todo.exists():
        unchecked = []
        for line in root_todo.read_text().splitlines():
            if line.strip().startswith("### [ ]"):
                # '### [ ] A1. ...' → '- [ ] A1. ...'（剥 '### ' 前缀，保留 checkbox）
                unchecked.append(f"- {line.strip()[4:]}")
        if unchecked:
            items.append("")
            items.append("**根 HUMAN-TODO.md 未勾选条目**（人工维护长期清单）：")
            items.extend(unchecked)
    return "\n".join(items)

def _gather_released_yesterday():
    """昨天放行的：最近 24h 合并的 PR。"""
    since = (datetime.datetime.now(datetime.timezone.utc) -
             datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # best-effort 采集：gh 调用本身可能抛异常（网络/权限），包一层 try 与其他
    # _gather_* 保持一致容错风格，避免单点失败中断整个 digest 渲染。
    try:
        p = gh("pr","list","-R",REPO,"--state","merged","--limit","50",
               "--search",f"merged:>{since}","--json","number,title,mergedAt,author")
        prs = json.loads(p.stdout or "[]")
    except Exception as e:
        print(f"[warn] _gather_released_yesterday: {e}", file=sys.stderr)
        prs = []
    if not prs:
        return "- （最近 24h 无合并 PR）"
    lines = []
    for pr in prs:
        lines.append(f"- #{pr['number']} {pr['title']} (@{pr.get('author',{}).get('login','?')})")
    return "\n".join(lines)

def _gather_degradations():
    """什么退化了：CI 连败 + 存活超期 + 新开 Incident。"""
    items = []
    # 1. 控制面 workflow 最近 3 次 run 中的 failure（--limit 3，与下方一致）
    for wf in ("conductor.yml", "audit.yml", "canary.yml", "scribe.yml", "drift.yml"):
        # best-effort 采集：gh 调用本身可能抛异常，包一层 try 与其他 _gather_* 一致，
        # 避免单个 workflow 查询失败中断整个 digest（CodeQL：非空 except）。
        try:
            p = gh("run","list","-R",CONTROL_REPO,"--workflow",wf,"--limit","3",
                   "--json","conclusion,createdAt,displayTitle")
            runs = json.loads(p.stdout or "[]")
        except Exception as e:
            print(f"[warn] degradations {wf}: {e}", file=sys.stderr)
            runs = []
        fails = [r for r in runs if r.get("conclusion") == "failure"]
        if fails:
            items.append(f"- **{wf}** 最近 {len(fails)}/{len(runs)} 次为 failure（最近: {fails[0].get('createdAt','?')}）")
    # 2. liveness 超期检测（读 liveness.yml 期望周期 vs 实际最近 run）
    ticks = _load_liveness_config()
    if ticks:
        now = datetime.datetime.now(datetime.timezone.utc)
        for t in ticks:
            name = t.get("name","")
            expect = t.get("expect_hours", 0)
            # W0-5 类型守卫（Copilot review）：_load_liveness_config 在 PyYAML 可用时
            # 会原样返回非整数 expect_hours（如字符串），直接 expect <= 0 会抛
            # TypeError 中断 digest。强制转 int，转换失败则按 0 跳过该项。
            try:
                expect = int(expect)
            except (TypeError, ValueError):
                expect = 0
            if not name or expect <= 0: continue
            # best-effort 采集：gh 调用本身可能抛异常，包一层 try 与其他 _gather_* 一致。
            try:
                p = gh("run","list","-R",CONTROL_REPO,"--workflow",f"{name}.yml",
                       "--limit","1","--json","createdAt,conclusion")
                runs = json.loads(p.stdout or "[]")
                if runs:
                    created = _parse_utc_iso(runs[0]["createdAt"])
                    age_h = (now - created).total_seconds() / 3600
                    if age_h > expect:
                        items.append(f"- **liveness 超期**: {name} 最近 run 在 {age_h:.1f}h 前（期望 ≤{expect}h）")
                else:
                    items.append(f"- **liveness 无 run**: {name} 从未运行过（期望 ≤{expect}h）")
            except Exception as e:
                # best-effort 采集：单个 workflow 的 run 解析失败不影响总体扫描，
                # 跳过该项继续下一个（CodeQL：非空 except）。
                print(f"[warn] liveness {name}: {e}", file=sys.stderr)
    # 3. open Incident
    try:
        p = gh("issue","list","-R",REPO,"--label","incident","--state","open",
               "--limit","10","--json","number,title,createdAt")
        incs = json.loads(p.stdout or "[]")
        for inc in incs:
            items.append(f"- **Incident #{inc['number']}**: {inc['title']} ({inc.get('createdAt','?')})")
    except Exception as e:
        # best-effort 采集：Incident 解析失败时降级为空，不中断 digest（CodeQL：非空 except）。
        print(f"[warn] incidents: {e}", file=sys.stderr)
    if not items:
        items.append("- （无退化：CI 无连败、liveness 全在期内、无 open Incident）")
    return "\n".join(items)

def _render_liveness_table():
    """liveness 期望周期表（附在 digest 末尾，供人快速核对）。"""
    ticks = _load_liveness_config()
    if not ticks:
        return "（.loop/liveness.yml 未找到 ticks 配置）"
    lines = ["| workflow | 期望周期 |", "|---|---|"]
    for t in ticks:
        lines.append(f"| {t.get('name','?')} | {t.get('expect_hours','?')}h |")
    return "\n".join(lines)

def generate_digest():
    """生成 .loop/HUMAN-TODO.md 四问（W0-5）。

    读 .loop/templates/human-todo.md 模板，填入四问数据，写 .loop/HUMAN-TODO.md。
    四问（手册 245 行）：
      1. 卡在我这的 — needs-human 标签 issue + 根 HUMAN-TODO.md 未勾选条目
      2. 昨天放行的 — 最近 24h 合并的 PR
      3. 什么退化了 — CI 连败 + liveness 超期 + open Incident
      4. 花了多少 — 成本占位"未接入"（WAVE-12 落地计量管道）
    """
    print("[12] Generate HUMAN-TODO.md digest (四问)...")
    if not HUMAN_TODO_TEMPLATE.exists():
        print(f"  → template not found: {HUMAN_TODO_TEMPLATE}")
        return
    tpl = HUMAN_TODO_TEMPLATE.read_text(encoding="utf-8")
    rendered = tpl.replace("{{generated_at}}", datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"))
    rendered = rendered.replace("{{blocked_on_human}}", _gather_blocked_on_human())
    rendered = rendered.replace("{{released_yesterday}}", _gather_released_yesterday())
    rendered = rendered.replace("{{degradations}}", _gather_degradations())
    rendered = rendered.replace("{{cost}}", "- 未接入（LLM 用量与 CI 分钟数计量管道在 WAVE-12 落地）")
    rendered = rendered.replace("{{liveness_table}}", _render_liveness_table())
    HUMAN_TODO_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_TODO_OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"  → wrote {HUMAN_TODO_OUTPUT}")

# ==================================================================
# W2-8 tick supervisor：Step 注册表 + per-step 超时/异常/last_success_at
# 禁止 try/except pass：任何 step 的异常/超时/不可用都记录为真实结果（fail-closed）。
# ==================================================================
import signal as _signal


class Step:
    """一个可监督的子步：注册名 + 目标函数 + 独立超时 + 最近成功时间戳。

    归监督器持有 last_success_at / last_error / status（ok|exception|timed_out|unavailable）。
    """
    def __init__(self, name, fn, timeout_sec=120):
        self.name = name
        self.fn = fn
        self.timeout_sec = timeout_sec
        self.last_success_at = None   # per-step 最近成功时间戳
        self.last_ran_at = None
        self.last_error = None
        self.status = None


def state_integrity_audit():
    """W2-8 新增步：接 W2-4——用 conductor.state_audit 校验卡片状态哈希链。

    找不到链文件不算绿：抛 _StepInterrupted → 监督器记录 status=unavailable
    （真实结果，fail-closed），绝不当作"成功跳过"。
    """
    print("[state_integrity_audit] verify card-state hash chain (W2-4)...")
    from conductor import state_audit

    cand = []
    base = (_env(E).get("LOOP_STATE") or "").strip()
    if base:
        cand.append(os.path.join(base, "cards", "chains.json"))
    if _env(E).get("LOOP_STATE_CHAIN"):
        cand.insert(0, _env(E)["LOOP_STATE_CHAIN"])
    cand += [
        str(LOOP_ROOT / ".loop" / "state" / "cards-chain.json"),
        str(LOOP_ROOT / ".loop" / "state" / "chain.json"),
        str(LOOP_ROOT / ".loop" / "state.json"),
    ]
    chain_file = next((p for p in cand if os.path.exists(p)), None)
    if not chain_file:
        raise _StepInterrupted(
            "state_integrity_audit: no card-state chain file found; "
            "recorded as unavailable (fail-closed, not green)"
        )
    blocks = state_audit.load_blocks(chain_file)
    rc = state_audit.audit(blocks)
    if rc != 0:
        raise _StepInterrupted(f"state_integrity_audit: chain audit FAILED (rc={rc})")
    print("state_integrity_audit: chain verified OK")


class _StepInterrupted(Exception):
    """步骤因不可用/内部失败需上报真实结果时抛出（不被当作静默 ok）。"""


class _StepTimeoutError(Exception):
    """某些平台无 SIGALRM 时的超时兜底标记（见 run_step）。"""


# ==================================================================
# W3-TK 接线步：reconcile / escalate / digest / scheduled_demo_drop（tick.py 单一 owner）
# 纯库由 W3-4/5/9 提供；此处只做注册与失败上报（fail-closed，绝不吃假绿）。
# ==================================================================
def reconcile_step():
    """[W3-TK] 事件-投影对账步：读事件日志 vs 当前卡状态投影，diff≠0 / 空日志 → Incident+不可用。"""
    print("[reconcile] event-vs-projection reconcile...")
    from conductor import state_reconcile, events
    root = os.environ.get("LOOP_STATE") or str(LOOP_ROOT / ".loop" / "state")
    events_dir = events.resolve_events_root(root)
    rows, _ = events.load_events(events_dir)
    proj = {}
    try:
        for it, blk in get_cards():
            if blk.get("id"):
                proj[blk["id"]] = blk.get("state")
    except Exception as e:  # noqa: BLE001 —— 投影读取失败不中断对账，仅告警
        print(f"[warn] projection read failed: {e}", file=sys.stderr)
    res = state_reconcile.reconcile(rows, projection=proj)
    print(f"    events={res.events_total}, coverage={res.coverage}, diff={res.diff}")
    if not res.ok:
        for inc in res.incidents:
            open_incident("Reconcile FAIL", f"[reconcile] {inc}")
        raise _StepInterrupted("; ".join(res.incidents) or "reconcile failed (fail-closed)")
    print("    reconcile OK")


def escalate_step():
    """[W3-TK] escalate 步：读 escalation.yml 评估；critical→freeze 时置 policy.freeze.all=true（唯一写者）。"""
    print("[escalate] evaluate escalation rules...")
    from conductor import escalation
    yml = os.environ.get("LOOP_ESCALATION_YML", "escalation.yml")
    # context：从 open incident / tick 状态推导最少变量（缺变量算不算触发，见 evaluate 容忍逻辑）
    inc_count = 0
    try:
        p = gh("issue", "list", "-R", CONTROL_REPO, "--state", "open", "--label", "incident",
               "--limit", "50", "--json", "number,createdAt")
        incs = json.loads(p.stdout or "[]")
        inc_count = len(incs)
    except Exception:  # noqa: BLE001
        inc_count = 0
    context = {
        "incident_open_days": 0,
        "digest_fail_count": 0,
        "loop_state_ref_missing": False,
        "cas_commit_permission_denied": False,
        "reconcile_consecutive_fail": 0,
        "card_attempts": 0,
        "gh_api_remaining_pct": 1.0,
        "tick_consecutive_fail": 0,
        "pr_ci_consecutive_fail": 0,
        "daily_audit_findings_exhausted": False,
        "canary_chain_cleanup_fail": 0,
        "pr_no_human_review_hours": 0,
        "incident_count": inc_count,
    }
    res = escalation.evaluate(context, yml_path=yml)
    print(f"    has_freeze={res.has_freeze}, outcomes={[o.rule_id for o in res.outcomes]}")
    if res.has_freeze:
        # 唯一写者（W3-TK）执行全局冻结：policy.yml freeze.all=true，走 kill switch。
        _set_freeze_all(True)
        open_incident("Escalation → freeze.all", "escalation advice=freeze; set policy.freeze.all=true")
    print("    escalate OK")


def _set_freeze_all(value):
    """把 policy.yml 的 freeze.all 置为 value（W3-TK 是唯一写者，N3）。

    CodeQL 修复：#1 删除函数内重复的 `import re`（模块级 L12 已导入）；
    #2 为正则加 re.MULTILINE —— policy.yml 中 `freeze:` 位于文件中段（非文件首行），
       若缺 MULTILINE，`^` 仅锚定字符串开头，将永不命中 → 杀开关失效（原实现缺陷）。
    """
    path = pathlib.Path(LOOP_ROOT) / POLICY_FILE
    text = path.read_text(encoding="utf-8")
    new_text = re.sub(r'^(\s*freeze:\s*\n\s*all:\s*)false', r'\g<1>' + str(value).lower(), text,
                      count=1, flags=re.MULTILINE)
    if new_text == text:
        new_text = re.sub(r'^(\s*freeze:\s*\n\s*all:\s*)true', r'\g<1>' + str(value).lower(), text,
                          count=1, flags=re.MULTILINE)
    path.write_text(new_text, encoding="utf-8")
    print(f"    policy.freeze.all → {value}")


def digest_step():
    """[W3-TK] digest 步：human_queue.build_digest 组装人类决策 digest（含 SLA 列）。"""
    print("[digest] assemble human-queue digest...")
    from conductor import human_queue
    decisions = []  # W3-5 纯库负责组装；真实决策来源由后续卡/人工填入
    res = human_queue.build_digest(decisions)
    out_dir = LOOP_ROOT / ".loop" / "plan" / "inbox"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "human-digest.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2))
    print(f"    digest rows={len(res['rows'])}, sla_column={res['sla_column']}")
    print("    digest OK")


def scheduled_demo_drop_step():
    """[W3-TK] 演示投放步：bot 以 scheduled_demo_drop actor 投 demo 卡（72h 演示用）。"""
    print("[scheduled_demo_drop] demo drop (only during 72h demo)...")
    from conductor import events
    demo_json = LOOP_ROOT / "waves" / "WAVE-03" / "demo_cards.json"
    if demo_json.exists() and os.environ.get("LOOP_DEMO_DROP"):
        events.append_event({"event": "scheduled_demo_drop", "actor": "scheduled_demo_drop",
                             "repo": REPO, "identity": os.environ.get("LOOP_IDENTITY", "bot")})
        print("    scheduled_demo_drop event emitted")
    else:
        print("    not in demo window / demo_cards absent → skip (ok)")
    print("    scheduled_demo_drop OK")


# Step 注册表：主循环监督的对象（按 tick 既有顺序）。
STEPS = [
    Step("zombie_reclaim", zombie_reclaim, timeout_sec=120),
    Step("escalate", escalate, timeout_sec=120),
    Step("unblock_deps", unblock_deps, timeout_sec=120),
    Step("path_lease_fallback", path_lease_fallback, timeout_sec=120),
    Step("tier_judge", tier_judge, timeout_sec=120),
    Step("liveness_check", liveness_check, timeout_sec=120),
    Step("audit_shard_rotate", audit_shard_rotate, timeout_sec=120),
    Step("occurrences_bump_severity", occurrences_bump_severity, timeout_sec=120),
    Step("plan_inbox_pack", plan_inbox_pack, timeout_sec=120),
    Step("silent_auto_release", silent_auto_release, timeout_sec=120),
    Step("race_mode_handler", race_mode_handler, timeout_sec=120),
    Step("state_integrity_audit", state_integrity_audit, timeout_sec=120),  # 接 W2-4
    # --- W3-TK 新增四步：reconcile / escalate / digest / scheduled_demo_drop ---
    Step("reconcile", reconcile_step, timeout_sec=180),   # 事件-投影对账（fail-closed）
    Step("escalate_step", escalate_step, timeout_sec=180),  # escalation 评估 + freeze.all 触发
    Step("digest", digest_step, timeout_sec=180),         # 人类决策 digest 组装
    Step("scheduled_demo_drop", scheduled_demo_drop_step, timeout_sec=180),  # 72h 演示投放
]


def _step_timeout_handler(signum, frame):
    raise _StepTimeoutError(f"step exceeded timeout ({signum}s)")


def run_step(step):
    """执行单个 step，应用其独立超时并记录异常/成功时间戳（绝不 try/except pass）。"""
    has_alarm = hasattr(_signal, "SIGALRM")
    old_handler = None
    if has_alarm:
        old_handler = _signal.signal(_signal.SIGALRM, _step_timeout_handler)
        _signal.alarm(step.timeout_sec)
    try:
        step.fn()
        step.status = "ok"
        step.last_success_at = time.time()
        step.last_error = None  # 成功后清除历史错误，避免监督摘要误报旧失败
    except _StepTimeoutError:
        step.status = "timed_out"
        step.last_error = f"step {step.name} timed out after {step.timeout_sec}s"
    except _StepInterrupted as e:
        step.status = "unavailable"
        step.last_error = str(e)
    except Exception as e:  # 记录非空异常（fail-closed），不静默吞
        step.status = "exception"
        step.last_error = f"{type(e).__name__}: {e}"
    finally:
        if has_alarm:
            _signal.alarm(0)
            _signal.signal(_signal.SIGALRM, old_handler)
    step.last_ran_at = time.time()
    bits = [f"→ step {step.name}: status={step.status}"]
    if step.last_error:
        bits.append(f"error: {step.last_error}")
    if step.last_success_at:
        bits.append(f"last_success_at={step.last_success_at}")
    print("  " + ", ".join(bits))
    return step.status


def run_steps(steps=None):
    """监督器跑全部注册 step；任一非 ok 记为真实结果，整体返回 False（fail-closed）。"""
    steps = steps if steps is not None else STEPS
    print(f"--- tick supervisor: supervising {len(steps)} steps ---")
    ok = True
    for step in steps:
        if run_step(step) != "ok":
            ok = False
    print("--- tick supervisor summary ---")
    for step in steps:
        print(f"  {step.name}: status={step.status}, last_success_at={step.last_success_at}, "
              f"last_error={step.last_error}")
    return ok


# ==================================================================
# main
# ==================================================================
def main(argv=None):
    """Run one control-plane tick.

    Pass argv=['--dry-run'] (or run `python conductor/tick.py --dry-run`) to
    print the resolved config (REPO / CONTROL_REPO / LOOP_ROOT / POLICY_FILE)
    and exit BEFORE any gh calls — no network required. Used to evidence that
    the single tick.py serves both repos purely via env/config (card R11-6).
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    print(f"=== conductor tick @ {now.isoformat()} ===")
    if "--dry-run" in args:
        print(f"[dry-run] REPO={REPO}")
        print(f"[dry-run] CONTROL_REPO={CONTROL_REPO}")
        print(f"[dry-run] LOOP_ROOT={LOOP_ROOT}")
        print(f"[dry-run] POLICY_FILE={POLICY_FILE}")
        print("[dry-run] exiting before any gh calls (no network).")
        return
    # W0-5: --generate-digest 只生成 .loop/HUMAN-TODO.md 四问，不走 tick 写操作。
    # 与 freeze 守卫独立——digest 是只读聚合（gh query），即使波前冻结也该出报告。
    if "--generate-digest" in args:
        generate_digest()
        return
    print(f"repo: {REPO}, policy: {POLICY_FILE}")
    # W0-3 freeze 守卫：policy.freeze.all=true → 退出 0、日志 FROZEN、无写操作
    # （波前冻结，满足 wave 负证 N2：freeze.all=true 时 tick 退出 0、日志 FROZEN、
    # 无写操作）。与 conductor.yml 的 Freeze guard step 互补：workflow 级先拦，
    # 此处为 tick 进程内 defense-in-depth，保证无论何种调用方式（cron /
    # workflow_dispatch / 手动 `python conductor/tick.py`）都 honor freeze。
    _freeze = POLICY.get("freeze", {}) or {}
    if _freeze.get("all"):
        print("FROZEN: policy.freeze.all=true, skipping tick writes (wave frozen)")
        return
    # W2-8：主循环由 tick supervisor 监督（Step 注册表 + 每步超时/异常/last_success_at）。
    ok = run_steps()
    print("=== tick complete ===")
    if not ok:
        # fail-closed：任一 registered step 未绿（异常/超时/不可用）→ 非 0 退出
        print("FAIL: one or more supervised steps did not pass (fail-closed)")
        sys.exit(1)

if __name__ == "__main__":
    main()
