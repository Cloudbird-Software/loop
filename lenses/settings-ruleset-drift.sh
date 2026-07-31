#!/usr/bin/env bash
# lenses/settings-ruleset-drift.sh — 确定性检查器（R12-6 固化案例 #3）
#
# 来源：settings 漂移（audit）。强模型曾指控 settings 与线上 ruleset 不一致，
# 经独立复现坐实。本检查器把该判断从「模型说了算」降级为「无 LLM 参与的往返比对」——
# 系统对模型的信任单调下降（R12-6 / CHARTER N5）。
#
# 契约：exit 0 = 未发现缺陷；exit 1 = 发现缺陷；exit 2 = 执行失败（GATE_NOT_EXECUTED）。
# 实现：直接调用 gates/gate_settings_roundtrip.py（无副作用：只打印 diff + exit 0/1），
# 复用其与 conductor/drift_check.py 共享的比较逻辑（R10-4 单一真源）。
# 不调用 drift_check.py 本体——后者会真开 Incident（写副作用），不适合确定性 lens。
# **永不自动修**（CHARTER N5）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

ROUNDTRIP="$ROOT/gates/gate_settings_roundtrip.py"

if [ ! -f "$ROUNDTRIP" ]; then
  echo "GATE_NOT_EXECUTED: gates/gate_settings_roundtrip.py not found" >&2
  exit 2
fi

cd "$ROOT"
# 直接调用 gate_settings_roundtrip.py（无副作用：只打印 diff + exit 0/1），
# 不调用 conductor/drift_check.py（后者会真开 Incident，有写副作用，不适合确定性 lens）。
set +e
python3 gates/gate_settings_roundtrip.py > /tmp/lens-srd-output.$$ 2>&1
rc=$?
set -e

cat /tmp/lens-srd-output.$$
rm -f /tmp/lens-srd-output.$$

case "$rc" in
  0)
    echo "settings-ruleset-drift OK"
    exit 0
    ;;
  1)
    echo "settings-ruleset-drift: drift detected (will open Incident, never auto-fix)"
    exit 1
    ;;
  *)
    echo "settings-ruleset-drift: checker failed with exit $rc" >&2
    exit 2
    ;;
esac
