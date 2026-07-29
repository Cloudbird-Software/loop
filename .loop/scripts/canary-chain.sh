#!/usr/bin/env bash
# .loop/scripts/canary-chain.sh — 合成工单走完整链路（开卡→claim→commit→PR→done→关卡）
#
# 任一步失败 → exit 非 0，由 canary.yml 的 if: failure() 步开 Incident 并 @人类。
# 全程留痕：每步写日志到 .loop/logs/canary-<ts>.log，并在 issue 上贴评论。
set -euo pipefail

ORG="${LOOP_ORG:?LOOP_ORG required}"
PRODUCT="${LOOP_PRODUCT:?LOOP_PRODUCT required}"
HUMAN="${LOOP_HUMAN:-}"
TS="$(date +%s)"
CARD_ID="canary-${TS}"
BRANCH="canary/${CARD_ID}"
DATE_TAG="$(date -u +%Y%m%dT%H%M%SZ)"
LOGDIR="${GITHUB_WORKSPACE:-.}/.loop/logs"
TRACE_FILE="${LOGDIR}/canary-${TS}.log"
mkdir -p "$LOGDIR"

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$TRACE_FILE" >&2; }

# 配置 git 凭据助手：让 git push 走 gh 的 token（GH_TOKEN）
gh auth setup-git >/dev/null 2>&1 || true

# 确保辅助标签存在（issue type 由 Card 提供，label 仅作筛选辅助）
ensure_label() {
  local name="$1" color="$2" repo="$3"
  gh label create "$name" -R "$repo" --color "$color" 2>/dev/null \
    || gh label edit "$name" -R "$repo" --color "$color" 2>/dev/null \
    || true
}
ensure_label "card"    "1d76db" "$ORG/$PRODUCT"
ensure_label "claimed" "fbca04" "$ORG/$PRODUCT"
ensure_label "done"    "0e8a16" "$ORG/$PRODUCT"

# 1. 开卡
log "step1: open canary card $CARD_ID"
BODY='```json loop
{"id":"'"$CARD_ID"'","state":"ready","tier":"trivial","role":"impl","paths":["canary/"],"acceptance":["canary passes"],"charter":"Q1","attempt":0,"canary":true}
```'
ISSUE_URL=$(gh issue create -R "$ORG/$PRODUCT" --title "canary: synthetic ticket $CARD_ID" --label "card" --body "$BODY")
NUM=$(printf '%s' "$ISSUE_URL" | grep -oE '[0-9]+$')
log "  -> issue #$NUM ($ISSUE_URL)"
gh issue comment "$NUM" -R "$ORG/$PRODUCT" --body "canary chain start $DATE_TAG" >/dev/null

# 2. claim（编辑 issue body 置 state=claimed + lease_until + heartbeat）
log "step2: claim #$NUM"
LEASE=$((TS + 2700))
CLAIM_BODY='```json loop
{"id":"'"$CARD_ID"'","state":"claimed","tier":"trivial","role":"impl","paths":["canary/"],"acceptance":["canary passes"],"charter":"Q1","attempt":0,"canary":true,"claim_id":"canary-sid","sandbox":"canary-runner","lease_until":'"$LEASE"',"heartbeat_at":'"$TS"'}
```'
gh issue edit "$NUM" -R "$ORG/$PRODUCT" --body "$CLAIM_BODY" --add-label "claimed" >/dev/null
log "  -> claimed (lease_until=$LEASE)"

# 3. commit（clone product-x → 建 canary 分支 → 小文件 → push）
log "step3: commit on branch $BRANCH"
WORKDIR="$(mktemp -d)"
gh repo clone "$ORG/$PRODUCT" "$WORKDIR/repo" -- --depth 1
cd "$WORKDIR/repo"
git config user.name  "loop-canary-bot"
git config user.email "canary-bot@users.noreply.github.com"
git checkout -b "$BRANCH"
mkdir -p canary
echo "canary trace $CARD_ID at $(date -u +%FT%TZ)" > "canary/${CARD_ID}.txt"
git add "canary/${CARD_ID}.txt"
git commit -q -m "canary: synthetic commit $CARD_ID"
git push -q origin "$BRANCH"
log "  -> pushed $BRANCH"

# 4. PR
log "step4: open PR"
PR_URL=$(gh pr create -R "$ORG/$PRODUCT" --head "$BRANCH" --base main \
  --title "canary: $CARD_ID" --body "Synthetic canary ticket for chain liveness. Auto-merge expected.")
PR_NUM=$(printf '%s' "$PR_URL" | grep -oE '[0-9]+$')
log "  -> PR #$PR_NUM ($PR_URL)"

# 5. done（合并 PR + 置卡 state=done + 关 issue）
log "step5: merge PR + done"
# admin 合并绕过 branch protection（canary 是合成工单，无需 review）
gh pr merge "$PR_NUM" -R "$ORG/$PRODUCT" --squash --delete-branch --admin >/dev/null \
  || gh pr merge "$PR_NUM" -R "$ORG/$PRODUCT" --squash --delete-branch >/dev/null
DONE_BODY='```json loop
{"id":"'"$CARD_ID"'","state":"done","tier":"trivial","role":"impl","paths":["canary/"],"acceptance":["canary passes"],"charter":"Q1","attempt":0,"canary":true,"claim_id":"canary-sid","sandbox":"canary-runner","lease_until":'"$LEASE"',"heartbeat_at":'"$TS"',"merged_pr":'"$PR_NUM"'}
```'
gh issue edit "$NUM" -R "$ORG/$PRODUCT" --body "$DONE_BODY" --remove-label "claimed" --add-label "done" >/dev/null
gh issue close "$NUM" -R "$ORG/$PRODUCT" --reason completed >/dev/null
log "  -> done, issue closed"

# 6. 关卡（回读 issue 确认 state=done + PR 已合并）
log "step6: gate check"
FINAL_BODY=$(gh issue view "$NUM" -R "$ORG/$PRODUCT" --json body --jq '.body')
PR_STATE=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json state,merged --jq '.state + "/" + (.merged|tostring)')
if printf '%s' "$FINAL_BODY" | grep -q '"state":"done"' && printf '%s' "$PR_STATE" | grep -q "MERGED/true"; then
  log "  -> GATE PASS: card done + PR merged"
  gh issue comment "$NUM" -R "$ORG/$PRODUCT" --body "canary chain PASS $DATE_TAG — pr=#$PR_NUM merged, card=done" >/dev/null
  echo "CANARY_CHAIN_OK issue=#$NUM pr=#$PR_NUM card=$CARD_ID"
else
  log "  -> GATE FAIL: body_state_missing_done or pr_not_merged (pr=$PR_STATE)"
  echo "CANARY_CHAIN_FAIL issue=#$NUM pr=#$PR_NUM" >&2
  exit 1
fi
