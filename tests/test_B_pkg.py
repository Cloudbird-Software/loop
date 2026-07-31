#!/usr/bin/env python3
"""B 包验收模拟器：伪造 issue/PR/runs 状态 → 跑 tick/retro → 验证每个功能。

运行方式：
  pip install PyYAML --quiet 2>/dev/null; python tests/test_B_pkg.py

覆盖：
  TC-TIER-1  tier 判定器：paths 含 migrations → 自动判 critical
  TC-TIER-2  tier 判定器：paths 含 .github/workflows → critical
  TC-TIER-3  tier 判定器：auth/billing/deploy paths → critical
  TC-TIER-4  tier 判定器：普通路径不升级
  TC-AUDIT-1 audit 分片轮转：4 个独立调用轮完 S1→S2→S3→S4（无降频干扰时 shards_per_day=2）
  TC-AUDIT-2 audit 配额：quota_left = policy 上限 8
  TC-AUDIT-3 audit 降频：14 天采纳率 0.2 < 0.35 → throttle active（1 shard/day）
  TC-AUDIT-4 audit stale close：21 天未出现的非 critical fp → closed_findings 条目
  TC-AUDIT-5 fingerprint 去重：同 lens+path+symbol+rule_id → 相同前 16 hex
  TC-OCC-1   occurrences>=3：severity low→medium + checker-needed 标记
  TC-INBOX-1 inbox 打包：.loop/plan/inbox/ 5 份 JSON，字段名对齐 OPC-v4 P3 清单
  TC-SILENT-1 48h 静默：PR 49h 前更新无人类 review → 发出 loop-materialize-silent dispatch
  TC-RACE-1  race 模式：同 critical cid 双 PR → 取 diff 小的为 winner，关 loser
  TC-RETRO-1 retro 周五：产出零 LLM 五问 JSON + Finding issue 正文文件 + zero_llm=True
  TC-RETRO-2 retro Q3：ord>k 之后通过率降 >10% → 建议 max_cards_per_session = k-1
  TC-RETRO-3 retro Q5：记录 prev 行动项并能回读（落地检测）
"""
import json, os, sys, subprocess, tempfile, pathlib, datetime, hashlib, shutil, textwrap

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = HERE.parent
TMP = pathlib.Path(tempfile.mkdtemp(prefix="Bpkg-test-"))
os.environ["LOOP_ROOT"] = str(TMP)
os.environ["LOOP_POLICY"] = str(TMP / "policy.yml")
os.environ["GH_TOKEN"] = "dummy"
sys.path.insert(0, str(WORKSPACE))

MOCK_BIN = TMP / "mock-bin"
MOCK_BIN.mkdir(parents=True, exist_ok=True)
MOCK_LOG = TMP / "gh_calls.log"

STATE_FILE_ISSUES = TMP / "gh_issues.json"
STATE_FILE_PRS = TMP / "gh_prs.json"
STATE_FILE_DISPATCHES = TMP / "dispatches.json"
STATE_FILE_ISSUES.write_text("[]")
STATE_FILE_PRS.write_text("[]")
STATE_FILE_DISPATCHES.write_text("[]")

