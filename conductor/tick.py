#!/usr/bin/env python3
"""conductor/tick.py — 手册 6.1 六件事，每 5 分钟一轮。

六件事（按序执行）：
1. 僵尸回收：lease_until < now 且 lease 期内无新 commit → state=ready, attempt+=1, 清 claim_id
2. 升档：attempt>=2 换模型池, attempt>=3 升 tier, attempt>=4 关卡 + 开拆卡 Finding
3. 依赖放行：blocked_by 全部 merged → 置 ready
4. 路径租约兜底：两张 claimed 卡 paths 交叉 → 后领的退回 ready
5. tier 判定：paths 命中 auth|billing|migrations|deploy|.github|settings|contracts → 强制 critical
6. 存活自检：最近一次 audit/export/canary 超过 26 小时 → 开 Incident
"""
import json, os, subprocess, sys, time, fnmatch, re, datetime

E = os.environ
REPO = f'{E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))}/{E.get("LOOP_REPO","product-x")}'
ORG = E.get("LOOP_ORG", E.get("GITHUB_REPOSITORY_OWNER",""))
POLICY_FILE = E.get("LOOP_POLICY", "policy.yml")

CRITICAL_PATTERNS = ["auth", "billing", "migrations", "deploy", ".github", "settings", "contracts"]
ALIVE_THRESHOLD_HOURS = 26

def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, **kw)

def gh(*a):
    return sh("gh", *a)

def load_policy():
    """简易 YAML 解析 policy.yml（不依赖 PyYAML）。"""
    try:
        import yaml
        with open(POLICY_FILE) as f:
            return yaml.safe_load(f)
    except ImportError:
        pass
    # fallback: line-by-line 解析
    policy = {}
    try:
        with open(POLICY_FILE) as f:
            for line in f:
                line = line.rstrip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("  ") and ":" in line:
                    k, _, v = line.strip().partition(":")
                    v = v.strip()
                    if v.startswith("{"):
                        try: v = eval(v, {"__builtins__":{}}, {})
                        except: pass
                    elif v.startswith("["):
                        try: v = eval(v, {"__builtins__":{}}, {})
                        except: pass
                    elif v.isdigit():
                        v = int(v)
                    elif v.replace(".","").isdigit():
                        v = float(v)
                    policy[k] = v
    except FileNotFoundError:
        pass
    return policy

POLICY = load_policy()
MAX_CARDS = POLICY.get("execute", {}).get("max_parallel_cards", 6) if isinstance(POLICY.get("execute"), dict) else 6

def extract_block(body):
    m = "```json loop"
    if m not in (body or ""): return None
    seg = body.split(m,1)[1].split("```",1)[0]
    try: return json.loads(seg)
    except Exception: return None

def get_cards():
    """获取所有 open 的 Card issue。"""
    q = gh("issue","list","-R",REPO,"--state","open","--limit","200",
           "--json","number,title,body,updatedAt,labels")
    out = []
    for it in json.loads(q.stdout or "[]"):
        blk = extract_block(it["body"])
        if blk: out.append((it, blk))
    return out

def write_block(num, blk):
    """写回 card block（非 CAS，conductor 有写权限）。"""
    it = json.loads(gh("issue","view",str(num),"-R",REPO,"--json","body").stdout)
    body = it["body"]
    m = "```json loop"
    if m not in body: return False
    head, rest = body.split(m,1); tail = rest.split("```",1)[1]
    new = head + m + "\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```" + tail
    import pathlib, tempfile
    p = pathlib.Path(tempfile.gettempdir()) / f"body-{num}.tmp"
    p.write_text(new)
    gh("issue","edit",str(num),"-R",REPO,"--body-file",str(p))
    return True

def open_incident(title, body):
    """开 Incident issue。"""
    gh("issue","create","-R",REPO,"--title",title,"--label","incident","--body",body)
    print(f"  → opened Incident: {title}")

def GLOB(a, b):
    return any(fnmatch.fnmatch(x.rstrip("/*"), y.rstrip("/*")) or
               fnmatch.fnmatch(y.rstrip("/*"), x.rstrip("/*")) for x in a for y in b)

# ============================================================
# 1. 僵尸回收
# ============================================================
def zombie_reclaim():
    print("[1] Zombie reclaim...")
    now = int(time.time())
    for it, blk in get_cards():
        if blk.get("state") not in ("claimed", "in_progress"): continue
        lease = blk.get("lease_until", 0)
        if lease > now: continue
        # 检查 lease 期内是否有新 commit
        br = blk.get("claim_id","")
        sandbox = blk.get("sandbox","")
        has_commit = False
        if br:
            p = gh("pr","list","-R",REPO,"--head",f'agent/{blk.get("id","")}',"--state","open",
                   "--json","number,updatedAt")
            try:
                prs = json.loads(p.stdout or "[]")
                for pr in prs:
                    if pr.get("updatedAt","") > str(datetime.datetime.utcfromtimestamp(lease - int(E.get("LOOP_LEASE_MIN","45"))*60)):
                        has_commit = True
            except Exception:
                pass
        if not has_commit:
            blk["state"] = "ready"
            blk["attempt"] = blk.get("attempt", 0) + 1
            blk.pop("claim_id", None)
            blk.pop("sandbox", None)
            blk.pop("lease_until", None)
            blk.pop("heartbeat_at", None)
            write_block(it["number"], blk)
            print(f"  → #{it['number']} ({blk.get('id','?')}) reclaimed (attempt={blk['attempt']})")

