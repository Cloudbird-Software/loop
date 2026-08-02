#!/usr/bin/env bash
# scripts/canary-nightly.sh — canary 跨自然日累计判定（W3-8）
#
# 读取 canary/history.jsonl（append-only 跨日历史），取最近 `--since N` 个
# 自然日，判定这些天内是否每一晚的故障探针都被拦截（all_intercepted=true）。
#
# 语义（EXPLICIT，绝无假绿 — N11）：
#   - 窗口内存在任一 all_intercepted=false → FAIL，exit 1（未拦截即不绿）。
#   - 窗口内存在 >=1 个自然日且全部 all_intercepted=true → OK，exit 0。
#   - 历史过新（实际自然日少于 N）→ 仍只按实际存在日期判定，不因"数据太少"硬失败；
#     但若历史为空/无可解析行（0 个自然日）→ FAIL，exit 3（无证据不可假绿）。
#   - 每次调用输出明确 NIGHT_OK / NIGHT_FAIL 标记，供 CI/人类一眼定位。
#
# 不依赖 python：纯 bash + sed/grep，脚本自包含。
#
# 用法：
#   bash scripts/canary-nightly.sh [--since N] [--history <file>]
#     --since N      检查最近 N 个自然日（默认 3）。
#     --history P    覆盖历史文件路径（默认 canary/history.jsonl）。
#                    该参数供离线路测/负证注入（AC-4），避免污染真实 history.jsonl。
#
# ── AC-8（清扫遗留合成 canary 票·机器可读；需 gh + 对 product-x 的权限）────────
# 本脚本不主动执行该清扫（涉及跨仓写、需 CI 权限）。以下为可运行片段，供 CI/人类复核：
#   bash <<'SH'
#     START=$(git log --format=%ct --diff-filter=A -- waves/WAVE-03.md | tail -1)
#     LEFT=$(gh api 'search/issues?q=repo:cloudbird-software/product-x+label:card+is:open+created:<'$START' --jq .total_count)
#     [ "$LEFT" -eq 0 ] && echo clean && exit 0
#     exit 1
#   SH
# （LEFT：OPEN 的 canary 合成票早于本波启动=WAVE-03.md 首次引入 commit 时间戳，自动读，无需人工替换）
# 若当前环境无法验证（gh 未鉴权 / 无法触达 product-x），不得伪造 clean 结果——记录为
# "requires gh — left for CI/human"。

set -euo pipefail

SINCE=3
HIST="canary/history.jsonl"

usage() {
  echo "usage: $0 [--since N] [--history <file>]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --since)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      SINCE="$2"; shift 2
      case "$SINCE" in ''|*[!0-9]*) usage; exit 2;; esac
      [ "$SINCE" -ge 1 ] || { usage; exit 2; }
      ;;
    --history)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      HIST="$2"; shift 2
      ;;
    -h|--help)
      usage; exit 0
      ;;
    *)
      usage; exit 2
      ;;
  esac
done

if [ ! -f "$HIST" ]; then
  echo "NIGHT_FAIL: history file not found: $HIST" >&2
  exit 3
fi

# 逐行解析 date 与 all_intercepted（字段可在任意顺序，用 sed 提取）。
# 对同一自然日的多行（每小时调度会落地多行）取"任一 false 即 false"。
declare -a dates_seq=()
declare -A seen=()
declare -A intercept=()
n=0
while IFS= read -r line || [ -n "$line" ]; do
  [ -n "$line" ] || continue
  d=$(printf '%s' "$line" | sed -n 's/^.*"date"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  iv=$(printf '%s' "$line" | sed -n 's/^.*"all_intercepted"[[:space:]]*:[[:space:]]*\(true\|false\).*/\1/p')
  if [ -z "$d" ] || [ -z "$iv" ]; then
    echo "WARN: malformed history row skipped (lacks date/all_intercepted): $line" >&2
    continue
  fi
  if [ -z "${seen[$d]:-}" ]; then
    seen[$d]=1
    dates_seq+=("$d")
    intercept[$d]="$iv"
  else
    [ "$iv" = "false" ] && intercept[$d]="false"
  fi
done < "$HIST"

total=${#dates_seq[@]}
if [ "$total" -eq 0 ]; then
  echo "NIGHT_FAIL: no parseable date/all_intercepted rows in $HIST — cannot confirm interception (no fake-green)" >&2
  exit 3
fi

# 最近 N 个自然日：取 dates_seq 末尾 min(total, SINCE) 个
start=$(( total - SINCE ))
[ "$start" -lt 0 ] && start=0
eval_count=$(( total - start ))

echo "canary-nightly: evaluating last $eval_count of $total distinct date(s) (--since $SINCE) from $HIST"

fail=""
for ((i = start; i < total; i++)); do
  d="${dates_seq[$i]}"
  iv="${intercept[$d]}"
  echo "  $d -> all_intercepted=$iv"
  if [ "$iv" = "false" ]; then
    fail="${fail:+$fail }$d"
  fi
done

if [ -n "$fail" ]; then
  echo "NIGHT_FAIL: not intercepted on date(s) within last $eval_count day(s): ${fail}" >&2
  exit 1
fi

echo "NIGHT_OK: all rows for the last $eval_count date(s) were intercepted"
exit 0