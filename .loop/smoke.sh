#!/usr/bin/env bash
# .loop/smoke.sh — loopd 本地冒烟测试
# 覆盖：py_compile / relay status / unknown verb / file mode / RETIRE / help
# 只测 relay/IO/参数层，不触真实 GitHub。
set -uo pipefail

PASS=0; FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOOPD="${REPO_ROOT}/loopd/loopd.py"
SHIM="${REPO_ROOT}/loopd/loop"

# 临时环境
TMPROOT=$(mktemp -d)
TMPWS="${TMPROOT}/ws"
mkdir -p "${TMPROOT}/.loop/relay/inbox" "${TMPROOT}/.loop/relay/outbox" "${TMPROOT}/.loop/relay/done" "${TMPROOT}/.loop/logs" "${TMPROOT}/.loop/trash" "${TMPROOT}/.loop/audit"
mkdir -p "${TMPWS}/.loop/relay/inbox" "${TMPWS}/.loop/relay/outbox" "${TMPWS}/.loop/relay/done" "${TMPWS}/.loop/logs" "${TMPWS}/.loop/trash" "${TMPWS}/.loop/audit"

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
export LOOP_IO_MODE="shim"
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
# a. py_compile
# ============================================================
if python3 -m py_compile "${LOOPD}" "${SHIM}" 2>/dev/null; then
  pass "a. py_compile loopd.py + loop"
else
  fail "a. py_compile loopd.py + loop"
fi

# ============================================================
# 启动 daemon（后续测试共用）
# ============================================================
python3 "${LOOPD}" &
DAEMON_PID=$!
sleep 1  # 等线程起来

# ============================================================
# b. relay status → code=0 within 3s
# ============================================================
RID="b-$(date +%s%N | tail -c 7)"
REQ="{\"id\":\"${RID}\",\"intent\":\"status\",\"args\":[],\"cwd\":\"${TMPWS}\",\"ts\":$(date +%s)}"
echo "${REQ}" > "${TMPROOT}/.loop/relay/inbox/${RID}.json"
B_OK=0
for i in $(seq 1 30); do  # 3 seconds, 100ms each
  if [ -f "${TMPROOT}/.loop/relay/outbox/${RID}.json" ]; then
    CODE=$(python3 -c "import json; print(json.load(open('${TMPROOT}/.loop/relay/outbox/${RID}.json'))['code'])" 2>/dev/null || echo "?")
    if [ "${CODE}" = "0" ]; then B_OK=1; fi
    break
  fi
  sleep 0.1
done
if [ "${B_OK}" = "1" ]; then pass "b. relay status returns code=0"; else fail "b. relay status returns code=0"; fi

# ============================================================
# c. unknown verb → code=64, stderr contains UNKNOWN_VERB
# ============================================================
RID="c-$(date +%s%N | tail -c 7)"
REQ="{\"id\":\"${RID}\",\"intent\":\"frobnicate\",\"args\":[],\"cwd\":\"${TMPWS}\",\"ts\":$(date +%s)}"
echo "${REQ}" > "${TMPROOT}/.loop/relay/inbox/${RID}.json"
C_OK=0
for i in $(seq 1 30); do
  if [ -f "${TMPROOT}/.loop/relay/outbox/${RID}.json" ]; then
    CODE=$(python3 -c "import json; print(json.load(open('${TMPROOT}/.loop/relay/outbox/${RID}.json'))['code'])" 2>/dev/null || echo "?")
    STDERR=$(python3 -c "import json; print(json.load(open('${TMPROOT}/.loop/relay/outbox/${RID}.json'))['stderr'])" 2>/dev/null || echo "")
    if [ "${CODE}" = "64" ] && echo "${STDERR}" | grep -q "UNKNOWN_VERB"; then C_OK=1; fi
    break
  fi
  sleep 0.1
done
if [ "${C_OK}" = "1" ]; then pass "c. unknown verb returns code=64 + UNKNOWN_VERB"; else fail "c. unknown verb returns code=64 + UNKNOWN_VERB"; fi

