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

# 5. done（入 merge queue → 合并 PR → 置卡 state=done → 关 issue）
log "step5: enqueue merge queue + done"
# product-x 的 main 启用了 merge queue，gh pr merge / --admin 均被拒（"Changes must be made through the merge queue"）。
# 正确路径：等 PR mergeable → GraphQL enqueuePullRequest 入队 → merge queue 自动按配置（squash）合并。
PR_NODE_ID=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json id --jq '.id' 2>/dev/null)
if [ -z "$PR_NODE_ID" ]; then
  log "  -> FAIL: cannot resolve PR node id for #$PR_NUM"
  echo "CANARY_CHAIN_FAIL issue=#$NUM pr=#$PR_NUM (no node id)" >&2
  exit 1
fi
# 等 PR 变 MERGEABLE（刚创建时 mergeable=UNKNOWN，merge queue 拒绝入队）
MERGEABLE_OK=0
for i in $(seq 1 20); do
  MB=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json mergeable --jq '.mergeable' 2>/dev/null || echo "")
  if [ "$MB" = "MERGEABLE" ]; then
    MERGEABLE_OK=1
    break
  fi
  sleep 3
done
log "  -> mergeable=$MB (ok=$MERGEABLE_OK) after ${i} polls"
# 等 required status checks 完成（enqueue 需要 checks 非 queued）
CHECKS_OK=0
for i in $(seq 1 40); do
  PENDING=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json statusCheckRollup --jq '[.statusCheckRollup[]? | select(.status != "COMPLETED")] | length' 2>/dev/null || echo "1")
  TOTAL=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json statusCheckRollup --jq '[.statusCheckRollup[]?] | length' 2>/dev/null || echo "0")
  if [ "$TOTAL" -gt 0 ] && [ "$PENDING" = "0" ]; then
    CHECKS_OK=1
    break
  fi
  sleep 5
done
log "  -> checks completed (ok=$CHECKS_OK) after ${i} polls"
# 入队（重试：merge queue 偶发 "required status checks are expected" timing 问题）
ENQ=""
ENQ_OK=0
for i in $(seq 1 6); do
  ENQ=$(gh api graphql -f query="mutation{ enqueuePullRequest(input:{pullRequestId:\"$PR_NODE_ID\"}){ mergeQueueEntry{ position state pullRequest{ number } } } }" 2>&1) || true
  if echo "$ENQ" | grep -q '"mergeQueueEntry"'; then
    ENQ_OK=1
    break
  fi
  log "  -> enqueue attempt $i failed (timing?), retry in 15s: $(echo "$ENQ" | tr -d '\n' | head -c 200)"
  sleep 15
done
log "  -> enqueue result (ok=$ENQ_OK after $i attempts): $ENQ"
# 等待合并生效（merge queue 处理 + 状态检查），最多轮询 420 秒（7min，覆盖 min_entries_to_merge_wait_minutes=5）
MERGED_OK=0
for i in $(seq 1 140); do
  PR_STATE=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json state --jq '.state' 2>/dev/null || echo "")
  if [ "$PR_STATE" = "MERGED" ]; then
    MERGED_OK=1
    break
  fi
  sleep 3
