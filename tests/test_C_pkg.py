#!/usr/bin/env python3
"""tests/test_C_pkg.py — C 包端到端测试：单向阀门 + incident 限额 + 作者白名单。

覆盖场景：
1. 合法 wave.md（2 张卡，paths 不交叉，tier 合法，acceptance≥1）→ validate() 通过
2. materialize_wave()（mock gh）→ milestone + parent + sub-issues 创建顺序正确
3. paths 交叉波次 → validate() 失败并开 Incident
4. 非 materializer role 调用 create_card_issue → 被拒
5. incident 第 3 张 hotfix → 被限额拒绝
6. 非白名单作者发 !drop → 被忽略
"""
import os
import sys
from subprocess import CompletedProcess
from unittest import mock

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

import conductor.materialize as M  # noqa: E402
import conductor.commands as C     # noqa: E402


# ---------- helpers ----------

def _cp(stdout="", returncode=0, stderr=""):
    """Build a subprocess.CompletedProcess-like object for mocked gh."""
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


VALID_WAVE_MD = """# WAVE-42: Test Wave

> A test wave for e2e

## O1: First objective

```json loop
{
  "schema": 1, "id": "C-1", "wave": "WAVE-42", "objective": "O1",
  "state": "ready", "tier": "standard", "role": "impl",
  "paths": ["src/auth/**"],
  "forbid_paths": [".github/**","settings/**"],
  "charter": ["G0"],
  "acceptance": ["AC1: works"],
  "verify": {"required": true, "blind": true, "verdict_sha": null},
  "blocked_by": null
}
```

## O2: Second objective

```json loop
{
  "schema": 1, "id": "C-2", "wave": "WAVE-42", "objective": "O2",
  "state": "ready", "tier": "trivial", "role": "impl",
  "paths": ["src/billing/**"],
  "forbid_paths": [".github/**","settings/**"],
  "charter": ["G0"],
  "acceptance": ["AC1: works"],
  "verify": {"required": true, "blind": true, "verdict_sha": null},
  "blocked_by": null
}
```
"""


OVERLAP_WAVE_MD = """# WAVE-43: Overlap Wave

> paths cross

## O1

```json loop
{
  "schema": 1, "id": "C-A", "wave": "WAVE-43", "objective": "O1",
  "state": "ready", "tier": "standard", "role": "impl",
  "paths": ["src/auth/**"],
  "charter": ["G0"],
  "acceptance": ["AC1: works"],
  "blocked_by": null
}
```

## O2

```json loop
{
  "schema": 1, "id": "C-B", "wave": "WAVE-43", "objective": "O2",
  "state": "ready", "tier": "standard", "role": "impl",
  "paths": ["src/auth/login/**"],
  "charter": ["G0"],
  "acceptance": ["AC1: works"],
  "blocked_by": null
}
```
"""


# ============================================================
# 1. Role valve map (documentation of the one-way valve)
# ============================================================

def test_role_create_map_valves():
    """ROLE_CREATE_MAP 编码单向阀门：每个角色只能造对应类型。"""
    assert M.ROLE_CREATE_MAP["auditor"] == {"Finding"}, "auditor 只能建 Finding"
    assert M.ROLE_CREATE_MAP["impl"] == set(), "impl 不能造 Card"
    assert M.ROLE_CREATE_MAP["verify"] == set(), "verify 不能造 Card"
    assert "Card" in M.ROLE_CREATE_MAP["materializer"], "materializer 可批量造 Card"
    assert "Card" in M.ROLE_CREATE_MAP["incident"], "incident 可造 hotfix Card"
    assert M.ROLE_CREATE_MAP["planner"] == {"Wave"}, "planner 只能建 Wave"
    assert M.INCIDENT_HOTFIX_DAILY_LIMIT == 2


# ============================================================
# 2. Valid wave validates
# ============================================================