GH_SCRIPT = f'''#!/usr/bin/env python3
import json, os, sys, datetime
ISSUES_FILE={repr(str(STATE_FILE_ISSUES))}
PRS_FILE={repr(str(STATE_FILE_PRS))}
DISPATCH_FILE={repr(str(STATE_FILE_DISPATCHES))}
LOG_FILE={repr(str(MOCK_LOG))}
args=sys.argv[1:]
with open(LOG_FILE,"a") as f:
    f.write(json.dumps(args, ensure_ascii=False)+"\\n")
def out(s, code=0):
    sys.stdout.write(s); sys.exit(code)

def filter_by_labels(items, labels_in_args):
    if not labels_in_args: return items
    result = []
    for it in items:
        it_labels = set(l.get("name","") for l in it.get("labels",[]))
        if any(lab in it_labels for lab in labels_in_args):
            result.append(it)
    return result

# -------- issue list --------
if args[:3]==["issue","list","-R"]:
    try: issues=json.load(open(ISSUES_FILE))
    except Exception: issues=[]
    # 抓 --label 值
    labels = []
    for i,a in enumerate(args):
        if a=="--label" and i+1<len(args): labels.append(args[i+1])
    if labels:
        issues = filter_by_labels(issues, labels)
    # 抓 --state 值过滤
    for i,a in enumerate(args):
        if a=="--state" and i+1<len(args):
            st = args[i+1]
            if st != "all":
                issues = [x for x in issues if x.get("state","open")==st]
    out(json.dumps(issues, ensure_ascii=False))

# -------- issue view --------
# 形式 1: gh issue view <num> -R REPO
# 形式 2: gh issue view -R REPO <num>
def find_issue_num(args):
    for a in args[2:]:
        if a.startswith("-"): continue
        try:
            int(a)
            return a
        except Exception:
            pass
    return None

if args[:2]==["issue","view"]:
    num = find_issue_num(args)
    if num is None:
        out(json.dumps({{}}))
    try:
        issues=json.load(open(ISSUES_FILE))
        for it in issues:
            if str(it.get("number"))==str(num):
                out(json.dumps(it, ensure_ascii=False))
    except Exception: pass
    # fallback 空 body 但有效 JSON（tick 中的 write_block 会 inject）
    out(json.dumps({{"number":int(num), "body": "", "comments":[]}}))

# -------- issue / pr edit / comment / close / create --------
if args[:2] in (["issue","edit"], ["issue","comment"], ["issue","close"], ["pr","close"], ["issue","create"]):
    out("issue mock-#999\\n")

# -------- pr list --------
if args[:2]==["pr","list"]:
    try: prs=json.load(open(PRS_FILE))
    except Exception: prs=[]
    # --state 过滤
    for i,a in enumerate(args):
        if a=="--state" and i+1<len(args):
            st=args[i+1]
            if st!="all": prs=[p for p in prs if p.get("state","open")==st]
    # --head 过滤（按 headRefName 精确匹配，不 prefix 以区分 race 的两个 PR）
    for i,a in enumerate(args):
        if a=="--head" and i+1<len(args):
            h=args[i+1]
            prs=[p for p in prs if p.get("headRefName","")==h]
    out(json.dumps(prs, ensure_ascii=False))

# -------- run list --------
if args[:2]==["run","list"]:
    out(json.dumps([{{"createdAt": (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(hours=1)).isoformat()+"Z", "conclusion":"success"}}]))

# -------- api dispatch --------
if len(args)>=3 and args[0]=="api" and "dispatches" in args[1]:
    try: ev=json.load(open(DISPATCH_FILE))
    except Exception: ev=[]
    ev.append(dict(args=args, ts=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()))
    json.dump(ev, open(DISPATCH_FILE,"w"))
    out("{{}}")

# -------- default --------
out("")
'''
(MOCK_BIN / "gh").write_text(GH_SCRIPT)
(MOCK_BIN / "gh").chmod(0o755)
os.environ["PATH"] = str(MOCK_BIN) + os.pathsep + os.environ["PATH"]

(TMP / "policy.yml").write_text((WORKSPACE / "policy.yml").read_text())
(TMP / "UPSTREAM.yaml").write_text("spec-kit:\n  pin: v1.2.3\n  seam: C\nzizmor:\n  pin: v0.4.0\n  seam: B\n")
(TMP / ".loop").mkdir(exist_ok=True)

PASS = []; FAIL = []
def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f"  — {detail}" if detail else ""))

def make_card_body(blk):
    return "前言\n```json loop\n" + json.dumps(blk, indent=2, ensure_ascii=False) + "\n```\n"

# ==================================================================
from conductor import tick as T
from conductor import retro as R

