#!/usr/bin/env bash
# .loop/scripts/canary-survival.sh — 26 小时存活自检
#
# 检查 audit/export/canary 三类 workflow 最近一次成功运行时间；
# 任一超过 26 小时（或从未成功）→ 开 Incident 并 @人类。
#
# 映射（loop 仓库无独立 audit.yml）：
#   canary  → canary.yml
#   export  → scribe.yml（全量导出 + 日报）
#   audit   → drift.yml（ruleset 漂移 / policy 审计）
set -euo pipefail

ORG="${LOOP_ORG:?LOOP_ORG required}"
LOOP_REPO="${LOOP_REPO:-loop}"
HUMAN="${LOOP_HUMAN:-}"
THRESH_SEC=$((26 * 3600))
NOW=$(date +%s)
ALERTS=""

# 确保辅助标签存在
gh label create "incident" -R "$ORG/$LOOP_REPO" --color b60205 --if-not-exists 2>/dev/null || true

check_wf() {
  local repo="$1" wf="$2" label="$3"
  local last
  last=$(gh run list -R "$repo" --workflow "$wf" --status success --limit 1 \
          --json updatedAt --jq '.[0].updatedAt // empty' 2>/dev/null || true)
  if [ -z "$last" ]; then
    ALERTS="${ALERTS}- ${label} (${wf} @ ${repo}): no successful run ever
"
    return
  fi
  local last_ts age
  last_ts=$(date -u -d "$last" +%s 2>/dev/null || echo 0)
  age=$((NOW - last_ts))
  if [ "$age" -gt "$THRESH_SEC" ]; then
    ALERTS="${ALERTS}- ${label} (${wf} @ ${repo}): last success ${last} ($((age/3600))h ago, > 26h)
"
  fi
}

check_wf "$ORG/$LOOP_REPO" "canary.yml" "canary"
check_wf "$ORG/$LOOP_REPO" "scribe.yml" "export"
check_wf "$ORG/$LOOP_REPO" "drift.yml"  "audit"

if [ -n "$ALERTS" ]; then
  echo "SURVIVAL_ALERT: one or more workflows stale > 26h:"
  echo "$ALERTS"
  MENTION="${HUMAN:+@$HUMAN }"
  # 开 Incident（issue type = Incident；label 辅助）
  INC_URL=$(gh issue create -R "$ORG/$LOOP_REPO" \
    --title "Incident: 26h survival check failed @ $(date -u +%FT%TZ)" \
    --label "incident" \
    --body "${MENTION}Canary 26h survival self-check failed. The following workflows have not succeeded within 26 hours:

${ALERTS}
Action: inspect the named workflow runs; if conductor is down, restart it. This incident was opened automatically by canary-survival.sh." 2>/dev/null || echo "")
  echo "INCIDENT_OPENED: ${INC_URL:-<failed>}"
  exit 1
fi

echo "SURVIVAL_OK: canary/export/audit all within 26h"
