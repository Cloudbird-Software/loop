#!/usr/bin/env python3
"""W0-1 gates/gate_maturity_evidence.py 单测（Copilot review 建议：补 check_evidence 覆盖）。

锁死证据优先级与失败模式：
  EVIDENCE_RUN_ID（最高优先级）> EVIDENCE_FILE > 默认 marker > 无证据 FAIL(NO_RUN_EVIDENCE)
  + Copilot review：EVIDENCE_FILE 已设但文件缺失时 detail 措辞区分。

运行：python tests/test_gate_maturity_evidence.py  或  pytest tests/test_gate_maturity_evidence.py -q
"""
import os
import sys
import json
import pathlib
import tempfile
import importlib

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))

# gates/ 不是包（无 __init__.py），用 importlib 从文件路径加载。
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "gate_maturity_evidence", WORKSPACE / "gates" / "gate_maturity_evidence.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)


def _clean_env():
    """移除影响证据判定的 env，确保测试起点干净。"""
    for k in ("EVIDENCE_RUN_ID", "EVIDENCE_FILE"):
        os.environ.pop(k, None)


def test_no_evidence_fails():
    """无任何证据 → has_evidence=False，detail 含 NO_RUN_EVIDENCE 语境。"""
    _clean_env()
    # 切到临时目录避免读到仓库真实 .loop/evidence marker
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            has, detail = G.check_evidence()
        finally:
            os.chdir(old_cwd)
    assert has is False, "no evidence should fail"
    assert "no run evidence" in detail, f"detail should mention no evidence: {detail!r}"
    assert "no EVIDENCE_RUN_ID env" in detail, f"detail should mention missing run id: {detail!r}"
    print("test_no_evidence_fails PASS: no evidence → FAIL with descriptive detail")


def test_evidence_run_id_highest_priority():
    """EVIDENCE_RUN_ID 非空 → PASS，且优先级高于 EVIDENCE_FILE/marker。"""
    _clean_env()
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            os.environ["EVIDENCE_RUN_ID"] = "12345"
            os.environ["EVIDENCE_FILE"] = str(pathlib.Path(td) / "nonexistent.json")
            has, detail = G.check_evidence()
        finally:
            os.chdir(old_cwd)
            _clean_env()
    assert has is True, "EVIDENCE_RUN_ID should pass"
    assert "12345" in detail, f"detail should include run id: {detail!r}"
    print("test_evidence_run_id_highest_priority PASS: EVIDENCE_RUN_ID wins over missing EVIDENCE_FILE")


def test_evidence_file_present():
    """EVIDENCE_FILE 指向存在且非空的文件 → PASS。"""
    _clean_env()
    with tempfile.TemporaryDirectory() as td:
        marker = pathlib.Path(td) / "evidence.json"
        marker.write_text(json.dumps({"run_id": 99}))
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            os.environ["EVIDENCE_FILE"] = str(marker)
            has, detail = G.check_evidence()
        finally:
            os.chdir(old_cwd)
            _clean_env()
    assert has is True, "non-empty EVIDENCE_FILE should pass"
    assert str(marker) in detail, f"detail should include marker path: {detail!r}"
    print("test_evidence_file_present PASS: non-empty EVIDENCE_FILE → PASS")


def test_evidence_file_set_but_missing_distinguished():
    """Copilot review：EVIDENCE_FILE 已设但文件缺失 → FAIL，detail 应区分此情形。"""
    _clean_env()
    with tempfile.TemporaryDirectory() as td:
        missing = pathlib.Path(td) / "absent.json"
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            os.environ["EVIDENCE_FILE"] = str(missing)
            has, detail = G.check_evidence()
        finally:
            os.chdir(old_cwd)
            _clean_env()
    assert has is False, "missing EVIDENCE_FILE should fail"
    # 措辞应反映「EVIDENCE_FILE 已设但文件缺失」，而非笼统「no EVIDENCE_FILE env」
    assert "set but file missing/empty" in detail, f"detail should distinguish set-but-missing: {detail!r}"
    print("test_evidence_file_set_but_missing_distinguished PASS: set-but-missing wording distinguished")


def test_default_marker_file():
    """无 EVIDENCE_FILE 时，默认 marker .loop/evidence/run-evidence.json 存在且非空 → PASS。"""
    _clean_env()
    with tempfile.TemporaryDirectory() as td:
        loop_evidence = pathlib.Path(td) / ".loop" / "evidence" / "run-evidence.json"
        loop_evidence.parent.mkdir(parents=True, exist_ok=True)
        loop_evidence.write_text('{"run_id": 7}')
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            has, detail = G.check_evidence()
        finally:
            os.chdir(old_cwd)
            _clean_env()
    assert has is True, "default marker should pass"
    assert "marker file" in detail, f"detail should mention marker: {detail!r}"
    print("test_default_marker_file PASS: default marker → PASS")


def test_main_exit_code_no_evidence():
    """main() 无证据 → exit 1（gate 契约 FAIL）。"""
    _clean_env()
    with tempfile.TemporaryDirectory() as td:
        old_cwd = os.getcwd()
        os.chdir(td)
        try:
            try:
                G.main()
                rc = 0
            except SystemExit as e:
                rc = e.code
        finally:
            os.chdir(old_cwd)
    assert rc == 1, f"no-evidence main() should exit 1, got {rc}"
    print("test_main_exit_code_no_evidence PASS: main() exits 1 on no evidence")


def test_main_exit_code_with_run_id():
    """main() 有 EVIDENCE_RUN_ID → exit 0（PASS）。"""
    _clean_env()
    os.environ["EVIDENCE_RUN_ID"] = "abc-123"
    try:
        try:
            G.main()
            rc = 0
        except SystemExit as e:
            rc = e.code
    finally:
        _clean_env()
    assert rc == 0, f"with-run-id main() should exit 0, got {rc}"
    print("test_main_exit_code_with_run_id PASS: main() exits 0 with evidence")


if __name__ == "__main__":
    tests = [
        test_no_evidence_fails,
        test_evidence_run_id_highest_priority,
        test_evidence_file_present,
        test_evidence_file_set_but_missing_distinguished,
        test_default_marker_file,
        test_main_exit_code_no_evidence,
        test_main_exit_code_with_run_id,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"{t.__name__} FAIL: {type(e).__name__}: {e}")
    print(f"\n{'='*40}\n{len(tests)-failed}/{len(tests)} passed" + (f", {failed} FAILED" if failed else ""))
    sys.exit(1 if failed else 0)
