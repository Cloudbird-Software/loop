#!/usr/bin/env python3
"""loopd.adapters 包入口：`python3 -m loopd.adapters` 跑分层自检（W2-7 AC-3）。"""
import sys

from loopd.adapters import _selfcheck

if __name__ == "__main__":
    print(_selfcheck())
    sys.exit(0)