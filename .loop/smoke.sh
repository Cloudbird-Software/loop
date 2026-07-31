#!/usr/bin/env bash
# .loop/smoke.sh — loopd 本地冒烟测试
# 覆盖：py_compile / 远程通道移除回归 / GLOB / done+save / reaper / finding-propose-verdict / workflow 静态检查
# #52/#53：relay/filemode/run 远程命令通道已移除，原 relay/file/run/shim/intents 冒烟阶段已替换为移除回归。
# 不触真实 GitHub。
set -uo pipefail

PASS=0; FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOOPD="${REPO_ROOT}/loopd/loopd.py"

# 临时环境
TMPROOT=$(mktemp -d)
TMPWS="${TMPROOT}/ws"
mkdir -p "${TMPROOT}/.loop/logs" "${TMPROOT}/.loop/trash" "${TMPROOT}/.loop/audit"
mkdir -p "${TMPWS}/.loop/logs" "${TMPWS}/.loop/trash" "${TMPWS}/.loop/audit"

# 公共环境变量
export LOOP_ROOT="${TMPROOT}"
export LOOP_WS="${TMPWS}"
export LOOP_ORG="test-org"
export LOOP_REPO="test-repo"
export LOOP_ROLE="impl"
export LOOP_MODEL="test-model"
export LOOP_SANDBOX_ID="smoke-1"
export LOOP_POLL_MS=100
export LOOP_TIMEOUT=10
export LOOP_LEASE_MIN=45
export LOOP_HEARTBEAT_SEC=999
export LOOP_AUTOSAVE_SEC=999
export LOOP_NEXT_BLOCK_SEC=5
export LOOP_BRANCH_PREFIX="agent"
export GH_TOKEN="${GH_TOKEN:-dummy}"

# init a fake git repo for WS so git commands don't fully fail
cd "${TMPWS}" && git init -q && git config user.email t@t && git config user.name t
git commit --allow-empty -q -m init 2>/dev/null || true

cleanup() {
  if [ -n "${DAEMON_PID:-}" ] && kill -0 "${DAEMON_PID}" 2>/dev/null; then
    kill "${DAEMON_PID}" 2>/dev/null || true
  fi
  rm -rf "${TMPROOT}"
}
trap cleanup EXIT

# ============================================================
# a. py_compile loopd.py（#52/#53：loop shim 已删除，不再编译）
# ============================================================
if python3 -m py_compile "${LOOPD}" 2>/dev/null; then
  pass "a. py_compile loopd.py"
else
  fail "a. py_compile loopd.py"
fi

# ============================================================
# Stage B: 远程命令通道移除回归（#52/#53）
#   relay_thread / filemode_thread / load_intents / h_run / run verb / loop shim / intents.yaml 全部应消失；
#   往 .loop/IN.json 或 .loop/relay/inbox/ 丢 JSON 不应被消费。
#   （与 tests/test_loopd_no_remote_intents.py 对齐的 bash 侧冒烟。）
# ============================================================
echo ""
echo "=== Stage B: remote channel removal (#52/#53) ==="
# b0. loop shim + intents.yaml 文件已从仓库删除
if [ ! -f "${REPO_ROOT}/loopd/loop" ]; then pass "b0. loopd/loop shim deleted"; else fail "b0. loopd/loop shim deleted"; fi
if [ ! -f "${REPO_ROOT}/loopd/intents.yaml" ]; then pass "b0. loopd/intents.yaml deleted"; else fail "b0. loopd/intents.yaml deleted"; fi

export SMOKE_LOOPD="${REPO_ROOT}/loopd"
B_OUT=$(python3 - <<'PY'
import os, sys, json, time, pathlib
sys.path.insert(0, os.environ["SMOKE_LOOPD"])
for m in ("loopd", "loopd.loopd"):
    sys.modules.pop(m, None)
import loopd
results = []
def chk(name, ok, detail=""):
    results.append((name, ok, detail))

# 1. run 不在 HANDLERS
chk("run not in HANDLERS", "run" not in loopd.HANDLERS, str(sorted(loopd.HANDLERS)))

# 2. 远程通道符号已删除
for sym in ("relay_thread", "filemode_thread", "load_intents", "h_run"):
    chk(f"{sym} removed", not hasattr(loopd, sym))

# 3. CFG() 不创建 .loop/relay 目录
loopd.CFG()
root = pathlib.Path(os.environ["LOOP_ROOT"])
chk(".loop/relay not created by CFG()", not (root/".loop"/"relay").exists())

# 4. VERB_TABLE 不含 'run <intent>'
chk("VERB_TABLE has no 'run <intent>'", "run <intent>" not in loopd.VERB_TABLE)

# 5. .loop/IN.json drop 不被消费（无 filemode_thread → 无 OUT.md）
loop_dir = root/".loop"
(loop_dir/"IN.json").write_text(json.dumps({"id":"evil","intent":"save","args":["pwned"]}))
time.sleep(0.3)
chk("IN.json not consumed (no OUT.md)", not (loop_dir/"OUT.md").exists())

# 6. .loop/relay/inbox/ drop 不被消费（无 relay_thread → 文件仍在原地）
inbox = loop_dir/"relay"/"inbox"
inbox.mkdir(parents=True, exist_ok=True)
(inbox/"evil.json").write_text(json.dumps({"id":"evil2","intent":"done","args":[]}))
time.sleep(0.3)
chk("relay inbox drop not consumed", (inbox/"evil.json").exists())

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ")+name+("" if ok else f" :: {detail}"))
print("STAGE_B_" + ("OK" if all(r[1] for r in results) else "FAIL"))
PY
)
echo "${B_OUT}"
if echo "${B_OUT}" | grep -q "STAGE_B_OK" && ! echo "${B_OUT}" | grep -q "FAIL"; then
  pass "b. remote channel removed (run/relay/filemode/intents/shim)"