# ============================================================
# 2. 升档
# ============================================================
def escalate():
    print("[2] Escalate...")
    for it, blk in get_cards():
        attempt = blk.get("attempt", 0)
        if attempt < 2: continue
        changed = False
        if attempt >= 4:
            # 关卡 + 开拆卡 Finding
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
            # 换模型池：在卡片上留言提示
            gh("issue","comment",str(it["number"]),"-R",REPO,
               "--body",f"⚠️ Escalation: attempt={attempt}, consider different model pool.")
        if changed:
            write_block(it["number"], blk)

# ============================================================
# 3. 依赖放行
# ============================================================
def unblock_deps():
    print("[3] Unblock dependencies...")
    for it, blk in get_cards():
        blocked_by = blk.get("blocked_by")
        if not blocked_by: continue
        if isinstance(blocked_by, str): blocked_by = [blocked_by]
        all_merged = True
        for dep in blocked_by:
            # 检查依赖卡是否已 merged/closed
            p = gh("issue","view",str(dep),"-R",REPO,"--json","state")
            try:
                st = json.loads(p.stdout or "{}").get("state","")
                if st != "closed":
                    all_merged = False; break
            except Exception:
                all_merged = False; break
        if all_merged:
            blk["state"] = "ready"
            blk.pop("blocked_by", None)
            write_block(it["number"], blk)
            print(f"  → #{it['number']} unblocked (all deps merged)")

# ============================================================
# 4. 路径租约兜底
# ============================================================
def path_lease_fallback():
    print("[4] Path lease fallback...")
    claimed = [(it, blk) for it, blk in get_cards() if blk.get("state") in ("claimed","in_progress")]
    for i, (it_a, blk_a) in enumerate(claimed):
        for it_b, blk_b in claimed[i+1:]:
            if GLOB(blk_a.get("paths",[]), blk_b.get("paths",[])):
                # 后领的退回 ready（按 claim 时间，heartbeat_at 更大的为后领）
                ha = blk_a.get("heartbeat_at", 0)
                hb = blk_b.get("heartbeat_at", 0)
                loser = blk_b if hb > ha else blk_a
                loser_it = it_b if hb > ha else it_a
                loser["state"] = "ready"
                loser.pop("claim_id", None)
                loser.pop("lease_until", None)
                write_block(loser_it["number"], loser)
                print(f"  → #{loser_it['number']} ({loser.get('id','?')}) path conflict, sent back to ready")

# ============================================================
# 5. tier 判定
# ============================================================
def tier_judge():
    print("[5] Tier judge...")
    for it, blk in get_cards():
        if blk.get("state") != "ready": continue
        paths = blk.get("paths", [])
        if any(any(patt in p for patt in CRITICAL_PATTERNS) for p in paths):
            if blk.get("tier") != "critical":
                old = blk.get("tier","standard")
                blk["tier"] = "critical"
                write_block(it["number"], blk)
                print(f"  → #{it['number']} tier {old} → critical (path match)")

# ============================================================
# 6. 存活自检
# ============================================================
def liveness_check():
    print("[6] Liveness check...")
    now = datetime.datetime.utcnow()
    threshold = now - datetime.timedelta(hours=ALIVE_THRESHOLD_HOURS)
    # 检查最近一次 canary / scribe / audit run
    checks = ["canary", "scribe", "nightly-rubric"]
    for wf in checks:
        p = gh("run","list","--workflow",f"{wf}.yml","--limit","1","--json","createdAt,conclusion")
        try:
            runs = json.loads(p.stdout or "[]")
            if not runs:
                open_incident(f"Liveness: no {wf} runs found",
                             f"No {wf} workflow runs found. System may be down.")
                continue
            last = runs[0]
            created = datetime.datetime.fromisoformat(last["createdAt"].replace("Z",""))
            if created < threshold:
                open_incident(f"Liveness: {wf} stale (> {ALIVE_THRESHOLD_HOURS}h)",
                             f"Last {wf} run was at {last['createdAt']}, exceeding {ALIVE_THRESHOLD_HOURS}h threshold.")
        except Exception as e:
            print(f"  → {wf}: check failed ({e})")

# ============================================================
# main
# ============================================================
def main():
    print(f"=== conductor tick @ {datetime.datetime.utcnow().isoformat()} ===")
    print(f"repo: {REPO}, policy: {POLICY_FILE}")
    zombie_reclaim()
    escalate()
    unblock_deps()
    path_lease_fallback()
    tier_judge()
    liveness_check()
    print("=== tick complete ===")

if __name__ == "__main__":
    main()