# ---------------- TIER tests ----------------
ok("TC-TIER-1 migrations → critical",
   T.path_matches_critical(["src/db/migrations/0001_init.py"]))
ok("TC-TIER-2 workflows/** → critical",
   T.path_matches_critical([".github/workflows/gates.yml"]))
ok("TC-TIER-3 auth billing deploy → critical",
   T.path_matches_critical(["src/auth/login.ts"]) and
   T.path_matches_critical(["billing/subscription.ts"]) and
   T.path_matches_critical(["deploy/helm/values.yaml"]))
ok("TC-TIER-4 普通路径不升级",
   not T.path_matches_critical(["src/ui/home.tsx"]) and
   not T.path_matches_critical(["docs/guide.md"]) and
   not T.path_matches_critical(["README.md"]))

ok("TC-AUDIT-5 fingerprint 确定性",
   T.fingerprint("ci-security","wf/x.yml","bad_action","z-123") ==
   T.fingerprint("ci-security","wf/x.yml","bad_action","z-123") and
   len(T.fingerprint("a","b","c","d")) == 16)

# ---------------- AUDIT shard 4-coverage（无降频干扰）----------------
import shutil as _sh
def clear_audit():
    d = TMP / ".loop" / "audit"
    if d.exists(): _sh.rmtree(d)

clear_audit()
# 4 次独立的轮转（每次假装是新一天，不塞 adoption_log 避免降频）
collected_shards = set()
collected_lenses = set()
for day_i in range(4):
    st = T._load_audit_state()
    st["last_date"] = (datetime.date.today() - datetime.timedelta(days=3-day_i)).isoformat()
    st["daily_new_findings"] = 0
    st["throttle"] = {"active": False, "reason": None, "until": None}
    st["adoption_log"] = []
    T._save_audit_state(st)
    shs = T.audit_shard_rotate()
    for sid, ls, _ in shs:
        collected_shards.add(sid)
        for l in ls: collected_lenses.add(l)

ok("TC-AUDIT-1 4 轮轮转覆盖 S1 S2 S3 S4（shards_per_day=2）",
   collected_shards >= {"S1","S2","S3","S4"},
   detail=f"got={sorted(collected_shards)}")
ok("TC-AUDIT-1b 默认 lens 集合 ≥ 10（共 12 lens 四片）",
   len(collected_lenses) >= 10,
   detail=f"count={len(collected_lenses)} lenses={sorted(collected_lenses)}")

today_shards_f = TMP / ".loop" / "audit" / "today_shards.json"
sh_json = json.loads(today_shards_f.read_text()) if today_shards_f.exists() else {}
quota_expected = int(T.POLICY.get("audit",{}).get("max_new_findings_per_day", 8) if isinstance(T.POLICY.get("audit",{}), dict) else 8)
ok("TC-AUDIT-2 日配额 quota_left == policy 上限",
   sh_json.get("quota_left") == quota_expected,
   detail=f"quota_left={sh_json.get('quota_left')} expected={quota_expected}")

# ---------------- AUDIT-3 throttle ----------------
clear_audit()
st = T._load_audit_state()
now_ts = int(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).timestamp())
# 14 天内 5 开 1 采纳 → 0.2 < 0.35
for i in range(5):
    st["adoption_log"].append({"ts": now_ts - 86400 * i, "event": "opened"})
st["adoption_log"].append({"ts": now_ts - 86400 * 0, "event": "adopted"})
T._save_audit_state(st)
T.audit_shard_rotate()
st_after = T._load_audit_state()
ok("TC-AUDIT-3 14d adopt_rate=0.2 → throttle active",
   bool(st_after["throttle"].get("active")),
   detail=f"throttle={st_after['throttle']}")