def test_valid_wave_validates(tmp_path):
    """合法 wave.md（2 张卡，paths 不交叉）→ validate() 通过。"""
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "WAVE-42.md").write_text(VALID_WAVE_MD)

    cards, metas = M.extract_cards(str(waves))
    assert len(cards) == 2
    assert metas and metas[0]["id"] == "WAVE-42"

    errors, valid = M.validate(cards, None)  # charter_ids=None → G0 placeholder
    assert errors == [], f"unexpected errors: {errors}"
    assert len(valid) == 2
    ids = {c["id"] for c in valid}
    assert ids == {"C-1", "C-2"}


# ============================================================
# 3. materialize_wave creates milestone → parent → sub-issues in order
# ============================================================

def test_materialize_wave_order(tmp_path):
    """mock gh 调用，验证 milestone + parent + sub-issues 创建顺序。"""
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "WAVE-42.md").write_text(VALID_WAVE_MD)
    cards, metas = M.extract_cards(str(waves))
    errors, valid = M.validate(cards, None)
    assert not errors
    assert len(valid) == 2

    calls = []
    counter = {"n": 10}

    def fake_gh(*a):
        calls.append(a)
        if a[0] == "issue" and len(a) > 1 and a[1] == "list":
            return _cp("[]")  # idempotency: nothing materialized yet
        if a[0] == "api" and "--method" in a:
            return _cp('{"number": 7}', returncode=201)  # milestone created
        if a[0] == "api":
            return _cp("[]")
        if a[0] == "issue" and len(a) > 1 and a[1] == "create":
            counter["n"] += 1
            return _cp(f"https://github.com/x/y/issues/{counter['n']}")
        return _cp("")

    with mock.patch.object(M, "gh", side_effect=fake_gh):
        ok = M.materialize_wave(valid, metas[0])

    assert ok is True

    def tag(a):
        if a[0] == "api" and "--method" in a:
            return "milestone"
        if a[0] == "issue" and len(a) > 1 and a[1] == "create":
            if "wave" in a:
                return "parent"
            if "card" in a:
                return "card"
            return "issue-create-other"
        if a[0] == "issue" and len(a) > 1 and a[1] == "list":
            return "list"
        if a[0] == "issue" and len(a) > 1 and a[1] == "edit":
            return "parent-edit"
        if a[0] == "issue" and len(a) > 1 and a[1] == "comment":
            return "comment"
        return "other"

    tags = [tag(a) for a in calls]
    # milestone (api POST) → parent (issue create --label wave) → cards (issue create --label card)
    assert "milestone" in tags
    assert "parent" in tags
    assert tags.count("card") == 2
    assert tags.index("milestone") < tags.index("parent"), f"order wrong: {tags}"
    assert tags.index("parent") < tags.index("card"), f"order wrong: {tags}"


# ============================================================
# 4. Overlapping paths fail validation → open Incident
# ============================================================

def test_overlap_paths_fail_and_opens_incident(tmp_path, capsys):
    """paths 交叉 → validate() 失败 → 开 Incident。"""
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "WAVE-43.md").write_text(OVERLAP_WAVE_MD)
    cards, metas = M.extract_cards(str(waves))

    errors, valid = M.validate(cards, None)
    assert any("Path conflict" in e for e in errors), f"expected path conflict, got {errors}"
    assert len(valid) == 0, "conflicting cards must be removed from valid set"

    # 模拟 main() 校验失败路径：materializer 开 Incident 报告自身物化失败
    incident_calls = []

    def fake_gh(*a):
        incident_calls.append(a)
        if a[0] == "issue" and len(a) > 1 and a[1] == "create":
            return _cp("https://github.com/x/y/issues/99")
        return _cp("")

    with mock.patch.object(M, "gh", side_effect=fake_gh):
        num = M.open_incident(
            "Materializer: validation failed for wave",
            "\n".join(f"- {e}" for e in errors),
            role="materializer",
        )

    assert num == "99"
    created = [c for c in incident_calls
               if c[0] == "issue" and len(c) > 1 and c[1] == "create"]
    assert created, "expected an issue create call for the incident"
    flat = []
    for c in created:
        flat.extend(c)
    assert "incident" in flat, "incident issue must carry the 'incident' label"


