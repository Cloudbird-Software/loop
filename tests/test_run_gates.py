"""tests/test_run_gates.py — R10-3 gate runner 的四种路径覆盖。"""
import json
import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATES = os.path.join(REPO_ROOT, "gates")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if GATES not in sys.path:
    sys.path.insert(0, GATES)

import run_gates  # noqa: E402


def _write_gate(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(textwrap.dedent(body))
    os.chmod(path, 0o755)


def test_resolve_gate_prefers_first_dir(tmp_path):
    d1 = tmp_path / "gates"
    d2 = tmp_path / ".loop" / "gates"
    _write_gate(str(d1 / "gate_alpha.py"), "import sys; sys.exit(0)")
    _write_gate(str(d2 / "gate_alpha.py"), "import sys; sys.exit(1)")
    p = run_gates.resolve_gate("alpha", [str(d1), str(d2)])
    assert p == str(d1 / "gate_alpha.py")


def test_resolve_gate_falls_through_to_second_dir(tmp_path):
    d1 = tmp_path / "gates"
    d2 = tmp_path / ".loop" / "gates"
    os.makedirs(str(d1))
    _write_gate(str(d2 / "gate_beta.py"), "import sys; sys.exit(0)")
    p = run_gates.resolve_gate("beta", [str(d1), str(d2)])
    assert p == str(d2 / "gate_beta.py")


def test_resolve_gate_accepts_bare_name_without_gate_prefix(tmp_path):
    d = tmp_path / "gates"
    _write_gate(str(d / "lockdiff.py"), "import sys; sys.exit(0)")
    assert run_gates.resolve_gate("lockdiff", [str(d)]) == str(d / "lockdiff.py")


def test_resolve_gate_missing_returns_none(tmp_path):
    assert run_gates.resolve_gate("nope", [str(tmp_path)]) is None


def test_run_one_pass(tmp_path):
    p = tmp_path / "gate_pass.py"
    _write_gate(str(p), "import sys; print('ok'); sys.exit(0)")
    r = run_gates.run_one("pass", str(p), 10)
    assert r["status"] == "pass" and r["exit_code"] == 0


def test_run_one_fail(tmp_path):
    p = tmp_path / "gate_fail.py"
    _write_gate(str(p), "import sys; print('FAIL: bad'); sys.exit(1)")
    r = run_gates.run_one("fail", str(p), 10)
    assert r["status"] == "fail" and r["exit_code"] == 1


def test_run_one_error_unexpected_exit_code(tmp_path):
    p = tmp_path / "gate_err.py"
    _write_gate(str(p), "import sys; sys.exit(2)")
    r = run_gates.run_one("err", str(p), 10)
    assert r["status"] == "error" and r["exit_code"] == 2


def test_run_one_error_traceback_classified_as_error(tmp_path):
    p = tmp_path / "gate_crash.py"
    _write_gate(str(p), "raise ValueError('boom')")
    r = run_gates.run_one("crash", str(p), 10)
    assert r["status"] == "error"
    assert r["exit_code"] == 1  # Python uncaught exception exits 1


def test_run_one_timeout_is_error(tmp_path):
    p = tmp_path / "gate_slow.py"
    _write_gate(str(p), "import time; time.sleep(30)")
    r = run_gates.run_one("slow", str(p), 1)
    assert r["status"] == "error"
    assert "TIMEOUT" in r["detail"]


def _run_main(tmp_path, gate_name, gate_body):
    """在 tmp_path 里造一个最小 policy + gate，跑 run_gates.py 子进程，返回 (exit_code, stdout)。"""
    gdir = tmp_path / "gates"
    _write_gate(str(gdir / f"gate_{gate_name}.py"), gate_body)
    policy = {
        "gates": {
            "timeout_default": 5,
            "search_dirs": ["gates"],
            "profiles": {"default": [gate_name]},
        }
    }
    (tmp_path / "policy.yml").write_text(
        __import__("yaml").dump(policy, default_flow_style=False)
    )
    out_file = tmp_path / "summary.json"
    p = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "gates", "run_gates.py"),
         "--out", str(out_file)],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    summary = json.loads(out_file.read_text()) if out_file.exists() else None
    return p.returncode, p.stdout, summary


def test_main_all_pass_exits_0(tmp_path):
    code, out, summary = _run_main(tmp_path, "ok", "import sys; sys.exit(0)")
    assert code == 0
    assert summary["gates"][0]["status"] == "pass"


def test_main_missing_gate_exits_2(tmp_path):
    """--gates 指定一个不存在的 gate → GATE_NOT_EXECUTED → exit 2。"""
    policy = {"gates": {"timeout_default": 5, "search_dirs": ["gates"],
                        "profiles": {"default": ["ghost"]}}}
    (tmp_path / "policy.yml").write_text(
        __import__("yaml").dump(policy, default_flow_style=False)
    )
    p = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "gates", "run_gates.py")],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert p.returncode == 2
    assert "GATE_NOT_EXECUTED: ghost" in p.stdout


def test_main_errored_gate_exits_3(tmp_path):
    code, out, summary = _run_main(tmp_path, "boom", "import sys; sys.exit(2)")
    assert code == 3
    assert summary["gates"][0]["status"] == "error"


def test_main_failed_gate_exits_1(tmp_path):
    code, out, summary = _run_main(tmp_path, "bad", "import sys; sys.exit(1)")
    assert code == 1
    assert summary["gates"][0]["status"] == "fail"


def test_main_timeout_exits_3(tmp_path):
    code, out, summary = _run_main(tmp_path, "slow", "import time; time.sleep(30)")
    assert code == 3
    assert summary["gates"][0]["status"] == "error"
