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
# Summary
# ============================================================
echo ""
echo "==============================="
echo "SMOKE RESULTS: ${PASS} PASS, ${FAIL} FAIL"
echo "==============================="
[ "${FAIL}" = "0" ]
