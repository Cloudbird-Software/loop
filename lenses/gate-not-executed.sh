#!/usr/bin/env bash
# lenses/gate-not-executed.sh — 确定性检查器（R12-6 固化案例 #2）
#
# 来源：审查裁决 F-A（audit）。强模型曾指控「偷偷缩小 gate 集合 = 静默跳过」，
# 经独立复现坐实。本检查器把该判断从「模型说了算」降级为「无 LLM 参与的 gate 存在性扫描」——
# 系统对模型的信任单调下降（R12-6 / CHARTER N5）。
#
# 契约：exit 0 = 未发现缺陷；exit 1 = 发现缺陷；exit 2 = 执行失败（GATE_NOT_EXECUTED）。
# 实现：复用 gates/run_gates.py，它对 profile 声明但三处 search_dir 都找不到的 gate
# 返回 exit code 2 并打印 GATE_NOT_EXECUTED。本 wrapper 把 2 翻译为「发现缺陷」。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

if [ ! -f "$ROOT/gates/run_gates.py" ]; then
  echo "GATE_NOT_EXECUTED: gates/run_gates.py not found" >&2
  exit 2
fi

cd "$ROOT"
set +e
python3 gates/run_gates.py > /tmp/lens-gne-output.$$ 2>&1
rc=$?
set -e

case "$rc" in
  0)
    echo "gate-not-executed OK"
    exit 0
    ;;
  2)
    # run_gates.py 用 exit 2 表示「至少一个 gate 缺席」——这正是本 lens 要检测的缺陷
    cat /tmp/lens-gne-output.$$
    rm -f /tmp/lens-gne-output.$$
    echo "gate-not-executed: missing gate(s) detected (run_gates.py exit 2)"
    exit 1
    ;;
  *)
    cat /tmp/lens-gne-output.$$ >&2
    rm -f /tmp/lens-gne-output.$$
    echo "gate-not-executed: run_gates.py failed with exit $rc" >&2
    exit 2
    ;;
esac