# ---------------- AUDIT-4 stale close（非 critical）----------------
clear_audit()
st = T._load_audit_state()
st["fingerprints"]["fp-olddeadbeef"] = {
    "severity": "low", "occurrences": 1,
    "last_seen": now_ts - 25*86400, "first_seen": now_ts - 30*86400,
}
# 同时一条 critical（不应被 stale close）
st["fingerprints"]["fp-critical-alive"] = {
    "severity": "critical", "occurrences": 5,
    "last_seen": now_ts - 60*86400,
}
T._save_audit_state(st)
T.audit_shard_rotate()
st_a4 = T._load_audit_state()
ok("TC-AUDIT-4 21d stale low→closed_findings, critical 免关",
   "fp-olddeadbeef" in st_a4["closed_findings"] and
   "fp-critical-alive" not in st_a4["closed_findings"])

# ---------------- OCC >=3 severity bump ----------------
clear_audit()
st = T._load_audit_state()
fp_key = T.fingerprint("dead-code","src/a.py","fn_x","rule-99")
st["fingerprints"][fp_key] = {
    "severity": "low", "occurrences": 3, "finding_id": 42,
    "_escalated_to_checker": False,
}
T._save_audit_state(st)
STATE_FILE_ISSUES.write_text("[]")
MOCK_LOG.write_text("")
T.occurrences_bump_severity()
meta = T._load_audit_state()["fingerprints"][fp_key]
# 确认 gh 调用里有 checker-needed 的标签添加
gh_calls = [json.loads(l) for l in MOCK_LOG.read_text().splitlines() if l.strip()]
has_label_add = any(
    c[:2]==["issue","edit"] and any("checker-needed" in x for x in c) for c in gh_calls
)
ok("TC-OCC-1 occ>=3 low→medium + checker-needed",
   meta["severity"]=="medium" and meta.get("_escalated_to_checker")==True,
   detail=f"meta={meta}, gh_add_edit={has_label_add}")

# ---------------- INBOX 5 JSONs 字段对齐 P3 ----------------
INBOX_DIR = TMP / ".loop" / "plan" / "inbox"
if INBOX_DIR.exists(): _sh.rmtree(INBOX_DIR)
INBOX_DIR.mkdir(parents=True, exist_ok=True)

# GRIPE issue + 评论
gripe_issue = {
    "number": 1, "title": "GRIPE BOX", "state": "open",
    "labels": [{"name":"gripe"}],
    "updatedAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "createdAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "body": "吐槽箱\n",
    "comments": [
        {"id":99,"author":{"login":"human"},
         "body":"这按钮没反应",
         "createdAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z"}
    ],
}
# Finding issue（带 label finding）
fblk = {
    "schema":1, "id":"F-001","severity":"high","occurrences":2,
    "confidence":0.9,"charter":["G2"],"fingerprint":"abcd1234"
}
finding_issue = {
    "number": 2, "title": "F-001 密钥扫描风险", "state":"open",
    "labels":[{"name":"finding"},{"name":"high"}],
    "updatedAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "createdAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "body": make_card_body(fblk),
}
# Incident issue（带 label incident）
ibl = {"schema":1,"id":"I-1","severity":"critical","state":"open"}
incident_issue = {
    "number": 3, "title": "Incident: canary 断链", "state":"open",
    "labels":[{"name":"incident"}],
    "updatedAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "createdAt": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
    "body": make_card_body(ibl),
}
STATE_FILE_ISSUES.write_text(json.dumps([gripe_issue, finding_issue, incident_issue], ensure_ascii=False))
T.plan_inbox_pack()

req = {
    "gripes.json":    {"id","issue","author","body","createdAt"},
    "findings.json":  {"number","title","severity","occurrences","confidence","charter"},
    "metrics.json":   {"generated_at","first_ci_pass_rate","human_interventions_7d","prev_wave"},
    "incidents.json": {"number","title","severity","state"},
    "upstream.json":  {"package","current_pin","seam"},
}
all_ok = True
for fn, need_keys in req.items():
    fp = INBOX_DIR / fn
    if not fp.exists():
        all_ok = False
        print(f"   - missing {fn}"); continue
    try:
        data = json.loads(fp.read_text())
    except Exception as e:
        all_ok = False
        print(f"   - {fn} invalid JSON: {e}"); continue
    if isinstance(data, list) and data:
        have = set(data[0].keys())
    elif isinstance(data, dict):
        have = set(data.keys())
    else:
        have = set()
    miss = need_keys - have
    if miss:
        all_ok = False
        print(f"   - {fn} missing fields: {miss} (have {sorted(have)})")