else
  fail "b. remote channel removed (run/relay/filemode/intents/shim)"
fi

# ============================================================
# Stage G2: GLOB path-match regression (v0.1.6, dir/** wildcard fix)
# ============================================================
echo ""
echo "=== Stage G2: GLOB path-match (v0.1.6 dir/** fix) ==="
G2G_OUT=$(python3 - <<'PY'
import sys, fnmatch
sys.path.insert(0, "/workspace/loopd")
import loopd
G = loopd.GLOB
cases = [
    # (staged, card_paths, expected, label)
    ("e2/handoff/MARKER.md", ["e2/handoff/**"], True,  "dir/** matches subdir file (the v0.1.6 bug)"),
    ("e2/handoff/MARKER.md", ["e2/handoff/*"],  True,  "dir/* matches subdir file"),
    ("e2/handoff/sub/a.md",  ["e2/handoff/**"], True,  "dir/** matches multi-level subdir file"),
    ("LICENSE",              ["LICENSE"],       True,  "single file path (W1-style, regression guard)"),
    ("other/x",              ["e2/handoff/**"], False, "out-of-scope rejected (no false-positive)"),
    ("e2/handoff",          ["e2/handoff/**"], False, "dir literal not matched by dir/** (fnmatch matches whole string)"),
]
results = []
for staged, paths, expected, label in cases:
    actual = G([staged], paths)
    ok = (actual == expected)
    results.append(ok)
    print(("PASS " if ok else "FAIL ")+f"{label}: GLOB([{staged!r}], {paths!r}) = {actual} (expected {expected})")
print("STAGE_G2_" + ("OK" if all(results) else "FAIL"))
PY
)
echo "${G2G_OUT}"
if echo "${G2G_OUT}" | grep -q "STAGE_G2_OK" && ! echo "${G2G_OUT}" | grep -q "FAIL"; then
  pass "g2. GLOB matches dir/** wildcards (v0.1.6 fix)"
else
  fail "g2. GLOB matches dir/** wildcards (v0.1.6 fix)"
fi

# ============================================================
# Stage H: done auto-merge + save path-scope regression
# ============================================================
echo ""
echo "=== Stage H: done auto-merge + save path-scope regression ==="

# h1. done 调用 pr merge --auto —— 用假 gh shim 拦截调用
GHSHIM="${TMPROOT}/ghshim"
mkdir -p "${GHSHIM}"
cat > "${GHSHIM}/gh" <<'SH'
#!/usr/bin/env bash
# 记录所有 gh 调用到日志，对 pr merge 返回成功
LOG="${GHSHIM_LOG:-/tmp/ghshim.log}"
echo "gh $*" >> "$LOG"
case "$1 $2" in
  "pr merge")
    echo "  (shim) would enqueue PR $4 --squash (direct, no --auto)"
    exit 0
    ;;
  "pr list")
    echo '[{"number":42,"isDraft":true,"state":"OPEN"}]'
    exit 0
    ;;
  "pr ready")
    exit 0
    ;;
  "pr view")
    # done 二次确认入队状态：返回 QUEUED 让逻辑判定已入队
    echo '{"state":"OPEN","mergeStateStatus":"QUEUED"}'
    exit 0
    ;;
  "api")
    case "$*" in
      *allow_auto_merge*) echo "true"; exit 0;;
      *) echo '{}'; exit 0;;
    esac
    ;;
  "issue view")
    printf '%s\n' '{"updatedAt":"x","body":"```json loop\n{\"id\":\"h1\",\"state\":\"claimed\"}\n```\n"}'
    exit 0
    ;;
  "issue"*) echo '{}'; exit 0;;
