#!/usr/bin/env python3
"""lockdiff — Return JSON array of [pkg, version, published_date] for new/changed deps in lockfile"""
import sys
# 未实现：按 CHARTER N8.3「未执行等价于失败」，骨架桩必须显式失败而非假绿。
# R11-5 会实现本 gate 的真实逻辑。接入 gates.yml 前必须先实现。
print("GATE_NOT_EXECUTED: lockdiff (skeleton — implement in R11-5)", file=sys.stderr)
sys.exit(2)