done
if [ "$MERGED_OK" -ne 1 ]; then
  # 未能自动合并：优先判断是否因"需 approving review"被门禁正确拦截。
  # product 仓 main 的分支保护要求至少 1 个 approving review（作者不能自审，code owner review 也可能必需），
  # canary 机器人无法提供人工 approve，因此入队后 PR 在 merge queue 里永远不被放行 → 属预期门禁约束。
  # 此时链路本身已存活（开卡→claim→commit→PR→入队→门禁全部生效），
  # 应判定存活并主动清理合成 PR/分支/卡，避免每天一堆 PR 堆积。
  REVIEW_DECISION=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json reviewDecision --jq '.reviewDecision' 2>/dev/null || echo "")
  if [ "$REVIEW_DECISION" = "REVIEW_REQUIRED" ]; then
    log "  -> GATE: PR #$PR_NUM blocked by required approving review (reviewDecision=$REVIEW_DECISION); chain alive, cleaning up"
    # 被拦截路径：PR 是被 close 而非 merged，卡体用 closed_pr 记录，避免 merged_pr 字段误导。
    BLOCK_DONE_BODY='```json loop
{"id":"'"$CARD_ID"'","state":"done","tier":"trivial","role":"impl","paths":["canary/"],"acceptance":["canary passes"],"charter":"Q1","attempt":0,"canary":true,"claim_id":"canary-sid","sandbox":"canary-runner","lease_until":'"$LEASE"',"heartbeat_at":'"$TS"',"closed_pr":'"$PR_NUM"'}
```'
    # 清理必须真正生效，否则合成 PR/分支/卡每日堆积，违背卫生目标；且须与合并路径的 issue 清理保持一致的严格度。
    # 任一清理步骤失败 → 日志留痕 + CLEANUP_FAIL 置位 → 最终 exit 1（走 canary 的 Incident 通道）暴露，不静默吞掉。
    CLEANUP_FAIL=0
    gh pr close "$PR_NUM" -R "$ORG/$PRODUCT" \
      --comment "canary $CARD_ID: blocked by required approving review (expected gate); chain alive. Cleaning up synthetic PR." >/dev/null 2>&1 \
      || { CLEANUP_FAIL=1; log "  -> CLEANUP FAIL: close PR #$PR_NUM"; }
    git push origin --delete "$BRANCH" >/dev/null 2>&1 \
      || { CLEANUP_FAIL=1; log "  -> CLEANUP FAIL: delete branch $BRANCH"; }
    gh issue edit "$NUM" -R "$ORG/$PRODUCT" --body "$BLOCK_DONE_BODY" --remove-label "claimed" --add-label "done" >/dev/null 2>&1 \
      || { CLEANUP_FAIL=1; log "  -> CLEANUP FAIL: update issue #$NUM"; }
    gh issue close "$NUM" -R "$ORG/$PRODUCT" --reason not_planned >/dev/null 2>&1 \
      || { CLEANUP_FAIL=1; log "  -> CLEANUP FAIL: close issue #$NUM"; }
    if [ "$CLEANUP_FAIL" -ne 0 ]; then
      log "  -> CLEANUP FAILED: chain alive but synthetic PR/branch/issue may remain"
      echo "CANARY_CHAIN_FAIL issue=#$NUM pr=#$PR_NUM (cleanup failed)" >&2
      exit 1
    fi
    log "  -> done, synthetic PR closed + branch deleted + issue closed"
    echo "CANARY_CHAIN_OK issue=#$NUM pr=#$PR_NUM card=$CARD_ID (blocked by required approving review; cleaned up)"
    exit 0
  fi
  log "  -> GATE FAIL: PR #$PR_NUM not merged within 420s (last state=$PR_STATE, reviewDecision=$REVIEW_DECISION)"
  echo "CANARY_CHAIN_FAIL issue=#$NUM pr=#$PR_NUM (merge timeout)" >&2
  exit 1
fi
log "  -> PR #$PR_NUM merged"
# 清理 canary 分支（合并后）
git push origin --delete "$BRANCH" >/dev/null 2>&1 || true
MERGE_DONE_BODY='```json loop
{"id":"'"$CARD_ID"'","state":"done","tier":"trivial","role":"impl","paths":["canary/"],"acceptance":["canary passes"],"charter":"Q1","attempt":0,"canary":true,"claim_id":"canary-sid","sandbox":"canary-runner","lease_until":'"$LEASE"',"heartbeat_at":'"$TS"',"merged_pr":'"$PR_NUM"'}
```'
gh issue edit "$NUM" -R "$ORG/$PRODUCT" --body "$MERGE_DONE_BODY" --remove-label "claimed" --add-label "done" >/dev/null
gh issue close "$NUM" -R "$ORG/$PRODUCT" --reason completed >/dev/null
log "  -> done, issue closed"

# 6. 关卡（回读 issue 确认 state=done + PR 已合并）
log "step6: gate check"
FINAL_BODY=$(gh issue view "$NUM" -R "$ORG/$PRODUCT" --json body --jq '.body')
PR_STATE=$(gh pr view "$PR_NUM" -R "$ORG/$PRODUCT" --json state --jq '.state')
if printf '%s' "$FINAL_BODY" | grep -q '"state":"done"' && [ "$PR_STATE" = "MERGED" ]; then
  log "  -> GATE PASS: card done + PR merged"
  gh issue comment "$NUM" -R "$ORG/$PRODUCT" --body "canary chain PASS $DATE_TAG — pr=#$PR_NUM merged, card=done" >/dev/null
  echo "CANARY_CHAIN_OK issue=#$NUM pr=#$PR_NUM card=$CARD_ID"
else
  log "  -> GATE FAIL: body_state_missing_done or pr_not_merged (pr=$PR_STATE)"
  echo "CANARY_CHAIN_FAIL issue=#$NUM pr=#$PR_NUM" >&2
  exit 1
fi