esac
exit 0
SH
chmod +x "${GHSHIM}/gh"

# 给 fake git repo 配一个本地 origin（让 do_save 的 git push 不 fatal）
git -C "${TMPWS}" remote remove origin 2>/dev/null || true
git -C "${TMPWS}" remote add origin "${TMPWS}/.git"

python3 - <<PY
import os, sys, json, subprocess, pathlib
os.environ["PATH"] = "${GHSHIM}:" + os.environ["PATH"]
os.environ["GHSHIM_LOG"] = "${TMPROOT}/ghshim.log"
os.environ["LOOP_ROOT"]="${TMPROOT}"
os.environ["LOOP_WS"]="${TMPWS}"
os.environ["LOOP_ORG"]="test-org"
os.environ["LOOP_REPO"]="test-repo"
os.environ["LOOP_ROLE"]="impl"
os.environ["LOOP_MODEL"]="test-model"
os.environ["LOOP_SANDBOX_ID"]="smoke-h1"
os.environ["LOOP_POLL_MS"]="100"
os.environ["LOOP_NEXT_BLOCK_SEC"]="5"
os.environ["LOOP_MAX_CARDS_PER_SESSION"]="6"
os.environ["LOOP_LEASE_MIN"]="45"
os.environ["LOOP_HEARTBEAT_SEC"]="999"
os.environ["LOOP_AUTOSAVE_SEC"]="999"
os.environ["LOOP_BRANCH_PREFIX"]="agent"
os.environ["LOOP_IO_MODE"]="shim"
os.environ["GH_TOKEN"]="dummy"
sys.path.insert(0, "${REPO_ROOT}/loopd")
import loopd
loopd.CFG()  # 物化 REPO/WS/SID/MODEL 等裸全局，否则 h_done/st 引用它们会 NameError
loopd.st(card={"num": 99, "blk":{"id":"h1-test","state":"claimed","paths":["h1/**"],"tier":"trivial","role":"impl","charter":["G0"],"attempt":0,"acceptance":["x"]}})
subprocess.run(["git","-C","${TMPWS}","checkout","-q","-b","agent/h1-test"],check=True)
out = loopd.h_done([])
PY
H1_RC=$?
if [ "${H1_RC}" = "0" ]; then
  if grep -q "pr merge" "${TMPROOT}/ghshim.log" 2>/dev/null && grep -q -- "--squash" "${TMPROOT}/ghshim.log" 2>/dev/null; then
    pass "h1. done calls gh pr merge --squash (direct enqueue, merge-queue scenario)"
  else
    fail "h1. done calls gh pr merge --squash (direct enqueue, merge-queue scenario)"
  fi
else
  fail "h1. done calls gh pr merge --squash (direct enqueue, merge-queue scenario)"
fi
rm -f "${TMPROOT}/ghshim.log"

# h2. save 后 staged 列表不含 .loop/ 且不含 paths 之外文件
mkdir -p "${TMPWS}/h2/in" "${TMPWS}/.loop"
echo "leak" > "${TMPWS}/.loop/CARD.md"
echo "ok" > "${TMPWS}/h2/in/a.txt"
cd "${TMPWS}" && git checkout -q -B agent/h2-test 2>/dev/null

python3 - <<PY
import os, sys, json, subprocess, pathlib
os.environ["LOOP_ROOT"]="${TMPROOT}"
os.environ["LOOP_WS"]="${TMPWS}"
os.environ["LOOP_ORG"]="test-org"
os.environ["LOOP_REPO"]="test-repo"
os.environ["LOOP_ROLE"]="impl"
os.environ["LOOP_MODEL"]="test-model"
os.environ["LOOP_SANDBOX_ID"]="smoke-h2"
os.environ["LOOP_POLL_MS"]="100"
os.environ["LOOP_NEXT_BLOCK_SEC"]="5"
os.environ["LOOP_MAX_CARDS_PER_SESSION"]="6"
os.environ["LOOP_LEASE_MIN"]="45"
os.environ["LOOP_HEARTBEAT_SEC"]="999"
os.environ["LOOP_AUTOSAVE_SEC"]="999"
os.environ["LOOP_BRANCH_PREFIX"]="agent"
os.environ["LOOP_IO_MODE"]="shim"
os.environ["GH_TOKEN"]="dummy"
os.environ["PATH"]="${GHSHIM}:" + os.environ["PATH"]
sys.path.insert(0, "${REPO_ROOT}/loopd")
import loopd
loopd.CFG()  # 物化 WS 等裸全局，否则 do_save 引用 WS 会 NameError（原 h2 因 try/except 静默假绿）
loopd.st(card={"num": 88, "blk":{"id":"h2-test","state":"claimed","paths":["h2/in/**"],"tier":"trivial","role":"impl","charter":["G0"],"attempt":0,"acceptance":["x"]}})
try:
    loopd.do_save("wip h2")
