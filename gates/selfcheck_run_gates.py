#!/usr/bin/env python3
"""gates/selfcheck_run_gates.py — W3-10 反注入重实现自检套件。

用 `python3 gates/selfcheck_run_gates.py` 运行，全部断言通过则 exit 0。
覆盖 AC-2（reduce_exit 归约优先级）、AC-4（trust_check 反注入/realpath 包含性）、
AC-5（min_gates 反空过 → exit 2）。
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from gates.run_gates import reduce_exit, trust_check


def make(status):
    """构造最小结果 dict。"""
    return {"name": "dummy", "status": status, "exit_code": None,
            "duration_ms": 0, "path": None, "detail": "", "reason": "test"}


def test_reduce_exit_priority():
    """AC-2：归约优先级 untrusted(4)→error(3)→unresolved(2)→fail(1)→pass(0)。"""
    assert reduce_exit([make("untrusted"), make("error"), make("fail")]) == 4
    assert reduce_exit([make("error"), make("unresolved"), make("fail")]) == 3
    assert reduce_exit([make("unresolved"), make("fail")]) == 2
    assert reduce_exit([make("missing")]) == 2          # missing → unresolved
    assert reduce_exit([make("not_found")]) == 2        # not_found → unresolved
    assert reduce_exit([make("root_unavailable")]) == 2
    assert reduce_exit([make("fail")]) == 1
    assert reduce_exit([make("pass"), make("pass")]) == 0
    assert reduce_exit([]) == 0                           # 空 → pass 等价
    assert reduce_exit([make("unknown_status")]) == 3     # 未知 → error，绝无静默假绿
    print("PASS: reduce_exit 归约优先级")


def test_trust_check_symlink_escape():
    """AC-4：符号链接逃逸受控根 → untrusted；realpath 包含性而非前缀。"""
    with tempfile.TemporaryDirectory() as td:
        control = os.path.join(td, "gates")
        os.makedirs(control)
        outside = os.path.join(td, "outside")
        os.makedirs(outside)

        secret = os.path.join(outside, "secret.py")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("import sys; sys.exit(0)\n")

        # 受控根内的正常文件 → 可信
        inside = os.path.join(control, "normal.py")
        with open(inside, "w", encoding="utf-8") as f:
            f.write("import sys; sys.exit(0)\n")
        assert trust_check(inside, control) is False

        # 逃逸到受控根外的符号链接 → untrusted
        link = os.path.join(control, "escape.py")
        os.symlink(secret, link)
        assert trust_check(link, control) is True

        # 字符串 `..` 逃逸 → untrusted
        assert trust_check(os.path.join(control, "..", "evil.py"), control) is True

        # 前缀撞名：/gates_evil 不应被 /gates 前缀误判为受控（realpath 包含性）
        evil_root = os.path.join(td, "gates_evil")
        os.makedirs(evil_root)
        evil_file = os.path.join(evil_root, "x.py")
        with open(evil_file, "w", encoding="utf-8") as f:
            f.write("import sys; sys.exit(0)\n")
        assert trust_check(evil_file, control) is True
    print("PASS: trust_check 反注入 / realpath 包含性")


def test_min_gates_shortfall_exit2():
    """AC-5：实际执行 pass/fail 数 < min_gates → exit 2（反空过）。

    构造临时 clone：policy.yml（JSON 内容，无 yaml 时也可被 JSON 兜底解析）、
    一个 pass 的 gate，profile 只声明该 gate，并设 min_gates=2。
    执行后实际 pass=1 < 2 → 期望退出码 2。
    """
    run_gates = os.path.abspath(os.path.join(os.path.dirname(__file__), "run_gates.py"))
    with tempfile.TemporaryDirectory() as td:
        gdir = os.path.join(td, "mg_gates")
        os.makedirs(gdir)
        with open(os.path.join(gdir, "gate_pass.py"), "w", encoding="utf-8") as f:
            f.write("import sys; sys.exit(0)\n")
        policy = {
            "gates": {
                "timeout_default": 30,
                "search_dirs": ["mg_gates"],
                "min_gates": 2,
                "profiles": {"default": ["pass"]},
            }
        }
        import json as _json
        with open(os.path.join(td, "policy.yml"), "w", encoding="utf-8") as f:
            _json.dump(policy, f)
        proc = subprocess.run(
            [sys.executable, run_gates, "--profile", "default", "--root", td],
            cwd=td, capture_output=True, text=True,
        )
        assert proc.returncode == 2, f"min_gates 反空过应 exit 2，实得 {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    print("PASS: min_gates 反空过 → exit 2")


def main():
    test_reduce_exit_priority()
    test_trust_check_symlink_escape()
    test_min_gates_shortfall_exit2()
    print("\nALL W3-10 TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())