#!/usr/bin/env bash
# purge-mechanism-copies.sh — 删除 product-x 中的 loop 机制副本（R13-4）
#
# 用法：在 product-x 仓库根目录执行
#   bash scripts/purge-mechanism-copies.sh [--dry-run]
#
# 删除清单（CHARTER N9）：
#   - gates/           门禁实现副本
#   - lenses/          审查 lens 副本
#   - conductor/       调度器副本（tick.py 等）
#   - loopd/           daemon 副本
#   - prompts/         提示词副本
#   - settings/        门禁设置副本（保留 environments.yml）
#   - materialize.py   模板桩（既不是拷贝也不是实现，是混淆源）
#
# 删除后这些机制由 loop 侧 reusable workflow 提供：
#   - 门禁 → .github/workflows/loop-gates.yml → reusable-gates.yml
#   - 调度 → loop 侧 conductor/tick.py（R11-6 已使其可配置化）
#   - 审查 → .github/workflows/loop-review.yml → reusable-review.yml
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      echo "用法: bash scripts/purge-mechanism-copies.sh [--dry-run]"
      echo "  --dry-run  只打印将删除的文件，不实际删除"
      echo "  -h,--help  显示本帮助"
      exit 0
      ;;
    *)
      echo "error: 未知参数: $arg" >&2
      echo "用法: bash scripts/purge-mechanism-copies.sh [--dry-run]" >&2
      exit 2
      ;;
  esac
done

DELETED_COUNT=0
TMP_LIST="$(mktemp)"
trap 'rm -f "$TMP_LIST"' EXIT

# 收集目录下全部文件（null 分隔）到 TMP_LIST。
# 目录不存在 → 打印 SKIP 并返回 0（清理后状态属预期，非错误）。
# find 在已存在目录上失败 → 返回非 0，set -e 直接退出（不吞错、不假绿）。
collect_dir() {
  local dir="$1"
  if [ ! -d "$dir" ]; then
    echo "SKIP: $dir not found"
    return 0
  fi
  find "$dir" -type f -print0 > "$TMP_LIST"
}

# 收集 settings/ 下的 *.json，保留 environments.yml（与 gate_conformance 检查 5 同口径）。
collect_settings_json() {
  local dir="settings"
  if [ ! -d "$dir" ]; then
    echo "SKIP: $dir not found"
    return 0
  fi
  find "$dir" -type f -name '*.json' ! -name 'environments.yml' -print0 > "$TMP_LIST"
}

purge_file() {
  local f="$1"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "DRY-RUN DELETE: $f"
  else
    echo "DELETE: $f"
    rm -f -- "$f"
  fi
  DELETED_COUNT=$((DELETED_COUNT + 1))
}

# 遍历 TMP_LIST（null 分隔）逐个删除。rm 失败 → set -e 退出，不假绿。
purge_collected() {
  local f
  while IFS= read -r -d '' f; do
    purge_file "$f"
  done < "$TMP_LIST"
}

purge_single() {
  local f="$1"
  if [ ! -e "$f" ] && [ ! -L "$f" ]; then
    echo "SKIP: $f not found"
    return 0
  fi
  purge_file "$f"
}

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== DRY RUN（不实际删除）==="
else
  echo "=== 开始清理 product-x 机制副本 ==="
fi

# gates / lenses / conductor / loopd / prompts —— 整目录清空
for target in gates lenses conductor loopd prompts; do
  : > "$TMP_LIST"
  collect_dir "$target"
  purge_collected
done

# settings/ —— 仅删 *.json，保留 environments.yml
: > "$TMP_LIST"
collect_settings_json
purge_collected

# materialize.py —— 根级模板桩（混淆源）
purge_single "materialize.py"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== DRY RUN 结束：将删除 $DELETED_COUNT 个文件（未实际删除）==="
else
  echo "=== 清理完成：已删除 $DELETED_COUNT 个文件 ==="
fi
