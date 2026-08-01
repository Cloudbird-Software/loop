#!/usr/bin/env bash
# lenses/lens-pat-scan.sh — PAT 形态凭据扫描确定性检查器（W0-7，CHARTER N15 配套）。
#
# 来源：W0-7。本卡已把 workflow 中 GH_TOKEN/SCRIBE_GH_TOKEN 改为 Conductor App 铸造
# （N15：能用 App 的绝不用 PAT）。本镜头静态扫描仓库内是否残留 PAT 形态凭据字符串，
# 命中即非零退出——不依赖任何 LLM，结果确定（R12-6 信任单调下降）。
#
# 覆盖 PAT 形态：
#   ghp_        classic personal access token   (36 个 [A-Za-z0-9] 跟在前缀后)
#   github_pat_ fine-grained PAT                (82 个 [A-Za-z0-9_] 跟在前缀后)
#   gho_        OAuth token                     (36 个 [A-Za-z0-9] 跟在前缀后)
#   ghu_        user-to-server token            (36 个 [A-Za-z0-9] 跟在前缀后)
#   ghs_        server-to-server token          (36 个 [A-Za-z0-9] 跟在前缀后)
# 占位符（ghp_<...>、ghp_YOUR_TOKEN、长度不足）天然不匹配完整正则，自动排除，不会误报。
#
# 契约：exit 0 = 未发现 PAT 形态凭据；exit 1 = 发现 PAT 形态凭据；exit 2 = 执行失败。
# 铁律（CHARTER N5/N11）：命中即诚实地 exit 1，不使用 `|| true` / `set +e` 吞退出码假绿。
# 输出：lens 证据信封 JSON 到 stdout（findings 数组列出每处命中）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT"

LENS="pat-scan"
# 完整长度正则：前缀 + 规定字符数。占位符长度不足，不匹配。
PAT_REGEX='ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{82}|gho_[A-Za-z0-9]{36}|ghu_[A-Za-z0-9]{36}|ghs_[A-Za-z0-9]{36}'

# 扫描仓库：-I 跳过二进制，-n 行号，-o 仅输出匹配，-E 扩展正则，-r 递归。
# 排除 .git/（版本库元数据）与本镜头自身（正则字面量自命中防御）。
# grep 退出码：0=有匹配，1=无匹配，2=工具错误。1 是正常「无发现」，2 才是执行失败。
# 用 `|| grep_rc=$?` 捕获退出码（非 `|| true`），保留码值供后续判断。
SCAN_OUTPUT=""
grep_rc=0
SCAN_OUTPUT=$(grep -rInoE "$PAT_REGEX" . --exclude-dir=.git --exclude=lens-pat-scan.sh) || grep_rc=$?

# 有命中时优先上报（即使 grep 也报了非致命错误，也绝不掩盖真实 PAT）。
count=0
findings_json=""
if [ -n "$SCAN_OUTPUT" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    # 行格式：./path:lineno:match （match 仅含 [A-Za-z0-9_]，不含冒号）
    path="${line%%:*}"
    rest="${line#*:}"
    lineno="${rest%%:*}"
    match="${rest#*:}"
    path="${path#./}"
    if [ "$count" -gt 0 ]; then
      findings_json+=","
    fi
    findings_json+="{\"path\":\"$path\",\"line\":$lineno,\"match\":\"$match\"}"
    count=$((count+1))
  done <<< "$SCAN_OUTPUT"
fi

echo "{\"lens\":\"$LENS\",\"shard\":\"S1\",\"generated_at\":\"$(date -Iseconds)\",\"findings\":[$findings_json]}"

if [ "$count" -gt 0 ]; then
  echo "pat-scan: 发现 $count 个 PAT 形态凭据命中（见上方 findings）" >&2
  exit 1
fi

# 无命中：若 grep 因工具错误（rc>=2）未能完成扫描，诚实地报执行失败，不假绿。
if [ "$grep_rc" -ge 2 ]; then
  echo "LENS_NOT_EXECUTED: grep 退出码 $grep_rc（工具错误，扫描未完成）" >&2
  exit 2
fi

echo "pat-scan OK: 未发现 PAT 形态凭据" >&2
exit 0