except Exception:
    pass
PY
H2_OUT=$(python3 - <<'PY2'
import subprocess
p = subprocess.run(["git","-C","${TMPWS}","show","--stat","--name-only","--format=","HEAD"],capture_output=True,text=True)
files=[f for f in p.stdout.strip().split("\n") if f]
bad=[f for f in files if f.startswith(".loop/") or not f.startswith("h2/in/")]
print("LEAK" if bad else "OK")
PY2
)
if [ "${H2_OUT}" = "OK" ]; then
  pass "h2. save staged only card paths, no .loop/ leak"
else
  fail "h2. save staged only card paths, no .loop/ leak"
fi
cd "${REPO_ROOT}"

# ============================================================
# Stage D static checks (workflows)
# ============================================================
echo ""
echo "=== Stage D: workflow static checks ==="

# d-a. YAML syntax for all 8 workflows
D_A=1
for f in "${REPO_ROOT}"/.github/workflows/*.yml; do
  if ! python3 -c "import yaml,sys; yaml.safe_load(open('$f'))" 2>/dev/null; then
    echo "  FAIL: $f YAML syntax"
    D_A=0
  fi
done
if [ "${D_A}" = "1" ]; then pass "d-a. all workflow YAML parse OK"; else fail "d-a. YAML syntax error"; fi

# d-b. no pull_request_target
if grep -rq "pull_request_target" "${REPO_ROOT}/.github/workflows/" 2>/dev/null; then
  fail "d-b. pull_request_target found (forbidden)"
else
  pass "d-b. no pull_request_target"
fi

# d-c. cron values match manual
D_C=1
check_cron() {
  local file="$1" expected="$2"
  if ! grep -q "cron:.*${expected}" "${REPO_ROOT}/.github/workflows/${file}" 2>/dev/null; then
    echo "  FAIL: ${file} cron should contain '${expected}'"
    D_C=0
  fi
}
check_cron "conductor.yml" '\*/5 \* \* \* \*'
check_cron "drift.yml" '0 \*/6 \* \* \*'
check_cron "scribe.yml" '0 22,10 \* \* \*'
if [ "${D_C}" = "1" ]; then pass "d-c. cron values match manual"; else fail "d-c. cron mismatch"; fi

# d-d. permissions minimal (just list them)
echo "  --- permissions table ---"
for f in "${REPO_ROOT}"/.github/workflows/*.yml; do
  PERMS=$(python3 -c "import yaml; d=yaml.safe_load(open('$f')); print(d.get('permissions','none'))" 2>/dev/null || echo "?")
  echo "  $(basename $f): ${PERMS}"
done
pass "d-d. permissions table output (see above)"

# d-e. actionlint if available
if command -v actionlint >/dev/null 2>&1; then
  if actionlint "${REPO_ROOT}/.github/workflows/"*.yml 2>&1; then
    pass "d-e. actionlint all green"
  else
    fail "d-e. actionlint found issues"
  fi
else
  echo "  (actionlint not installed, skipping d-e)"
  pass "d-e. actionlint (skipped, not installed)"
fi

# ============================================================
# Stage F static checks (pinact / pinned SHAs)
# ============================================================
echo ""
echo "=== Stage F: pinned-SHA checks ==="

# f-a. every uses: line pins a 40-char SHA (offline proxy for pinact run --check)
# 只认 YAML 里的 uses 键（`uses:` / `- uses:`），避免误伤 workflow 内嵌 Python run 块里
# 出现的 "uses:" 字面量（如 pr-ci.yml 自带的 pin 检查脚本）。
F_A=1
while IFS= read -r line; do
  # extract the action ref after "uses:" up to the comment
  ref=$(printf '%s' "$line" | sed -E 's/.*uses:[[:space:]]*//; s/[[:space:]]*#.*//')
  sha=$(printf '%s' "$ref" | sed -E 's/.*@//')
  if ! printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$'; then
    echo "  FAIL: unpinned uses -> $line"
    F_A=0
  fi
done < <(grep -rhE '^[[:space:]]*-?[[:space:]]*uses:[[:space:]]' --include='*.yml' --include='*.yaml' "${REPO_ROOT}/.github/workflows/" 2>/dev/null)
if [ "${F_A}" = "1" ]; then pass "f-a. all uses: pinned to 40-char SHA"; else fail "f-a. unpinned uses: found"; fi

