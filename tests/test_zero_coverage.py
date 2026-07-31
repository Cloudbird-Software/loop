"""tests/test_zero_coverage.py — 为 6 个低覆盖模块建立最小可信测试（R14-4）。

原则：每条测试必须先被证明能在对应逻辑被破坏时变红。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# 确保项目根在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ============================================================
# conductor/claim_intake.py
# ============================================================
from conductor import claim_intake as ci


def test_build_fcard_state_unconfirmed():
    """破坏点：把 _build_fcard 里 state 改成 'ready' 即红。"""
    claim = {"id": "C-001", "severity": "high", "claim": "memory leak", "path": "src/a.py"}
    fcard = ci._build_fcard(claim, {"review_id": "R1"})
    assert fcard["state"] == "unconfirmed"
    assert fcard["tier"] == "critical"
    assert fcard["claim_id"] == "C-001"


def test_assert_reproduced_blocks_unconfirmed():
    """未复现的 claim 不可被路由到 fix。"""
    with pytest.raises(ci.CLAIM_NOT_REPRODUCED):
        ci.assert_reproduced({"state": "unconfirmed"})


# ============================================================
# conductor/commands.py
# ============================================================
from conductor import commands as cmds


def test_load_allowed_authors_from_env():
    """破坏点：把环境变量名改错或返回空集合即红。"""
    with mock.patch.dict(os.environ, {"COMMAND_AUTHORS": "alice, bob"}):
        assert cmds._load_allowed_authors() == {"alice", "bob"}


def test_parse_drop_instruction():
    """破坏点：正则写错无法识别 !drop O2 即红。"""
    body = "!drop O2\nsome context"
    cmds_list = cmds.parse_commands(body)
    assert cmds_list == [("drop", "O2")]


# ============================================================
# gates/gate_charter.py
# ============================================================
from gates import gate_charter as gc


def test_validate_charter_missing_refs():
    """破坏点：允许空 charter 即红。"""
    ids = {"G0", "G1"}
    bad = gc.validate_charter({}, ids, True)
    assert "MISSING_CHARTER" in bad


def test_validate_charter_unknown_ref():
    """破坏点：未知引用不被拦截即红。"""
    ids = {"G0", "G1"}
    bad = gc.validate_charter({"charter": ["G0", "G99"]}, ids, True)
    assert any("G99" in b for b in bad)


# ============================================================
# gates/gate_license.py
# ============================================================
from gates import gate_license as gl


def test_dep_name_from_line_requirements():
    """破坏点：正则无法识别包名即红。"""
    assert gl.dep_name_from_line("requirements.txt", "requests>=2.0") == "requests"


def test_dep_name_from_line_package_json():
    assert gl.dep_name_from_line("package.json", '  "lodash": "^4.17"') == "lodash"


def test_new_deps_from_diff(tmp_path, monkeypatch):
    """破坏点：未正确解析新增依赖即红。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("olddep==1.0\n")
    monkeypatch.chdir(repo)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "config", "user.name", "T"], check=True)
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "base", "-q"], check=True)
    (repo / "requirements.txt").write_text("olddep==1.0\nnewdep==2.0\n")
    subprocess.run(["git", "add", "."], check=True)
    subprocess.run(["git", "commit", "-m", "add dep", "-q"], check=True)
    deps = gl.new_deps_from_diff("HEAD~1", "HEAD")
    assert "newdep" in deps


# ============================================================
# loopd/loopd.py — 纯函数部分
# ============================================================
import loopd.loopd as loopd


def test_validate_finding_requires_message():
    """破坏点：缺少 message 仍返回通过即红。"""
    ok, msg = loopd._validate_finding({"severity": "high", "path": "a.py"})
    assert not ok
    assert "message" in msg.lower()


def test_validate_verdict_required_fields():
    """破坏点：verdict 缺 sha 不被拦截即红。"""
    ok, msg = loopd._validate_verdict({"verdict": "PASS", "evidence": "ok"})
    assert not ok
    assert "sha" in msg.lower()


def test_iso_to_ts_parses_z():
    """破坏点：无法解析 ISO-Z 时间即红。"""
    assert loopd._iso_to_ts("2026-07-31T12:00:00Z") > 0


def test_prio_trivial_lower_than_critical():
    """破坏点：trivial 优先级数字不小于 critical 即红（数字越小优先级越高）。"""
    assert loopd.prio({"tier": "trivial"}) < loopd.prio({"tier": "critical"})


# ============================================================
# gates/gate_heterogeneity.py — 补一个产品仓场景
# ============================================================
from gates import gate_heterogeneity as gh


def test_load_yaml_falls_back_to_loop_root(tmp_path, monkeypatch):
    """破坏点：本地无 ROUTING.yaml 时不从 LOOP_ROOT 回退即红。"""
    loop_root = tmp_path / "loop"
    loop_root.mkdir()
    routing = loop_root / "ROUTING.yaml"
    routing.write_text("routes:\n  - domain: review\n    action: accept\n    provider: p\n    model: m\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOOP_ROOT", str(loop_root))
    data = gh.load_yaml("ROUTING.yaml")
    assert data is not None
    assert data["routes"][0]["model"] == "m"