# ============================================================
# d. file mode: IN.json → OUT.md done
# ============================================================
# 先杀掉旧 daemon，换 file 模式重启
kill "${DAEMON_PID}" 2>/dev/null; wait "${DAEMON_PID}" 2>/dev/null; DAEMON_PID=""
sleep 0.5

export LOOP_IO_MODE="file"
# 清理旧 OUT.md
rm -f "${TMPROOT}/.loop/OUT.md" "${TMPROOT}/.loop/IN.json"

python3 "${LOOPD}" &
DAEMON_PID=$!
sleep 1

# 写 IN.json
echo '{"intent":"status","args":[]}' > "${TMPROOT}/.loop/IN.json"
D_OK=0
for i in $(seq 1 30); do
  if [ -f "${TMPROOT}/.loop/OUT.md" ]; then
    STATUS=$(head -1 "${TMPROOT}/.loop/OUT.md" 2>/dev/null || echo "")
    if echo "${STATUS}" | grep -q "status: done"; then D_OK=1; fi
    break
  fi
  sleep 0.1
done
if [ "${D_OK}" = "1" ]; then pass "d. file mode IN.json → OUT.md done"; else fail "d. file mode IN.json → OUT.md done"; fi

# 杀掉 file-mode daemon
kill "${DAEMON_PID}" 2>/dev/null; wait "${DAEMON_PID}" 2>/dev/null; DAEMON_PID=""
sleep 0.5

# ============================================================
# e. LOOP_MAX_CARDS_PER_SESSION=0 → next returns RETIRE
# ============================================================
export LOOP_IO_MODE="shim"
export LOOP_MAX_CARDS_PER_SESSION="0"
# 清理 relay
rm -f "${TMPROOT}/.loop/relay/inbox/"*.json "${TMPROOT}/.loop/relay/outbox/"*.json 2>/dev/null

python3 "${LOOPD}" &
DAEMON_PID=$!
sleep 1

RID="e-$(date +%s%N | tail -c 7)"
REQ="{\"id\":\"${RID}\",\"intent\":\"next\",\"args\":[],\"cwd\":\"${TMPWS}\",\"ts\":$(date +%s)}"
echo "${REQ}" > "${TMPROOT}/.loop/relay/inbox/${RID}.json"
E_OK=0
for i in $(seq 1 30); do
  if [ -f "${TMPROOT}/.loop/relay/outbox/${RID}.json" ]; then
    STDOUT=$(python3 -c "import json; print(json.load(open('${TMPROOT}/.loop/relay/outbox/${RID}.json'))['stdout'])" 2>/dev/null || echo "")
    if echo "${STDOUT}" | grep -q "RETIRE"; then E_OK=1; fi
    break
  fi
  sleep 0.1
done
if [ "${E_OK}" = "1" ]; then pass "e. LOOP_MAX_CARDS_PER_SESSION=0 → next returns RETIRE"; else fail "e. LOOP_MAX_CARDS_PER_SESSION=0 → next returns RETIRE"; fi

# ============================================================
# f. loop help prints verb table
# ============================================================
# 通过 relay 发 help intent，检查输出含动词表关键行
RID="f-$(date +%s%N | tail -c 7)"
REQ="{\"id\":\"${RID}\",\"intent\":\"help\",\"args\":[],\"cwd\":\"${TMPWS}\",\"ts\":$(date +%s)}"
echo "${REQ}" > "${TMPROOT}/.loop/relay/inbox/${RID}.json"
F_OK=0
for i in $(seq 1 30); do
  if [ -f "${TMPROOT}/.loop/relay/outbox/${RID}.json" ]; then
    STDOUT=$(python3 -c "import json; print(json.load(open('${TMPROOT}/.loop/relay/outbox/${RID}.json'))['stdout'])" 2>/dev/null || echo "")
    # 检查动词表关键行
    if echo "${STDOUT}" | grep -q "next" && \
       echo "${STDOUT}" | grep -q "save" && \
       echo "${STDOUT}" | grep -q "done" && \
       echo "${STDOUT}" | grep -q "retire" && \
       echo "${STDOUT}" | grep -q "status"; then F_OK=1; fi
    break
  fi
  sleep 0.1