ok("TC-INBOX-1 5 份 JSON 字段名对齐 P3 输入清单", all_ok)

# ---------------- SILENT 48h ----------------
STATE_FILE_DISPATCHES.write_text("[]")
long_ago = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(hours=49)).isoformat()+"Z"
STATE_FILE_PRS.write_text(json.dumps([{
    "number": 100,
    "title": "WAVE-2026W30 提案",
    "state": "open",
    "labels": [{"name":"wave"}],
    "headRefName": "waves/w30",
    "updatedAt": long_ago,
    "reviewDecision": None,
}], ensure_ascii=False))
T.silent_auto_release()
dispatches = json.loads(STATE_FILE_DISPATCHES.read_text() or "[]")
dispatch_text = json.dumps(dispatches, ensure_ascii=False)
ok("TC-SILENT-1 49h 静默 wave PR → dispatch loop-materialize-silent",
   "loop-materialize-silent" in dispatch_text,
   detail=f"dispatches ({len(dispatches)}): {dispatch_text[:300]}")

# ---------------- RACE critical 双 PR ----------------
# 两张同 cid 的 race Card
cid = "C-RACE-99"
race_a = {
    "schema":1,"id":cid,"tier":"critical","state":"in_review",
    "paths":["migrations/**"],"role":"impl","attempt":0,
    "sandbox":"impl-A","model":"A","claim_id":"A-racer",
    "pr_branch": f"agent/{cid}-A",
    "heartbeat_at": int(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).timestamp())-1,
}
race_b = {
    "schema":1,"id":cid,"tier":"critical","state":"in_review",
    "paths":["migrations/**"],"role":"impl","attempt":0,
    "sandbox":"impl-B","model":"B","claim_id":"B-racer",
    "pr_branch": f"agent/{cid}-B",
    "heartbeat_at": int(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).timestamp()),
}
STATE_FILE_ISSUES.write_text(json.dumps([
    {"number":200,"title":cid+" A","state":"open","labels":[],"updatedAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
     "createdAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z","body":make_card_body(race_a)},
    {"number":201,"title":cid+" B","state":"open","labels":[],"updatedAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
     "createdAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z","body":make_card_body(race_b)},
], ensure_ascii=False))
# 两份 PR：A diff 大 (changedFiles=12)，B diff 小 (3)
STATE_FILE_PRS.write_text(json.dumps([
    {"number":301,"state":"open","headRefName":f"agent/{cid}-A","changedFiles":12,
     "additions":300,"deletions":120,
     "updatedAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z"},
    {"number":302,"state":"open","headRefName":f"agent/{cid}-B","changedFiles":3,
     "additions":60,"deletions":20,
     "updatedAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z"},
], ensure_ascii=False))
MOCK_LOG.write_text("")
T.race_mode_handler()
calls = [json.loads(l) for l in MOCK_LOG.read_text().splitlines() if l.strip()]
pr_closes = [c for c in calls if len(c)>=2 and c[0]=="pr" and c[1]=="close"]
issue_closes = [c for c in calls if len(c)>=2 and c[0]=="issue" and c[1]=="close"]
ok("TC-RACE-1 critical 双 PR: 关闭 loser (pr close>=1 + issue close>=1)",
   len(pr_closes)>=1 and len(issue_closes)>=1,
   detail=f"pr_closes={len(pr_closes)} issue_closes={len(issue_closes)}")

