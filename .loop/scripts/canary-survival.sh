#!/usr/bin/env bash
# .loop/scripts/canary-survival.sh — 26 小时存活自检（R10-6：指纹去重）
#
# 检查 audit/export/canary 三类 workflow 最近一次成功运行时间；
# 任一超过 26 小时（或从未成功）→ 开 Incident 并 @人类。
#
# R10-6 改动：Incident 标题含稳定指纹（基于哪些 workflow 滞后，非时间戳）。
# 同指纹已有 open Incident 时追加评论而非新开，终结"每次跑都开一张"的噪声。
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
STALE_NAMES=""

# 确保辅助标签存在
ensure_label() {
  local name="$1" color="$2" repo="$3"
  gh label create "$name" -R "$repo" --color "$color" 2>/dev/null \
    || gh label edit "$name" -R "$repo" --color "$color" 2>/dev/null \
    || true
}
ensure_label "incident" "b60205" "$ORG/$LOOP_REPO"

check_wf() {
  local repo="$1" wf="$2" label="$3"
  local last
  last=$(gh run list -R "$repo" --workflow "$wf" --status success --limit 1 \
          --json updatedAt --jq '.[0].updatedAt // empty' 2>/dev/null || true)
  if [ -z "$last" ]; then
    ALERTS="${ALERTS}- ${label} (${wf} @ ${repo}): no successful run ever
"
    STALE_NAMES="${STALE_NAMES}${label} "
    return
  fi
  local last_ts age
  last_ts=$(date -u -d "$last" +%s 2>/dev/null || echo 0)
  age=$((NOW - last_ts))
  if [ "$age" -gt "$THRESH_SEC" ]; then
    ALERTS="${ALERTS}- ${label} (${wf} @ ${repo}): last success ${last} ($((age/3600))h ago, > 26h)
"
    STALE_NAMES="${STALE_NAMES}${label} "
  fi
}

check_wf "$ORG/$LOOP_REPO" "canary.yml" "canary"
check_wf "$ORG/$LOOP_REPO" "scribe.yml" "export"
check_wf "$ORG/$LOOP_REPO" "drift.yml"  "audit"

if [ -z "$ALERTS" ]; then
  echo "SURVIVAL_OK: canary/export/audit all within 26h"
  exit 0
fi

# ── R10-6：稳定指纹（基于滞后的 workflow 名，非时间戳）──────────────────
STALE_SORTED=$(echo -n "$STALE_NAMES" | tr ' ' '\n' | grep -v '^$' | sort | tr '\n' ' ')
FP=$(echo -n "$STALE_SORTED" | sha256sum | cut -c1-8)
TITLE="Incident: 26h survival check failed [fp=${FP}]"

echo "SURVIVAL_ALERT: one or more workflows stale > 26h (fp=${FP}):"
echo "$ALERTS"

MENTION="${HUMAN:+@$HUMAN }"

# 按指纹查重：已有 open 同指纹 Incident → 追加评论，不新开
EXISTING=$(gh issue list -R "$ORG/$LOOP_REPO" --state open \
  --search "fp=${FP} in:title" --json number,title --limit 10 \
  --jq ".[] | select(.title | contains(\"fp=${FP}\")) | .number" 2>/dev/null | head -1 || true)

if [ -n "$EXISTING" ]; then
  echo "DEDUP: found existing Incident #${EXISTING} with fp=${FP}, appending comment"
  TS=$(date -u +%FT%TZ)
  gh issue comment "$EXISTING" -R "$ORG/$LOOP_REPO" --body \
    "${MENTION}**Survival check still failing** @ ${TS} (fp=${FP})

${ALERTS}
*No new incident opened — same fingerprint. (R10-6 dedup)*" 2>/dev/null || true
  echo "APPENDED to #${EXISTING}"
  exit 1
fi

# 新开 Incident（标题含稳定指纹前缀）
INC_URL=$(gh issue create -R "$ORG/$LOOP_REPO" \
  --title "$TITLE" \
  --label "incident" \
  --body "${MENTION}Canary 26h survival self-check failed (fp=${FP}).

The following workflows have not succeeded within 26 hours:

${ALERTS}
**Fingerprint**: \`fp=${FP}\` (stable — same stale workflows = same fp)
Action: inspect the named workflow runs; if conductor is down, restart it. This incident was opened automatically by canary-survival.sh." 2>/dev/null || echo "")
echo "INCIDENT_OPENED: ${INC_URL:-<failed>} (fp=${FP})"
exit 1