done
if [ "${F_OK}" = "1" ]; then pass "f. help prints verb table"; else fail "f. help prints verb table"; fi

# ============================================================
# g. 部署模拟：按 bootstrap 逻辑把 loopd/ 装进临时目录，
#    loopd --daemon 能起、loop run logs.tail 不返回 UNKNOWN_INTENT
# ============================================================
# 先杀掉之前的 daemon，避免争抢同一个 relay inbox
if [ -n "${DAEMON_PID:-}" ] && kill -0 "${DAEMON_PID}" 2>/dev/null; then
  kill "${DAEMON_PID}" 2>/dev/null || true; wait "${DAEMON_PID}" 2>/dev/null || true
fi
DAEMON_PID=""

DEPLOY="${TMPROOT}/deploy"
mkdir -p "${DEPLOY}/bin" "${DEPLOY}/etc/loopd"
install -m 0755 "${REPO_ROOT}/loopd/loopd.py" "${DEPLOY}/bin/loopd"
install -m 0755 "${REPO_ROOT}/loopd/loop" "${DEPLOY}/bin/loop"
install -m 0644 "${REPO_ROOT}/loopd/intents.yaml" "${DEPLOY}/etc/loopd/intents.yaml"

# 用部署目录里的 loopd/loop（PATH 前置）；intents 走 LOOPD_INTENTS_PATH（第一候选）
export PATH="${DEPLOY}/bin:${PATH}"
export LOOPD_INTENTS_PATH="${DEPLOY}/etc/loopd/intents.yaml"
# logs.tail 指向 .loop/logs/app.log（相对 WS），建一个空文件让 tail 成功
touch "${TMPWS}/.loop/logs/app.log"
# 清理 relay，避免残留请求干扰
rm -f "${TMPROOT}/.loop/relay/inbox/"*.json "${TMPROOT}/.loop/relay/outbox/"*.json 2>/dev/null

# g1. loopd --daemon 能起
loopd --daemon &
DAEMON_PID=$!
sleep 1
if kill -0 "${DAEMON_PID}" 2>/dev/null; then
  pass "g1. loopd --daemon starts (deployed binary)"
else
  fail "g1. loopd --daemon starts (deployed binary)"
fi

# g2. loop run logs.tail 不返回 UNKNOWN_INTENT（走部署的 loop shim + loopd daemon）
G2_OUT=$(loop run logs.tail 2>&1 || true)
if echo "${G2_OUT}" | grep -q "UNKNOWN_INTENT"; then
  fail "g2. loop run logs.tail not UNKNOWN_INTENT"
else
  pass "g2. loop run logs.tail not UNKNOWN_INTENT"
fi

# 杀掉部署 daemon，还原 PATH / LOOPD_INTENTS_PATH，避免影响后续静态检查
kill "${DAEMON_PID}" 2>/dev/null || true; wait "${DAEMON_PID}" 2>/dev/null || true; DAEMON_PID=""
export PATH="${PATH#${DEPLOY}/bin:}"
unset LOOPD_INTENTS_PATH

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
F_A=1
while IFS= read -r line; do
  # extract the action ref after "uses:" up to the comment
  ref=$(printf '%s' "$line" | sed -E 's/.*uses:[[:space:]]*//; s/[[:space:]]*#.*//')
  sha=$(printf '%s' "$ref" | sed -E 's/.*@//')
  if ! printf '%s' "$sha" | grep -Eq '^[0-9a-f]{40}$'; then
    echo "  FAIL: unpinned uses -> $line"
    F_A=0
  fi
done < <(grep -rhE 'uses:' "${REPO_ROOT}/.github/workflows/" 2>/dev/null)
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
# Summary
# ============================================================
echo ""
echo "==============================="
echo "SMOKE RESULTS: ${PASS} PASS, ${FAIL} FAIL"
echo "==============================="
[ "${FAIL}" = "0" ]
