"""tests/test_incident_dedup.py — R10-6 Incident 指纹去重逻辑。"""
import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONDUCTOR = os.path.join(REPO_ROOT, "conductor")
SCRIPTS = os.path.join(REPO_ROOT, ".loop", "scripts")
for p in (REPO_ROOT, CONDUCTOR, SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)

import drift_check  # noqa: E402
import incident_converge  # noqa: E402


# ── drift_check.fingerprint ──────────────────────────────────────────────

def test_fingerprint_stable_for_same_input():
    raw = [{"file": "main-protection.json", "diffs": ["enforcement differs"]}]
    assert drift_check.fingerprint(raw) == drift_check.fingerprint(raw)


def test_fingerprint_changes_for_different_input():
    a = [{"file": "a.json", "diffs": ["x"]}]
    b = [{"file": "a.json", "diffs": ["y"]}]
    assert drift_check.fingerprint(a) != drift_check.fingerprint(b)


def test_fingerprint_order_independent():
    a = [{"file": "a.json", "diffs": ["x"]}, {"file": "b.json", "diffs": ["y"]}]
    b = [{"file": "b.json", "diffs": ["y"]}, {"file": "a.json", "diffs": ["x"]}]
    assert drift_check.fingerprint(a) == drift_check.fingerprint(b)


def test_fingerprint_is_8_hex_chars():
    fp = drift_check.fingerprint([{"diffs": ["test"]}])
    assert len(fp) == 8 and all(c in "0123456789abcdef" for c in fp)


# ── drift_check.find_open_incident (mocked gh) ───────────────────────────

def test_find_open_incident_returns_number_on_match(monkeypatch):
    calls = {}

    def fake_gh(*args):
        calls["args"] = args
        return type("R", (), {"returncode": 0, "stdout": json.dumps(
            [{"number": 42, "title": "Incident: drift [fp=abc12345]"}]), "stderr": ""})()

    monkeypatch.setattr(drift_check, "gh", fake_gh)
    assert drift_check.find_open_incident("abc12345") == 42


def test_find_open_incident_returns_none_when_no_match(monkeypatch):
    monkeypatch.setattr(drift_check, "gh", lambda *a: type(
        "R", (), {"returncode": 0, "stdout": "[]", "stderr": ""})())
    assert drift_check.find_open_incident("abc12345") is None


def test_find_open_incident_returns_none_on_gh_failure(monkeypatch):
    monkeypatch.setattr(drift_check, "gh", lambda *a: type(
        "R", (), {"returncode": 1, "stdout": "", "stderr": "auth error"})())
    assert drift_check.find_open_incident("abc12345") is None


# ── incident_converge.group_key ──────────────────────────────────────────

def test_group_key_extracts_fingerprint():
    issue = {"title": "Incident: 26h survival check failed [fp=abc12345]"}
    assert incident_converge.group_key(issue) == "fp=abc12345"


def test_group_key_legacy_strips_timestamp():
    issue = {"title": "Incident: 26h survival check failed @2026-07-29T10:15Z"}
    k = incident_converge.group_key(issue)
    assert "2026" not in k and "survival" in k


def test_group_key_legacy_without_timestamp():
    issue = {"title": "Incident: canary chain broken"}
    assert incident_converge.group_key(issue) == "Incident: canary chain broken"


def test_group_key_same_legacy_title_groups_together():
    a = {"title": "Incident: 26h survival check failed @2026-07-29T10:15Z"}
    b = {"title": "Incident: 26h survival check failed @2026-07-30T09:29Z"}
    assert incident_converge.group_key(a) == incident_converge.group_key(b)


# ── incident_converge.converge (mocked) ──────────────────────────────────

def test_converge_keeps_latest_closes_rest(monkeypatch):
    incidents = [
        {"number": 3, "title": "Incident: survival @2026-07-29T10:15Z", "createdAt": "2026-07-29T10:15:00Z"},
        {"number": 5, "title": "Incident: survival @2026-07-29T10:19Z", "createdAt": "2026-07-29T10:19:00Z"},
        {"number": 48, "title": "Incident: survival @2026-07-30T09:29Z", "createdAt": "2026-07-30T09:29:00Z"},
        {"number": 4, "title": "Incident: canary chain broken", "createdAt": "2026-07-29T10:16:00Z"},
    ]
    closed = []
    monkeypatch.setattr(incident_converge, "list_incidents", lambda: incidents)
    monkeypatch.setattr(incident_converge, "close_with_reason",
                        lambda n, r: closed.append(n))
    n = incident_converge.converge(dry_run=False)
    assert n == 2  # closed 3 and 5, kept 48 (latest survival) + 4 (canary, only one)
    assert 3 in closed and 5 in closed
    assert 48 not in closed and 4 not in closed


def test_converge_dry_run_does_not_close(monkeypatch):
    incidents = [
        {"number": 1, "title": "Incident: x @2026-07-29T10:00Z", "createdAt": "2026-07-29T10:00:00Z"},
        {"number": 2, "title": "Incident: x @2026-07-30T10:00Z", "createdAt": "2026-07-30T10:00:00Z"},
    ]
    closed = []
    monkeypatch.setattr(incident_converge, "list_incidents", lambda: incidents)
    monkeypatch.setattr(incident_converge, "close_with_reason",
                        lambda n, r: closed.append(n))
    incident_converge.converge(dry_run=True)
    assert closed == []