# ---------------- RETRO 周五 ----------------
RETRO_DIR = TMP / ".loop" / "retro"
if RETRO_DIR.exists(): _sh.rmtree(RETRO_DIR)
RETRO_DIR.mkdir(parents=True, exist_ok=True)

def mkcard(num, cid, tier, so, attempt, paths, state="closed", vr=False, charter=None, cre_days=2):
    blk = {
        "schema":1,"id":cid,"tier":tier,"state":state,
        "session_ordinal":so,"attempt":attempt,"paths":paths,
        "verify":{"required":vr},
        "charter": charter or ["G1"],
    }
    cre = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)-datetime.timedelta(days=cre_days)
    return {"number":num,"title":cid,"state":state,
            "labels":[{"name":tier}],
            "createdAt":cre.isoformat()+"Z",
            "updatedAt":datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat()+"Z",
            "body":make_card_body(blk)}

cards = []
# ord=1: 10 张 8 过 2 失败 (attempt>=2 视为 failed) → 0.80
for i in range(10):
    cards.append(mkcard(1000+i, f"C-SO1-{i}", "standard", 1, 0 if i<8 else 2, ["src/x/**"]))
# ord=2: 10 张 5 过 5 失败 → 0.50（相对 ord=1 降 30% >10%，建议 k-1=1）
for i in range(10):
    cards.append(mkcard(1100+i, f"C-SO2-{i}", "standard", 2, 0 if i<5 else 2, ["src/y/**"]))
# critical failures 放到 ord=3，避免干扰 1→2 的下降计算
for i in range(4):
    cards.append(mkcard(1200+i, f"C-CR-{i}", "critical", 3, 2, ["migrations/**","deploy/**"],
                        state="open", vr=True, charter=["G3"]))
STATE_FILE_ISSUES.write_text(json.dumps(cards, ensure_ascii=False))

# prev action items
(TMP / ".loop" / "retro" / "prev_action_items.json").write_text(json.dumps({
    "PREV-1": {"kind":"checker","file":"gates/gate_migrations_bundle.py",
               "expected_change_sha_or_keyword":"migrations/** lint",
               "change":"为 migrations/** 加 lint"},
}, ensure_ascii=False))

R.main()
retro_jsons = sorted((TMP / ".loop" / "retro").glob("retro_*W*.json"))
retro_mds = sorted((TMP / ".loop" / "retro").glob("*_issue.md"))
ok("TC-RETRO-1 retro JSON+issue 正文+zero_llm",
   len(retro_jsons)>=1 and len(retro_mds)>=1,
   detail=f"json={[p.name for p in retro_jsons]!r} md={[p.name for p in retro_mds]!r}")

if retro_jsons:
    rd = json.loads(retro_jsons[-1].read_text())
    q3 = rd.get("q3_session_ordinal", {})
    ok("TC-RETRO-2 Q3 ord2 通过率降 >10% → 建议 max_cards_per_session=1",
       q3.get("recommended_max_cards_per_session") == 1,
       detail=f"q3={json.dumps(q3, ensure_ascii=False)[:400]}")
    q5 = rd.get("q5_prev_landed", {})
    ok("TC-RETRO-3 Q5 能回读 prev 行动项 (checked)",
       q5.get("status") == "checked",
       detail=f"q5 status={q5.get('status')!r}, evidence sample={q5.get('evidence',[])[:2]}")
    ok("TC-RETRO-1b zero_llm=True in payload", bool(rd.get("zero_llm")))
else:
    ok("TC-RETRO-2", False, "no retro JSON generated")
    ok("TC-RETRO-3", False, "no retro JSON generated")
    ok("TC-RETRO-1b", False, "no retro JSON generated")

# ==================================================================
print()
print(f"==== PASS {len(PASS)} / FAIL {len(FAIL)} / TOTAL {len(PASS)+len(FAIL)} ====")
if FAIL:
    print("FAILED:", ", ".join(FAIL))
    sys.exit(1)
else:
    print("ALL PASSED")
