"""Integration tests for gates/gate_verdict.py.

Covers: head_sha binding, missing fields, AC pass/fail, missing evidence,
trivial-tier skip, and the all-green happy path.

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

import gate_verdict  # noqa: E402

HEAD_SHA = "abcdef1234567890abcdef1234567890abcdef12"
STANDARD_CARD = {"tier": "standard", "verify": {"required": True}}
TRIVIAL_CARD = {"tier": "trivial", "verify": {"required": True}}


def _pr_body(card_num=456):
    return f"Implements feature.\n\nCard: #{card_num}\n"


def _issue_body(card):
    return "Card body.\n\n```json loop\n" + json.dumps(card) + "\n```\n"


def _verdict_comment(verdict):
    return "Posted verdict:\n\n```json verdict\n" + json.dumps(verdict) + "\n```\n"


def _valid_verdict(head_sha=HEAD_SHA, acs=None):
    if acs is None:
        acs = [{"id": "AC1", "pass": True, "evidence": "tests/unit/t.py::test_ac1"}]
    return {
        "head_sha": head_sha,
        "blind_phase_commit": "z" * 40,
        "artifact_digest": "abc123",
        "test_plan_version": "card-1-v1",
        "acs": acs,
    }


def _make_run_side_effect(pr_body, issue_body, comments, head_sha):
    """Fake subprocess.run that answers gh + git calls used by gate_verdict."""
    def _run(cmd, *args, **kwargs):
        class R:
            pass
        r = R()
        r.returncode = 0
        r.stderr = ""
        if cmd[0] == "gh":
            sub = cmd[1]
            if sub == "pr" and "--json" in cmd:
                r.stdout = json.dumps({"body": pr_body})
            elif sub == "issue" and "--json" in cmd:
                r.stdout = json.dumps({"body": issue_body})
            elif sub == "api":
                r.stdout = json.dumps(comments)
            else:
                r.stdout = "{}"
        elif cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "rev-parse":
            r.stdout = head_sha + "\n"
        else:
            r.stdout = ""
        return r
    return _run


def _run_gate(card, verdict=None, head_sha=HEAD_SHA, comments=None):
    """Run gate_verdict.main() under mocked env + subprocess. Returns (code, stdout)."""
    env = {
        "GITHUB_REF": "refs/pull/123/merge",
        "GITHUB_REPOSITORY": "owner/repo",
        "GH_TOKEN": "fake-token",
    }
    if comments is None:
        comments = [{"body": _verdict_comment(verdict)}] if verdict is not None else []
    side = _make_run_side_effect(_pr_body(), _issue_body(card), comments, head_sha)
    buf = io.StringIO()
    code = 0
    with mock.patch.dict(os.environ, env, clear=False), \
            mock.patch.object(gate_verdict, "GITHUB_REPOSITORY", "owner/repo"), \
            mock.patch.object(gate_verdict, "GH_TOKEN", "fake-token"), \
            mock.patch.object(gate_verdict.subprocess, "run", side_effect=side), \
            redirect_stdout(buf):
        try:
            gate_verdict.main()
        except SystemExit as e:
            code = e.code if e.code is not None else 0
    return code, buf.getvalue()


# --- Test cases ---

def test_verdict_head_sha_matches_pr_head_is_green():
    """Case 1: VERDICT.head_sha == current PR HEAD -> green."""
    code, out = _run_gate(STANDARD_CARD, verdict=_valid_verdict(HEAD_SHA))
    assert code == 0
    assert "OK" in out
    assert HEAD_SHA[:12] in out


def test_verdict_head_sha_mismatch_is_red():
    """Case 2: VERDICT.head_sha != current PR HEAD -> red, VERDICT_SHA_MISMATCH."""
    code, out = _run_gate(STANDARD_CARD, verdict=_valid_verdict("0" * 40))
    assert code == 1
    assert "VERDICT_SHA_MISMATCH" in out


def test_verdict_missing_acs_is_red():
    """Case 3: verdict missing acs field -> red."""
    v = {
        "head_sha": HEAD_SHA,
        "blind_phase_commit": "z" * 40,
        "artifact_digest": "abc123",
        "test_plan_version": "card-1-v1",
    }
    code, out = _run_gate(STANDARD_CARD, verdict=v)
    assert code == 1
    assert "MISSING_FIELD: acs" in out


def test_verdict_ac_pass_false_is_red():
    """Case 4: an AC with pass=false -> red."""
    v = _valid_verdict(HEAD_SHA, acs=[
        {"id": "AC1", "pass": True, "evidence": "tests/x.py::t1"},
        {"id": "AC2", "pass": False, "evidence": "tests/x.py::t2"},
    ])
    code, out = _run_gate(STANDARD_CARD, verdict=v)
    assert code == 1
    assert "AC_FAILED" in out
    assert "AC2" in out


def test_verdict_ac_missing_evidence_is_red():
    """Case 5: an AC missing evidence -> red."""
    v = _valid_verdict(HEAD_SHA, acs=[
        {"id": "AC1", "pass": True},  # no evidence
    ])
    code, out = _run_gate(STANDARD_CARD, verdict=v)
    assert code == 1
    assert "AC_MISSING_FIELD: evidence" in out


def test_trivial_tier_skips_verdict_check():
    """Case 6: trivial tier -> SKIP, no verdict required."""
    code, out = _run_gate(TRIVIAL_CARD, verdict=None)
    assert code == 0
    assert "SKIP" in out
    assert "trivial" in out


def test_valid_verdict_all_pass_is_green():
    """Case 7: valid verdict, all ACs pass -> green."""
    v = _valid_verdict(HEAD_SHA, acs=[
        {"id": "AC1", "pass": True, "evidence": "tests/a.py::t1"},
        {"id": "AC2", "pass": True, "evidence": "tests/a.py::t2"},
        {"id": "AC3", "pass": True, "evidence": "tests/a.py::t3"},
    ])
    code, out = _run_gate(STANDARD_CARD, verdict=v)
    assert code == 0
    assert "OK" in out
    assert "acs=3" in out