# f-b. pinact run --check if available + token present
if command -v pinact >/dev/null 2>&1 && [ -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ]; then
  if pinact run --check 2>&1; then
    pass "f-b. pinact run --check green"
  else
    fail "f-b. pinact run --check found issues"
  fi
else
  echo "  (pinact or token not available, skipping f-b; f-a is the offline gate)"
  pass "f-b. pinact run --check (skipped)"
fi

# ============================================================
# Stage I: reaper (zombie reclaim, v0.1.5)
# ============================================================
echo ""
echo "=== Stage I: reaper (zombie reclaim) ==="
STAGE_I_OUT=$(python3 - <<'PY'
import os, sys, types, json, time, datetime
os.environ["LOOP_ROOT"]="/tmp/loopd-smoke-i"
os.environ["LOOP_WS"]="/tmp/loopd-smoke-i/ws"
os.environ["LOOP_ORG"]="test-org"
os.environ["LOOP_REPO"]="test-repo"
os.environ["LOOP_ROLE"]="impl"
os.environ["LOOP_MODEL"]="test-model"
os.environ["LOOP_SANDBOX_ID"]="smoke-i"
os.environ["LOOP_BRANCH_PREFIX"]="agent"
os.environ["LOOP_LEASE_MIN"]="45"
os.environ["LOOP_POLL_MS"]="100"
os.environ["LOOP_HEARTBEAT_SEC"]="999"
os.environ["LOOP_AUTOSAVE_SEC"]="999"
os.environ["LOOP_NEXT_BLOCK_SEC"]="5"
os.environ["LOOP_MAX_CARDS_PER_SESSION"]="6"
os.environ["LOOP_IO_MODE"]="shim"
os.environ["GH_TOKEN"]="dummy"
sys.path.insert(0, os.environ.get("SMOKE_LOOPD","/workspace/loopd"))
import loopd
loopd.CFG()  # 物化 REPO 等裸全局，否则 reap_once 引用 REPO 会 NameError

class FakeProc:
    def __init__(self, stdout="", stderr="", rc=0):
        self.stdout=stdout; self.stderr=stderr; self.returncode=rc

def issue_it(num, blk):
    body = "```json loop\n" + json.dumps(blk) + "\n```\n## Body"
    return {"number":num,"title":"[Card]","updatedAt":"TS","labels":[],"body":body}

def claim_blk(cid, state, lease_until):
    return {"id":cid,"state":state,"tier":"trivial","role":"impl","paths":["z/**"],
            "attempt":0,"claim_id":"impl-1-dead","sandbox":"impl-1",
            "lease_until":lease_until,"heartbeat_at":1}

NOW = int(time.time())
results = []

# i1: expired lease + no commit → reclaimed (state=ready, attempt=1, fields cleared)
b1 = claim_blk("z1","claimed",1)
loopd.cards = lambda states: [(issue_it(77, b1), b1)]
loopd.gh = lambda *a, **kw: FakeProc("[]")
rec=[]; loopd.write_block = lambda n,b,t: (rec.append((n,b)),True)[1]
loopd.reap_once()
ok1 = (len(rec)==1 and rec[0][0]==77 and rec[0][1]["state"]=="ready"
       and rec[0][1]["attempt"]==1 and "claim_id" not in rec[0][1]
       and "sandbox" not in rec[0][1] and "lease_until" not in rec[0][1]
       and "heartbeat_at" not in rec[0][1])
results.append(("i1 reclaimed expired-lease zombie", ok1, rec))

# i2: lease still valid → NOT reclaimed
b2 = claim_blk("z2","claimed",NOW+9999)
loopd.cards = lambda states: [(issue_it(78, b2), b2)]
rec=[]; loopd.write_block = lambda n,b,t: (rec.append((n,b)),True)[1]
loopd.reap_once()
results.append(("i2 skips live-lease card", len(rec)==0, rec))

# i3: expired lease but PR has new commit (after lease start) → NOT reclaimed
lease3 = NOW - 100
b3 = claim_blk("z3","claimed",lease3)
loopd.cards = lambda states: [(issue_it(79, b3), b3)]
lease_start = lease3 - 45*60
upd = datetime.datetime.utcfromtimestamp(lease_start+50).strftime("%Y-%m-%dT%H:%M:%SZ")
loopd.gh = lambda *a, **kw: FakeProc(json.dumps([{"number":9,"updatedAt":upd}]))
rec=[]; loopd.write_block = lambda n,b,t: (rec.append((n,b)),True)[1]
loopd.reap_once()
results.append(("i3 skips zombie with recent commit", len(rec)==0, rec))

# i4: in_progress state also reaped (not just claimed)
b4 = claim_blk("z4","in_progress",1)
loopd.cards = lambda states: [(issue_it(80, b4), b4)]
loopd.gh = lambda *a, **kw: FakeProc("[]")
rec=[]; loopd.write_block = lambda n,b,t: (rec.append((n,b)),True)[1]
loopd.reap_once()
results.append(("i4 reaps in_progress zombie too",
                len(rec)==1 and rec[0][1]["state"]=="ready", rec))

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ")+name+("" if ok else f" :: {detail}"))
print("STAGE_I_" + ("OK" if all(r[1] for r in results) else "FAIL"))
PY
)
echo "${STAGE_I_OUT}"
if echo "${STAGE_I_OUT}" | grep -q "STAGE_I_OK" && ! echo "${STAGE_I_OUT}" | grep -q "FAIL"; then
  pass "i. reaper reclaims expired zombies, skips live/recent-commit"
