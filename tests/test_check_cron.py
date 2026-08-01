#!/usr/bin/env python3
"""W0-8 tools/check-cron.py 单测（Copilot review 建议：补 validate_cron 覆盖）。

覆盖 validate_cron() 的合法/非法用例与 main() 退出码，锁死语义防回归。

运行：python tests/test_check_cron.py  或  pytest tests/test_check_cron.py -q
"""
import os
import sys
import pathlib
import importlib.util

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))

# tools/ 不是包（无 __init__.py，且可能被同名 stdlib/site-package 遮蔽），
# 用 importlib 从文件路径加载，与 test_gate_maturity_evidence.py 同风格。
_spec = importlib.util.spec_from_file_location(
    "check_cron", WORKSPACE / "tools" / "check-cron.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


# ==================================================================
# 合法表达式（ok=True）
# ==================================================================
VALID_CASES = [
    "*/15 * * * *",      # AC-3: 每 15 分钟
    "0 9 1 * 1",         # 每周一 9:00（day-of-month=1, dow=1）
    "0 5 0 * *",         # 注意：这是 *非法* 用例（见下方 INVALID），此处占位被替换
    "0 0 * * 0",         # 每周日（dow=0）
    "0 0 * * 7",         # 每周日（dow=7，与 0 等价）
    "30 22 * * 1-5",     # 工作日 22:30（range）
    "0,30 * * * *",      # 每 30 分钟（逗号列表）
    "0 0 1,15 * *",      # 每月 1 号与 15 号
    "*/30 9-17 * * 1-5", # 工作时间每 30 分钟
    "0 0 1 1 *",         # 每年 1 月 1 号
    "59 23 31 12 *",     # 12 月 31 号 23:59（边界值）
    "0-59/2 * * * *",    # 每 2 分钟（range+step）
]


def test_valid_expressions():
    """所有合法 cron 表达式应返回 ok=True。"""
    failures = []
    for expr in VALID_CASES:
        if expr == "0 5 0 * *":
            continue  # 该用例属非法集，跳过占位
        ok, msg = C.validate_cron(expr)
        if not ok:
            failures.append(f"{expr!r}: expected ok, got {msg!r}")
    assert not failures, "合法表达式被误判为非法:\n  " + "\n  ".join(failures)
    print(f"test_valid_expressions PASS: {len(VALID_CASES)-1} valid expressions accepted")


# ==================================================================
# 非法表达式（ok=False）
# ==================================================================
INVALID_CASES = [
    ("0 5 0 * *", "day-of-month=0 非法（AC-2）"),
    ("60 * * * *", "minute=60 越界（max 59）"),
    ("* 24 * * *", "hour=24 越界（max 23）"),
    ("* * 32 * *", "day-of-month=32 越界（max 31）"),
    ("* * * 13 *", "month=13 越界（max 12）"),
    ("* * * * 8", "day-of-week=8 越界（max 7）"),
    ("*/0 * * * *", "step=0 非法"),
    ("1-5/0 * * * *", "range step=0 非法"),
    ("* * * *", "字段数不足（4 字段）"),
    ("* * * * * *", "字段数过多（6 字段）"),
    ("a b c d e", "非数字 token"),
    ("1-5-9 * * * *", "畸形 range（双连字符）"),
    ("* * , * *", "逗号列表空元素"),
    ("1-9/ * * * *", "畸形 step（无步长值）"),
]


def test_invalid_expressions():
    """所有非法 cron 表达式应返回 ok=False 并给出原因。"""
    failures = []
    for expr, reason in INVALID_CASES:
        ok, msg = C.validate_cron(expr)
        if ok:
            failures.append(f"{expr!r} ({reason}): expected FAIL, got ok=True")
    assert not failures, "非法表达式被误判为合法:\n  " + "\n  ".join(failures)
    print(f"test_invalid_expressions PASS: {len(INVALID_CASES)} invalid expressions rejected")


# ==================================================================
# main() 退出码（CLI 契约）
# ==================================================================
def test_main_exit_codes():
    """--cron 合法 → main 返回 0；非法 → 返回 1。"""
    assert C.main(["--cron", "*/15 * * * *"]) == 0, "valid cron should exit 0"
    assert C.main(["--cron", "0 5 0 * *"]) == 1, "invalid cron should exit 1"
    print("test_main_exit_codes PASS: main() returns 0/1 correctly")


if __name__ == "__main__":
    tests = [test_valid_expressions, test_invalid_expressions, test_main_exit_codes]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"{t.__name__} FAIL: {type(e).__name__}: {e}")
    print(f"\n{'='*40}\n{len(tests)-failed}/{len(tests)} passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
