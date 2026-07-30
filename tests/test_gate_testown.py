"""Integration tests for gates/gate_testown.py.

Covers: no acceptance change, acceptance change without/with the
`test-change-approved` label, and recursive glob matching of
tests/acceptance/** (subdirectory files).

All external subprocess (gh / git) and env vars are mocked; no network.
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout
from unittest import mock

import pytest

GATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gates")
if GATES_DIR not in sys.path:
    sys.path.insert(0, GATES_DIR)

import gate_testown  # noqa: E402


def _make_run_side_effect(changed_files, labels):
    """Fake subprocess.run that answers git diff + gh pr view --json labels."""
    def _run(cmd, *args, **kwargs):
        class R:
            pass
        r = R()
        r.returncode = 0
        r.stderr = ""
        if cmd[0] == "gh":
            sub = cmd[1]
            if sub == "pr" and "--json" in cmd and "labels" in cmd:
                r.stdout = json.dumps({"labels": [{"name": l} for l in labels]})
            else:
                r.stdout = "{}"
        elif cmd[0] == "git":
            if len(cmd) > 1 and cmd[1] == "merge-base":
                r.stdout = "baseSHA\n"
            elif len(cmd) > 1 and cmd[1] == "rev-parse":
                r.stdout = "baseSHA\n"
            elif len(cmd) > 1 and cmd[1] == "diff" and "--name-only" in cmd:
                r.stdout = "\n".join(changed_files) + ("\n" if changed_files else "")
            else:
                r.stdout = ""
        else:
            r.stdout = ""
        return r
    return _run


def _run_gate(changed_files, labels=None):
    """Run gate_testown.main() under mocked env + subprocess. Returns (code, stdout)."""
    if labels is None:
        labels = []
    env = {
        "GITHUB_REF": "refs/pull/123/merge",
        "GITHUB_BASE_REF": "main",
        "GH_TOKEN": "fake-token",
    }
    side = _make_run_side_effect(changed_files, labels)
    buf = io.StringIO()
    code = 0
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(gate_testown, "GH_TOKEN", "fake-token"), \
            mock.patch.object(gate_testown.subprocess, "run", side_effect=side), \
            redirect_stdout(buf):
        try:
            gate_testown.main()
        except SystemExit as e:
            code = e.code if e.code is not None else 0
    return code, buf.getvalue()


# --- Test cases ---

def test_no_acceptance_changes_is_green():
    """Case 1: PR diff without tests/acceptance/** -> green."""
    code, out = _run_gate(["src/main.py", "README.md"])
    assert code == 0
    assert "OK" in out
    assert "no acceptance test changes" in out


def test_acceptance_change_without_label_is_red():
    """Case 2: tests/acceptance/foo.py changed, no test-change-approved label -> red."""
    code, out = _run_gate(["src/main.py", "tests/acceptance/foo.py"], labels=[])
    assert code == 1
    assert "FAIL" in out
    assert "test-change-approved" in out
    assert "tests/acceptance/foo.py" in out


def test_acceptance_change_with_label_is_green():
    """Case 3: tests/acceptance/foo.py changed with test-change-approved label -> green."""
    code, out = _run_gate(
        ["src/main.py", "tests/acceptance/foo.py"],
        labels=["test-change-approved"],
    )
    assert code == 0
    assert "OK" in out
    assert "test-change-approved" in out


def test_acceptance_subdir_glob_match_is_detected():
    """Case 4: tests/acceptance/sub/bar.py is detected by the glob pattern."""
    code, out = _run_gate(["tests/acceptance/sub/bar.py"], labels=[])
    assert code == 1
    assert "FAIL" in out
    assert "tests/acceptance/sub/bar.py" in out