# ============================================================
# 5. Non-materializer role rejected at create_card_issue
# ============================================================

def test_non_materializer_role_rejected():
    """impl/verify/auditor/planner 调用 create_card_issue → ValueError 越权。"""
    base = {"id": "C-X", "objective": "O1", "tier": "standard",
            "paths": ["src/utils/**"], "charter": ["G0"],
            "acceptance": ["AC1: works"]}
    for bad_role in ("impl", "verify", "auditor", "planner"):
        with pytest.raises(ValueError, match="ROLE_VALVE_VIOLATION"):
            M.create_card_issue(dict(base), 1, 1, role=bad_role)


def test_incident_role_can_create_hotfix_card():
    """incident role 在限额内可以造 hotfix Card（正向阀门）。"""
    card = {"id": "C-HF", "objective": "O1", "tier": "standard",
            "paths": ["src/utils/**"], "charter": ["G0"],
            "acceptance": ["AC1: hotfix works"]}
    with mock.patch.object(M, "gh", return_value=_cp("https://github.com/x/y/issues/55")):
        num = M.create_card_issue(dict(card), 1, 1, role="incident")
    assert num == 55


# ============================================================
# 6. Incident hotfix daily limit (3rd hotfix refused)
# ============================================================

def test_incident_hotfix_limit_exceeded(capsys):
    """当日已有 2 张 hotfix Card → 第 3 张被限额拒绝。"""
    with mock.patch.object(M, "_count_today_hotfix_cards",
                           return_value=M.INCIDENT_HOTFIX_DAILY_LIMIT), \
         mock.patch.object(M, "gh", return_value=_cp("https://github.com/x/y/issues/999")):
        num = M.open_incident("hotfix: prod down", "body", role="incident")
    assert num is None
    out = capsys.readouterr().out
    assert "INCIDENT_HOTFIX_LIMIT_EXCEEDED" in out


def test_incident_open_under_limit_succeeds():
    """当日 0 张 hotfix Card → incident role 可开 Incident。"""
    with mock.patch.object(M, "_count_today_hotfix_cards", return_value=0), \
         mock.patch.object(M, "gh", return_value=_cp("https://github.com/x/y/issues/77")):
        num = M.open_incident("hotfix: X", "body", role="incident")
    assert num == "77"


# ============================================================
# 7. Unauthorized comment author ignored
# ============================================================

def test_unauthorized_comment_author_ignored(monkeypatch, capsys):
    """非白名单作者发 !drop → 直接忽略，打印 UNAUTHORIZED_COMMENT_AUTHOR。"""
    monkeypatch.setenv("COMMAND_AUTHORS", "alice,bob")
    # eve 不在白名单 → 忽略，且不应触发任何 gh 调用
    with mock.patch.object(C, "gh", side_effect=AssertionError("gh must not be called for unauthorized author")):
        result = C.process_comment(123, "!drop O1", "eve")
    assert result["action"] == "skip"
    assert "unauthorized" in result["reason"]
    out = capsys.readouterr().out
    assert "UNAUTHORIZED_COMMENT_AUTHOR" in out


def test_whitelisted_author_passes_gate(monkeypatch, capsys):
    """白名单作者通过阀门（无微指令 → skip 'no commands found'）。"""
    monkeypatch.setenv("COMMAND_AUTHORS", "alice")
    with mock.patch.object(C, "gh", side_effect=AssertionError("gh must not be called when no commands")):
        result = C.process_comment(123, "just a regular comment", "alice")
    assert result["action"] == "skip"
    assert result["reason"] == "no commands found"
    out = capsys.readouterr().out
    assert "UNAUTHORIZED_COMMENT_AUTHOR" not in out