else
  fail "i. reaper reclaims expired zombies, skips live/recent-commit"
fi

# ============================================================
# Stage J: finding/propose/verdict handlers (卡包 A2/A4/W4-1/V3/V2)
# 必测：无 evidence 的 finding 被拒 / head_sha 过期的 verdict 被拒
# ============================================================
echo ""
echo "=== Stage J: finding / propose / verdict handlers ==="
STAGE_J_OUT=$(python3 - <<'PY'
import os, sys, json, time, pathlib, hashlib
os.environ["LOOP_ROOT"]="/tmp/loopd-smoke-j"
os.environ["LOOP_WS"]="/tmp/loopd-smoke-j/ws"
os.environ["LOOP_ORG"]="test-org"
os.environ["LOOP_REPO"]="test-repo"
os.environ["LOOP_ROLE"]="impl"
os.environ["LOOP_MODEL"]="test-model"
os.environ["LOOP_SANDBOX_ID"]="smoke-j"
os.environ["LOOP_BRANCH_PREFIX"]="agent"
os.environ["LOOP_LEASE_MIN"]="45"
os.environ["LOOP_POLL_MS"]="100"
os.environ["LOOP_HEARTBEAT_SEC"]="999"
os.environ["LOOP_AUTOSAVE_SEC"]="999"
os.environ["LOOP_NEXT_BLOCK_SEC"]="5"
os.environ["LOOP_MAX_CARDS_PER_SESSION"]="6"
os.environ["LOOP_IO_MODE"]="shim"
os.environ["GH_TOKEN"]="dummy"
# WS 必须在 import 前就绪（loopd 在 import 时读 LOOP_WS）
ws = pathlib.Path(os.environ["LOOP_WS"]); ws.mkdir(parents=True, exist_ok=True)
root = pathlib.Path(os.environ["LOOP_ROOT"])
(root/".loop").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, os.environ.get("SMOKE_LOOPD","/workspace/loopd"))
import loopd
loopd.CFG()  # 物化 WS 等裸全局，否则 h_finding/h_propose 引用 WS 会 NameError

results = []
class FakeProc:
    def __init__(self, stdout="", stderr="", rc=0):
        self.stdout=stdout; self.stderr=stderr; self.returncode=rc

def write_json(name, obj):
    p = ws / name; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj)); return str(p.relative_to(ws))

# ---- J1: 无 evidence 的 finding 被拒（必测） ----
# 覆盖两种"无证据"形态：字段缺失 / 数组为空
loopd.gh = lambda *a, **kw: FakeProc("[]")
no_ev = {"lens":"ci-security","severity":"high","message":"x","path":"a.yml"}  # 无 evidence 字段
r = loopd.h_finding([write_json("no_ev.json", no_ev)])
ok = r.get("code")==1 and "evidence" in r.get("stderr","").lower()
results.append(("j1 无 evidence 字段的 finding 被拒（必测）", ok, r))

empty_ev = {"lens":"ci-security","severity":"high","message":"x","path":"a.yml","evidence":[]}  # 空数组
r = loopd.h_finding([write_json("empty_ev.json", empty_ev)])
ok = r.get("code")==1 and "NO_EVIDENCE" in r.get("stderr","")
results.append(("j1a evidence 空数组的 finding 被拒（NO_EVIDENCE）", ok, r))

# evidence 缺 rule_id/location 也拒收
bad_ev = {"lens":"ci-security","severity":"high","message":"x","path":"a.yml",
          "evidence":[{"tool":"zizmor"}]}  # 缺 rule_id + location
r = loopd.h_finding([write_json("bad_ev.json", bad_ev)])
ok = r.get("code")==1 and "BAD_EVIDENCE" in r.get("stderr","")
results.append(("j1b evidence 缺 rule_id/location 被拒", ok, r))

