#!/usr/bin/env bash
# lenses/no-fake-green.sh — 确定性检查器（R12-6 固化案例 #1）
#
# 来源：审查裁决 P1-1（audit）。强模型曾指控工作流存在吞错假绿，经独立复现坐实。
# 本检查器把该判断从「模型说了算」降级为「无 LLM 参与的静态扫描」——
# 系统对模型的信任单调下降（R12-6 / CHARTER N5）。
#
# 契约：exit 0 = 未发现缺陷；exit 1 = 发现缺陷；exit 2 = 执行失败（GATE_NOT_EXECUTED）。
# 例外：行内或上一行写明 `fake-green-ok: <理由>` 视为可追溯的正当例外，不计入缺陷。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
WF_DIR="$ROOT/.github/workflows"

if [ ! -d "$WF_DIR" ]; then
  echo "GATE_NOT_EXECUTED: $WF_DIR not found" >&2
  exit 2
fi

# 命中即缺陷的吞错模式
patterns=(
  '\|\| *true'
  'set +e'
  'continue-on-error: *true'
  '2>/dev/null *&& *echo'
)

hits=0
while IFS= read -r f; do
  [ -z "$f" ] && continue
  lineno=0
  prev=""
  while IFS= read -r line; do
    lineno=$((lineno+1))
    # 跳过注释行：YAML/Shell 注释里描述禁令的文字不应被误判为缺陷
    stripped="${line#"${line%%[![:space:]]*}"}"
    case "$stripped" in
      \#*) prev="$line"; continue ;;
    esac
    for pat in "${patterns[@]}"; do
      if printf '%s' "$line" | grep -Eq "$pat"; then
        # 检查本行或上一行是否有 fake-green-ok 例外标注
        if printf '%s\n%s' "$line" "$prev" | grep -Eq 'fake-green-ok:'; then
          continue
        fi
        echo "DEFECT: $f:$lineno matches /$pat/ — $line"
        hits=$((hits+1))
      fi
    done
    prev="$line"
  done < "$f"
done < <(find "$WF_DIR" -name '*.yml' -o -name '*.yaml' 2>/dev/null)

if [ "$hits" -gt 0 ]; then
  echo "no-fake-green: $hits defect(s) found"
  exit 1
fi
echo "no-fake-green OK"
exit 0
