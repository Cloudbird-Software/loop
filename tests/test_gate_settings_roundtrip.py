"""tests/test_gate_settings_roundtrip.py — R10-4 normalize/diff 逻辑（不含 gh api）。"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATES = os.path.join(REPO_ROOT, "gates")
if GATES not in sys.path:
    sys.path.insert(0, GATES)

import gate_settings_roundtrip as rt  # noqa: E402


def test_normalize_strips_server_only_keys():
    snap = {"id": 123, "name": "x", "created_at": "t", "enforcement": "active",
            "rules": [], "_links": {}, "node_id": "n", "current_user_can_bypass": "never"}
    n = rt.normalize(snap)
    assert "id" not in n and "created_at" not in n and "name" not in n
    assert "enforcement" in n and n["enforcement"] == "active"


def test_normalize_sorts_rules_by_type():
    snap = {"rules": [{"type": "merge_queue"}, {"type": "deletion"},
                      {"type": "required_status_checks"}]}
    n = rt.normalize(snap)
    types = [r["type"] for r in n["rules"]]
    assert types == ["deletion", "merge_queue", "required_status_checks"]


def test_diff_fields_detects_value_mismatch():
    d = rt.diff_fields({"enforcement": "active"}, {"enforcement": "disabled"})
    assert any("enforcement" in x for x in d)


def test_diff_fields_detects_missing_key():
    d = rt.diff_fields({"a": 1, "b": 2}, {"a": 1})
    assert any("b" in x for x in d)
    d2 = rt.diff_fields({"a": 1}, {"a": 1, "c": 3})
    assert any("c" in x for x in d2)


def test_diff_fields_no_diff_on_equal():
    assert rt.diff_fields({"a": 1}, {"a": 1}) == []


def test_compare_one_no_id_skips():
    ok, diffs = rt.compare_one({"rules": []})
    assert ok and diffs == []


def test_compare_one_repo_without_source_fails():
    ok, diffs = rt.compare_one({"id": 1, "source_type": "Repository"})
    assert not ok and any("source missing" in d for d in diffs)


def test_compare_one_unknown_source_type_skips():
    ok, diffs = rt.compare_one({"id": 1, "source_type": "Mystery"})
    assert ok and diffs == []


def test_settings_files_have_ids():
    """settings/*.json 必须每个都带 id（否则 roundtrip gate 无法比对）。"""
    sdir = os.path.join(REPO_ROOT, "settings")
    for fn in os.listdir(sdir):
        if fn.endswith(".json"):
            import json
            data = json.loads(open(os.path.join(sdir, fn)).read())
            assert data.get("id"), f"{fn} missing ruleset id"