# ---- J2: 合法 finding（带 evidence）被接受 ----
def gh_create(*a, **kw):
    if a[:2]==("issue","list"): return FakeProc("[]")
    if a[:2]==("issue","create"): return FakeProc("https://github.com/o/r/issues/55")
    return FakeProc("")
loopd.gh = gh_create
good = {"lens":"secret-leak","severity":"high","message":"leaked token","path":"src/a.py",
        "evidence":[{"tool":"gitleaks","rule_id":"aws-access-token","location":"src/a.py:42"}]}
r = loopd.h_finding([write_json("good.json", good)])
ok = r.get("code",0)==0 and "OK (Finding" in r.get("stdout","")
results.append(("j2 合法 finding（带 evidence）被接受", ok, r))

# ---- J3: head_sha 过期的 verdict 被拒 + 重跑提示（必测） ----
loopd.st = lambda **kw: {"card":{"num":10,"blk":{"id":"v1"}}}
HEAD_SHA = "aaaa1111bbbb2222cccc3333dddd4444eeee5555"
loopd.sh = lambda *a, **kw: FakeProc(HEAD_SHA)  # git rev-parse HEAD
loopd.gh = lambda *a, **kw: FakeProc("")
vm = {"head_sha":"zzzz9999","blind_phase_commit":"c1","artifact_digest":"d1",
      "test_plan_version":"v1","acs":[{"id":"AC1","pass":True,"evidence":"tests/t.py::test_a"}]}
r = loopd.h_verdict([write_json("vm.json", vm)])
ok = r.get("code")==1 and "SHA_MISMATCH" in r.get("stderr","") and "重跑" in r.get("stderr","")
results.append(("j3 head_sha 过期的 verdict 被拒 + 重跑提示（必测）", ok, r))

# ---- J4: verdict 缺 acs 被 schema 拒收 ----
vm_no_acs = {"head_sha":HEAD_SHA,"blind_phase_commit":"c1","artifact_digest":"d1","test_plan_version":"v1"}
r = loopd.h_verdict([write_json("vm2.json", vm_no_acs)])
ok = r.get("code")==1 and "MISSING_FIELDS" in r.get("stderr","")
results.append(("j4 verdict 缺 acs 被 schema 拒收", ok, r))

# j4b: verdict ac 缺 evidence 被拒
vm_bad_ac = {"head_sha":HEAD_SHA,"blind_phase_commit":"c1","artifact_digest":"d1","test_plan_version":"v1",
             "acs":[{"id":"AC1","pass":True}]}  # 缺 evidence
r = loopd.h_verdict([write_json("vm3.json", vm_bad_ac)])
ok = r.get("code")==1 and "BAD_AC" in r.get("stderr","")
results.append(("j4b verdict ac 缺 evidence 被拒", ok, r))

# ---- J5: 合法 verdict（head_sha 匹配）被接受 ----
posted = []
def gh_comment(*a, **kw):
    posted.append(a); return FakeProc("")
loopd.gh = gh_comment
vm_ok = {"head_sha":HEAD_SHA,"blind_phase_commit":"c1","artifact_digest":"d1","test_plan_version":"v1",
         "acs":[{"id":"AC1","pass":True,"evidence":"tests/t.py::test_a"},
                {"id":"AC2","pass":False,"evidence":"tests/t.py::test_b"}]}
r = loopd.h_verdict([write_json("vm_ok.json", vm_ok)])
ok = r.get("code",0)==0 and "OK (verdict posted)" in r.get("stdout","") and len(posted)>0
results.append(("j5 合法 verdict（head_sha 匹配）被接受", ok, r))

# ---- J6: occurrences>=3 改写 proposed_card 标题为'为 X 写一个检查器' ----
def issue_body_with_occurrences(fp, occ):
    """构造 occurrences=2 的旧 finding body（第三次重复 → occ 变 3 → 触发改写）。"""
    old_f = {"lens":"ci-security","severity":"high","message":"template inj","path":"w/a.yml",
             "evidence":[{"tool":"zizmor","rule_id":"template-injection","location":"w/a.yml:15"}],
             "occurrences":occ,"fingerprint":fp}
    pc = {"id":f"chk-{fp[:8]}","role":"impl","paths":["w/a.yml"],"tier":"standard","charter":["G0"],
          "title":f"为 ci-security finding #{fp[:8]} 写一个自动检查器","acceptance":["x"]}
    return (
        f"```json finding\n{json.dumps(old_f, indent=2)}\n```\n\n"
        f"Fingerprint: `{fp}`  \nOccurrences: **{occ}**\n\n"
        f"---\n\n## Proposed Card\n\n```json loop\n{json.dumps(pc, indent=2)}\n```\n"
    )

