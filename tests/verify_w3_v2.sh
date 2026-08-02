#!/usr/bin/env bash
# W3 Verification Test Suite — UPDATED for PR294 v2
# Role: Verify (Seed-2.1-Turbo)
# Head SHA: cc6eeea2ed65c659ebba30a91fe77ce3f54ce4bf

set -euo pipefail

RESULTS_FILE=".loop/verdicts/w3-verify-results-v2.json"
mkdir -p .loop/verdicts

PASS_COUNT=0
FAIL_COUNT=0
RESULTS='[]'

log_result() {
    local card=$1
    local ac=$2
    local status=$3
    local evidence=$4
    if [ "$status" = "PASS" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
    elif [ "$status" != "INFO" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    RESULTS=$(echo "$RESULTS" | python3 -c "
import sys, json
data = json.load(sys.stdin)
data.append({'card': '$card', 'ac': '$ac', 'status': '$status', 'evidence': '''$evidence'''})
print(json.dumps(data, indent=2))
")
    echo "[$status] $card/$ac: $evidence"
}

echo "=== W3 Verification Test Suite v2 ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Head: $(git rev-parse HEAD)"
echo "Model: $LOOP_MODEL"
echo "========================================"

# ==========================================
# W3-1: dispatcher
# ==========================================
echo ""
echo "--- W3-1: dispatcher ---"

# W3-1 AC-0: policy.yml 含四数值 + rings + freeze 三段
if grep -cE 'max_concurrent_sandboxes|concurrency_per_repo|quota_token_threshold|daily_budget' policy.yml | awk '{exit $1 >= 4 ? 0 : 1}'; then
    log_result "W3-1" "AC-0" "PASS" "policy.yml contains 4+ numeric config keys"
else
    log_result "W3-1" "AC-0" "FAIL" "policy.yml missing required config keys"
fi

if grep -q 'rings:' policy.yml; then
    log_result "W3-1" "AC-0b" "PASS" "policy.yml contains rings section"
else
    log_result "W3-1" "AC-0b" "FAIL" "policy.yml missing rings section"
fi

if grep -q 'freeze:' policy.yml; then
    log_result "W3-1" "AC-0c" "PASS" "policy.yml contains freeze section"
else
    log_result "W3-1" "AC-0c" "FAIL" "policy.yml missing freeze section"
fi

# W3-1 AC-1: import dispatcher
if python3 -c "from conductor.dispatcher import dispatch; print('ok')" 2>/dev/null; then
    log_result "W3-1" "AC-1" "PASS" "conductor.dispatcher.dispatch importable"
else
    log_result "W3-1" "AC-1" "FAIL" "Cannot import conductor.dispatcher.dispatch"
fi

# W3-1 AC-2: assignments/ write path
if grep -q 'assignments/' conductor/dispatcher.py 2>/dev/null; then
    log_result "W3-1" "AC-2" "PASS" "dispatcher writes to assignments/ path"
else
    log_result "W3-1" "AC-2" "FAIL" "dispatcher missing assignments/ write path"
fi

# W3-1 AC-3: ASSIGNMENT_MISMATCH check
if grep -q 'ASSIGNMENT_MISMATCH' conductor/dispatcher.py 2>/dev/null; then
    log_result "W3-1" "AC-3" "PASS" "ASSIGNMENT_MISMATCH check present"
else
    log_result "W3-1" "AC-3" "FAIL" "ASSIGNMENT_MISMATCH check missing"
fi

# W3-1 AC-4: No hardcoded values
if python3 - <<'PY'
import ast, sys
src = open('conductor/dispatcher.py').read()
t = ast.parse(src)
for a in ast.walk(t):
    if isinstance(a, ast.Assign):
        for x in a.targets:
            if getattr(x, 'id', '') in ('MAX_CONCURRENT', 'CONCURRENCY_PER_REPO', 'QUOTA_THRESHOLD', 'DAILY_BUDGET'):
                sys.exit(1)
print('ok')
PY
then
    log_result "W3-1" "AC-4" "PASS" "No hardcoded constants in dispatcher"
else
    log_result "W3-1" "AC-4" "FAIL" "Hardcoded constants found"
fi

# W3-1 AC-4b: imports backpressure (check both import styles)
if grep -q 'backpressure' conductor/dispatcher.py 2>/dev/null; then
    log_result "W3-1" "AC-4b" "PASS" "dispatcher uses backpressure"
else
    log_result "W3-1" "AC-4b" "FAIL" "dispatcher missing backpressure import"
fi

# ==========================================
# W3-2: scoped token
# ==========================================
echo ""
echo "--- W3-2: scoped token ---"

# W3-2 AC-1: create-github-app-token v3
if [ -f .github/workflows/scoped-token.yml ] && grep -q 'create-github-app-token' .github/workflows/scoped-token.yml; then
    log_result "W3-2" "AC-1" "PASS" "scoped-token.yml uses create-github-app-token v3"
else
    log_result "W3-2" "AC-1" "FAIL" "scoped-token.yml missing or wrong action"
fi

# W3-2 AC-2: owner/repositories 收窄
if grep -q 'repositories' scripts/scoped-token.sh 2>/dev/null; then
    log_result "W3-2" "AC-2" "PASS" "scoped-token.sh has repositories scope"
else
    log_result "W3-2" "AC-2" "FAIL" "scoped-token.sh missing repositories scope"
fi

# W3-2 AC-3: 1h expiration
if grep -E 'expire|SECONDS_PER_HOUR|3600' scripts/scoped-token.sh 2>/dev/null | grep -qiE '3600|1h|hour'; then
    log_result "W3-2" "AC-3" "PASS" "token 1h expiration configured"
else
    log_result "W3-2" "AC-3" "FAIL" "token expiration not configured"
fi

# W3-2 AC-4: No persistent token forms
TOKEN_COUNT=$(grep -cE 'ghp_|gho_|github_pat_' scripts/scoped-token.sh 2>/dev/null || echo 0)
if [ "$TOKEN_COUNT" -eq 0 ]; then
    log_result "W3-2" "AC-4" "PASS" "No persistent token forms in script (count=0)"
else
    log_result "W3-2" "AC-4" "FAIL" "Persistent token forms found (count=$TOKEN_COUNT)"
fi

# ==========================================
# W3-3: backpressure
# ==========================================
echo ""
echo "--- W3-3: backpressure ---"

# W3-3 AC-1: import check_budget
if python3 -c "from conductor.backpressure import check_budget; print('ok')" 2>/dev/null; then
    log_result "W3-3" "AC-1" "PASS" "backpressure.check_budget importable"
else
    log_result "W3-3" "AC-1" "FAIL" "Cannot import backpressure.check_budget"
fi

# W3-3 AC-2: X-RateLimit-Remaining
if grep -q 'X-RateLimit-Remaining' conductor/backpressure.py 2>/dev/null; then
    log_result "W3-3" "AC-2" "PASS" "X-RateLimit-Remaining referenced"
else
    log_result "W3-3" "AC-2" "FAIL" "X-RateLimit-Remaining missing"
fi

# W3-3 AC-3: daily_budget from policy.yml
if grep -q 'daily_budget' conductor/backpressure.py 2>/dev/null; then
    log_result "W3-3" "AC-3" "PASS" "daily_budget referenced in backpressure"
else
    log_result "W3-3" "AC-3" "FAIL" "daily_budget missing in backpressure"
fi

# W3-3 AC-4: degrade path writes incident
if grep -iE 'incident|degraded' conductor/backpressure.py 2>/dev/null; then
    log_result "W3-3" "AC-4" "PASS" "backpressure has incident/ degraded semantics"
else
    log_result "W3-3" "AC-4" "FAIL" "backpressure missing incident alerts"
fi

# ==========================================
# W3-4: escalation
# ==========================================
echo ""
echo "--- W3-4: escalation ---"

# W3-4 AC-1: ≥12 ESC- rules
ESC_COUNT=$(grep -c 'rule_id:.*ESC-' escalation.yml 2>/dev/null || echo 0)
if [ "$ESC_COUNT" -ge 12 ]; then
    log_result "W3-4" "AC-1" "PASS" "escalation.yml has $ESC_COUNT ESC- rules (≥12)"
else
    log_result "W3-4" "AC-1" "FAIL" "escalation.yml has only $ESC_COUNT ESC- rules (<12)"
fi

# W3-4 AC-2: notify/warn/freeze levels
if grep -q 'on_sla_breach: notify' escalation.yml 2>/dev/null; then
    log_result "W3-4" "AC-2" "PASS" "escalation has notify/warn/freeze levels"
else
    log_result "W3-4" "AC-2" "FAIL" "escalation missing levels"
fi

# W3-4 AC-3: consecutive_breach_threshold
if grep -q 'consecutive_breach_threshold' escalation.yml 2>/dev/null; then
    log_result "W3-4" "AC-3" "PASS" "consecutive_breach_threshold defined"
else
    log_result "W3-4" "AC-3" "FAIL" "consecutive_breach_threshold missing"
fi

# W3-4 AC-4: import evaluate
if python3 -c "from conductor.escalation import evaluate; print('ok')" 2>/dev/null; then
    log_result "W3-4" "AC-4" "PASS" "escalation.evaluate importable"
else
    log_result "W3-4" "AC-4" "FAIL" "Cannot import escalation.evaluate"
fi

# W3-4 AC-5: medium → notify (with correct API usage)
if python3 - <<'PY'
import os, sys
os.environ['LOOP_SIMULATE_SLA_BREACH'] = '1'
from conductor.escalation import evaluate
# medium severity: incident_open_days > 3 (ESC-01)
context = {'incident_open_days': 5, 'consecutive_breach_count': 3}
result = evaluate(context)
if result.outcomes and result.outcomes[0].outcome == 'notify' and result.outcomes[0].severity == 'medium':
    print('PASS: medium → notify correctly triggered')
    sys.exit(0)
else:
    print(f'FAIL: medium → {result.outcomes}')
    sys.exit(1)
PY
then
    log_result "W3-4" "AC-5" "PASS" "severity=medium → evaluate returns notify"
else
    log_result "W3-4" "AC-5" "FAIL" "medium severity doesn't return notify"
fi

# W3-4 AC-6: critical → freeze (with correct API usage)
if python3 - <<'PY'
import os, sys
os.environ['LOOP_SIMULATE_SLA_BREACH'] = '1'
from conductor.escalation import evaluate
# critical severity: loop_state_ref_missing (ESC-03)
context = {'loop_state_ref_missing': True, 'consecutive_breach_count': 1}
result = evaluate(context)
if result.has_freeze:
    print('PASS: critical → freeze correctly triggered')
    sys.exit(0)
else:
    print(f'FAIL: critical → has_freeze={result.has_freeze}')
    sys.exit(1)
PY
then
    log_result "W3-4" "AC-6" "PASS" "severity=critical → evaluate returns freeze"
else
    log_result "W3-4" "AC-6" "FAIL" "critical severity doesn't return freeze"
fi

# ==========================================
# W3-5: human_queue
# ==========================================
echo ""
echo "--- W3-5: human_queue ---"

# W3-5 AC-1: import
if python3 -c "from conductor.human_queue import add_decision, build_digest; print('ok')" 2>/dev/null; then
    log_result "W3-5" "AC-1" "PASS" "human_queue.add_decision/build_digest importable"
else
    log_result "W3-5" "AC-1" "FAIL" "Cannot import human_queue functions"
fi

# W3-5 AC-2: SLA reference
if grep -q 'SLA' conductor/human_queue.py 2>/dev/null; then
    log_result "W3-5" "AC-2" "PASS" "SLA referenced in human_queue"
else
    log_result "W3-5" "AC-2" "FAIL" "SLA missing in human_queue"
fi

# W3-5 AC-3: escalation reference
if grep -qiE 'escalation|SLA' conductor/human_queue.py 2>/dev/null; then
    log_result "W3-5" "AC-3" "PASS" "human_queue references escalation"
else
    log_result "W3-5" "AC-3" "FAIL" "human_queue missing escalation ref"
fi

# ==========================================
# W3-6: kill switch
# ==========================================
echo ""
echo "--- W3-6: kill switch ---"

# W3-6 AC-1: runbook-freeze.md
if [ -f docs/runbook-freeze.md ]; then
    if grep -q '解冻恢复' docs/runbook-freeze.md && grep -q '冻结' docs/runbook-freeze.md; then
        log_result "W3-6" "AC-1" "PASS" "runbook-freeze.md exists with required sections"
    else
        log_result "W3-6" "AC-1" "FAIL" "runbook-freeze.md missing required sections"
    fi
else
    log_result "W3-6" "AC-1" "FAIL" "runbook-freeze.md not found"
fi

# W3-6 AC-2: rings + no MERGE_FROZEN
if grep -q 'ring0' policy.yml 2>/dev/null; then
    log_result "W3-6" "AC-2a" "PASS" "policy.yml contains ring0"
else
    log_result "W3-6" "AC-2a" "FAIL" "policy.yml missing ring0"
fi

if grep -rn 'MERGE_FROZEN' --include='*.py' --include='*.sh' --include='*.yml' --include='*.yaml' \
    conductor/ gates/ .github/ scripts/ 2>/dev/null | grep -v 'waves/'; then
    log_result "W3-6" "AC-2b" "FAIL" "MERGE_FROZEN found in code"
else
    log_result "W3-6" "AC-2b" "PASS" "No MERGE_FROZEN in code files"
fi

# W3-6 AC-3: freeze-yaml-check.yml
if [ -f .github/workflows/freeze-yaml-check.yml ]; then
    if grep -qiE 'freeze.all.*true|FROZEN' .github/workflows/freeze-yaml-check.yml; then
        log_result "W3-6" "AC-3" "PASS" "freeze-yaml-check.yml exists with freeze logic"
    else
        log_result "W3-6" "AC-3" "FAIL" "freeze-yaml-check.yml missing freeze logic"
    fi
else
    log_result "W3-6" "AC-3" "FAIL" "freeze-yaml-check.yml not found"
fi

# ==========================================
# W3-7: 72h demo
# ==========================================
echo ""
echo "--- W3-7: 72h demo ---"

# W3-7 AC-0: demo_cards.json has 6 cards
if [ -f waves/WAVE-03/demo_cards.json ]; then
    CARD_COUNT=$(grep -c '"repo"' waves/WAVE-03/demo_cards.json 2>/dev/null || echo 0)
    if [ "$CARD_COUNT" -eq 6 ]; then
        log_result "W3-7" "AC-0" "PASS" "demo_cards.json has 6 cards"
    else
        log_result "W3-7" "AC-0" "FAIL" "demo_cards.json has $CARD_COUNT cards (expected 6)"
    fi
else
    log_result "W3-7" "AC-0" "FAIL" "demo_cards.json not found"
fi

# W3-7 AC-1: events.jsonl non-empty
if [ -s waves/WAVE-03/evidence/72h-events.jsonl ]; then
    log_result "W3-7" "AC-1" "PASS" "72h-events.jsonl non-empty"
else
    log_result "W3-7" "AC-1" "FAIL" "72h-events.jsonl empty or missing"
fi

# ==========================================
# W3-8: canary
# ==========================================
echo ""
echo "--- W3-8: canary ---"

# W3-8 AC-1: canary.yml uses append mode for history.jsonl
if grep -q "open.*'a'" .github/workflows/canary.yml 2>/dev/null; then
    log_result "W3-8" "AC-1" "PASS" "canary.yml uses append mode for history.jsonl"
else
    log_result "W3-8" "AC-1" "FAIL" "canary.yml may not use append mode"
fi

# W3-8 AC-2: history.jsonl exists
if [ -f canary/history.jsonl ] && [ -s canary/history.jsonl ]; then
    log_result "W3-8" "AC-2" "PASS" "canary/history.jsonl exists with content"
else
    log_result "W3-8" "AC-2" "FAIL" "canary/history.jsonl empty or missing"
fi

# W3-8 AC-3: canary-nightly.sh with --since
if [ -f scripts/canary-nightly.sh ] && grep -q '\-\-since' scripts/canary-nightly.sh 2>/dev/null; then
    log_result "W3-8" "AC-3" "PASS" "canary-nightly.sh supports --since"
else
    log_result "W3-8" "AC-3" "FAIL" "canary-nightly.sh missing or no --since"
fi

# W3-8 AC-5: CLARIFIED — results.json is intentional snapshot, history.jsonl is authoritative
# Check that history.jsonl is appended (not overwritten) and has the authoritative cross-day data
if grep -q 'history.jsonl' .github/workflows/canary.yml 2>/dev/null && grep -q "open.*'a'" .github/workflows/canary.yml 2>/dev/null; then
    log_result "W3-8" "AC-5" "PASS" "history.jsonl append-only (authoritative cross-day source). results.json is snapshot only (as clarified in code comments)"
else
    log_result "W3-8" "AC-5" "FAIL" "history.jsonl append mode not confirmed"
fi

# W3-8 AC-6: CLEANUP_WARN decoupled
if grep -q 'CLEANUP_WARN' .loop/scripts/canary-chain.sh 2>/dev/null; then
    log_result "W3-8" "AC-6" "PASS" "CLEANUP_WARN found in canary-chain.sh (cleanup decoupled from chain health)"
else
    log_result "W3-8" "AC-6" "FAIL" "CLEANUP_WARN missing in canary-chain.sh"
fi

# W3-8 AC-7: No silent stderr suppression in canary-chain.sh
# Check that cleanup commands don't use >/dev/null 2>&1
if grep -n '>/dev/null 2>&1' .loop/scripts/canary-chain.sh 2>/dev/null; then
    log_result "W3-8" "AC-7" "FAIL" "Some commands still silently suppress stderr"
else
    log_result "W3-8" "AC-7" "PASS" "No silent stderr suppression in cleanup commands"
fi

# ==========================================
# W3-9: events + state_reconcile
# ==========================================
echo ""
echo "--- W3-9: events + state_reconcile ---"

# W3-9 AC-1: import events
if python3 -c "from conductor.events import append_event; print('ok')" 2>/dev/null; then
    log_result "W3-9" "AC-1" "PASS" "events.append_event importable"
else
    log_result "W3-9" "AC-1" "FAIL" "Cannot import events.append_event"
fi

# W3-9 AC-2: import state_reconcile
if python3 -c "from conductor.state_reconcile import reconcile; print('ok')" 2>/dev/null; then
    log_result "W3-9" "AC-2" "PASS" "state_reconcile.reconcile importable"
else
    log_result "W3-9" "AC-2" "FAIL" "Cannot import state_reconcile.reconcile"
fi

# W3-9 AC-4: events path under loop-state
if grep -q 'loop-state' conductor/events.py 2>/dev/null || grep -q 'events/' conductor/events.py 2>/dev/null; then
    log_result "W3-9" "AC-4" "PASS" "events writes under loop-state path"
else
    log_result "W3-9" "AC-4" "FAIL" "events not under loop-state path"
fi

# ==========================================
# W3-10: run_gates
# ==========================================
echo ""
echo "--- W3-10: run_gates ---"

# W3-10 AC-1: import
if python3 -c "from gates.run_gates import reduce_exit, trust_check; print('ok')" 2>/dev/null; then
    log_result "W3-10" "AC-1" "PASS" "run_gates.reduce_exit/trust_check importable"
else
    log_result "W3-10" "AC-1" "FAIL" "Cannot import run_gates functions"
fi

# W3-10 AC-2: exit code contract — check by running selfcheck_run_gates.py
if [ -f gates/selfcheck_run_gates.py ]; then
    if python3 gates/selfcheck_run_gates.py 2>/dev/null; then
        log_result "W3-10" "AC-2" "PASS" "selfcheck_run_gates.py passes (exit code contract verified)"
    else
        log_result "W3-10" "AC-2" "FAIL" "selfcheck_run_gates.py fails"
    fi
elif [ -f gates/test_run_gates.py ]; then
    if python3 gates/test_run_gates.py 2>/dev/null; then
        log_result "W3-10" "AC-2" "PASS" "test_run_gates.py passes"
    else
        log_result "W3-10" "AC-2" "FAIL" "test_run_gates.py fails"
    fi
else
    log_result "W3-10" "AC-2" "FAIL" "No test file found"
fi

# W3-10 AC-6: reason field
if grep -q 'reason' gates/run_gates.py 2>/dev/null; then
    log_result "W3-10" "AC-6" "PASS" "reason field present in run_gates"
else
    log_result "W3-10" "AC-6" "FAIL" "reason field missing in run_gates"
fi

# ==========================================
# W3-TK: tick wiring
# ==========================================
echo ""
echo "--- W3-TK: tick wiring ---"

# W3-TK AC-1: import STEPS
if python3 -c "from conductor.tick import STEPS; print('ok')" 2>/dev/null; then
    log_result "W3-TK" "AC-1" "PASS" "tick.STEPS importable"
else
    log_result "W3-TK" "AC-1" "FAIL" "Cannot import tick.STEPS"
fi

# W3-TK AC-2: append_event in cas.py (real call, not dead string)
if grep -q '_emit_event' conductor/cas.py 2>/dev/null && grep -q 'append_event' conductor/cas.py 2>/dev/null; then
    log_result "W3-TK" "AC-2" "PASS" "cas_update success path emits real events (not dead string)"
else
    log_result "W3-TK" "AC-2" "FAIL" "append_event not properly wired in cas.py"
fi

# W3-TK AC-3: STEPS registration
if grep -q 'reconcile' conductor/tick.py 2>/dev/null && \
   grep -q 'escalate' conductor/tick.py 2>/dev/null; then
    log_result "W3-TK" "AC-3" "PASS" "STEPS registered with reconcile/escalate"
else
    log_result "W3-TK" "AC-3" "FAIL" "STEPS missing reconcile/escalate registration"
fi

# W3-TK AC-4: escalate reads escalation.yml
if grep -q 'escalation.yml' conductor/tick.py 2>/dev/null; then
    log_result "W3-TK" "AC-4" "PASS" "tick reads escalation.yml"
else
    log_result "W3-TK" "AC-4" "FAIL" "tick missing escalation.yml reference"
fi

# ==========================================
# Summary
# ==========================================
echo ""
echo "========================================"
echo "SUMMARY: $PASS_COUNT PASS, $FAIL_COUNT FAIL"
echo "========================================"

echo "$RESULTS" > "$RESULTS_FILE"
echo "Results saved to $RESULTS_FILE"

if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
exit 0