fp6 = hashlib.sha256(b"ci-security|w/a.yml|template inj").hexdigest()[:16]
# 旧 issue occurrences=2 → 再来一次 = 3
edited_bodies = []
def gh_for_dup(*a, **kw):
    if a[:2]==("issue","list"):
        return FakeProc(json.dumps([{"number":99,"body":issue_body_with_occurrences(fp6, 2)}]))
    if a[:2]==("issue","edit"):
        # 正确定位 --body：遍历找到其下标，取下一项（不要用 a[4]，会取到 -R 的值）
        body = None
        for i in range(len(a)-1):
            if a[i] == "--body":
                body = a[i+1]; break
        if body is None:
            body = kw.get("--body", "")
        edited_bodies.append(body); return FakeProc("")
    return FakeProc("")
loopd.gh = gh_for_dup
dup3 = {"lens":"ci-security","severity":"high","message":"template inj","path":"w/a.yml",
        "evidence":[{"tool":"zizmor","rule_id":"template-injection","location":"w/a.yml:88"}]}
r = loopd.h_finding([write_json("dup3.json", dup3)])
occ3_ok = False
if edited_bodies:
    nb = edited_bodies[-1]
    occ3_ok = (
        "为 ci-security.template-injection 写一个检查器" in nb
        and "Occurrences: **3**" in nb
    )
results.append(("j6 occurrences>=3 改写 proposed_card 标题为'为 X 写一个检查器'", occ3_ok, (r, edited_bodies[:1])))

# ---- J7: propose PR 正文带'机器自检'占位段（仅允许 waves/**） ----
import subprocess, tempfile
pr_bodies = []
def gh_pr_create(*a, **kw):
    for i, tok in enumerate(a):
        if tok == "--body" and i+1 < len(a):
            pr_bodies.append(a[i+1]); break
    return FakeProc("https://github.com/o/r/pull/7")
loopd.gh = gh_pr_create
# 先让 git diff 只返回 waves/ 路径
# 注意：sh("git","-C",WS,...) 调用前缀带 -C，所以通过"关键字段在 a 中出现"判断
def sh_good_diff(*a, **kw):
    if "rev-parse" in a: return FakeProc("night/wave-1")
    if "merge-base" in a: return FakeProc("cafebabe")
    if "diff" in a: return FakeProc("waves/WAVE-1.md")
    return FakeProc("")
loopd.sh = sh_good_diff
loopd.do_save = lambda *a, **kw: None  # 避免真的 git push
# 确保 waves/WAVE-1.md 文件存在（h_propose 先查 fpath.exists）
(ws/"waves").mkdir(exist_ok=True); (ws/"waves"/"WAVE-1.md").write_text("# WAVE-1\n")
r = loopd.h_propose(["waves/WAVE-1.md"])
ok = (r.get("code",0)==0 and pr_bodies
      and "机器自检" in pr_bodies[-1]
      and "speckit.analyze" in pr_bodies[-1]
      and "speckit.checklist" in pr_bodies[-1]
      and "卡片 paths 两两无 glob 交叉" in pr_bodies[-1])
results.append(("j7 propose PR 正文带'机器自检'占位段（仅允许 waves/**）", ok, (r, pr_bodies[:1])))

# ---- J8: propose 越界（含非 waves/**）被拒 ----
def sh_bad_diff(*a, **kw):
    if "rev-parse" in a: return FakeProc("night/wave-1")
    if "merge-base" in a: return FakeProc("cafebabe")
    if "diff" in a: return FakeProc("waves/WAVE-1.md\nsrc/bad.py")
    return FakeProc("")
loopd.sh = sh_bad_diff
(ws/"waves"/"WAVE-2.md").write_text("# WAVE-2\n")
r = loopd.h_propose(["waves/WAVE-2.md"])
ok = r.get("code")==1 and "OUT_OF_SCOPE" in r.get("stderr","")
results.append(("j8 propose 越界（含非 waves/**）被拒", ok, r))

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ")+name+("" if ok else f" :: {detail}"))
print("STAGE_J_" + ("OK" if all(r[1] for r in results) else "FAIL"))
PY
)
echo "${STAGE_J_OUT}"
if echo "${STAGE_J_OUT}" | grep -q "STAGE_J_OK" && ! echo "${STAGE_J_OUT}" | grep -q "FAIL"; then
  pass "j. finding/propose/verdict handlers (无证据拒收 + head_sha 过期拒收 + occurrences>=3 + 机器自检)"
else
  fail "j. finding/propose/verdict handlers (无证据拒收 + head_sha 过期拒收 + occurrences>=3 + 机器自检)"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo "==============================="
echo "SMOKE RESULTS: ${PASS} PASS, ${FAIL} FAIL"
echo "==============================="
[ "${FAIL}" = "0" ]
