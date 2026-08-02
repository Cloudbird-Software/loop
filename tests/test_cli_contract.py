"""契约测试：对 loopd CLI 的 16 个动词做黑盒契约验证（AC-1/AC-2）。

AC-2 硬约束：本文件绝不 import loopd 内部模块，一律通过 subprocess 调用
`python loopd/loopd.py <verb> [args]`（sys.executable + Path 拼接）。
(依 _GATE 由 test_cli_meta.py 做元测试强制。)

范围说明：按要求只测"无副作用"场景（help、未知动词、缺参/参数错误、missing 文件、
drop 进临时 trash、仅读 UPSTREAM.yaml 等），所有副作用隔离在 pytest 的 tmp_path 下，
绝不调用 next/done/verify/reset/save 等会阻塞或改动 git/GitHub 状态的命令。
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOOPD = ROOT / "loopd" / "loopd.py"
PY = sys.executable

# 与 loopd.VERBS 契约一致（16 个已知动词）
EXPECTED_VERBS = [
    "next", "save", "verify", "done", "drop", "reset", "ask",
    "evidence", "finding", "propose", "verdict", "upstream",
    "retire", "status", "tick", "help",
]


def run_cli(verb, args, cwd):
    """在隔离目录 cwd 下以 subprocess 调用 loopd.py，带干净且可预测的 LOOP_ROOT/LOOP_WS。"""
    env = dict(os.environ)
    env["LOOP_ROOT"] = str(cwd)
    env["LOOP_WS"] = str(cwd)
    cmd = [PY, str(LOOPD)] + [verb] + list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=120
    )


# ---------- help / 版本 ----------
@pytest.mark.parametrize("flag", ["help", "--help", "-h"])
def test_help_ok(tmp_path, flag):
    """help 三形态均 exit 0，且 JSON 报告 count=16。"""
    p = run_cli(flag, [], tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["count"] == 16
    assert len(data["verbs"]) == 16


def test_help_lists_all_16_verbs(tmp_path):
    """help 的 verbs 集合与期望契约完全一致。"""
    p = run_cli("help", [], tmp_path)
    assert p.returncode == 0
    data = json.loads(p.stdout)
    assert set(data["verbs"]) == set(EXPECTED_VERBS)


@pytest.mark.parametrize("verb", EXPECTED_VERBS)
def test_verb_in_help_table(tmp_path, verb):
    """每个已知动词都出现在 help 的 verbs 表里。"""
    data = json.loads(run_cli("help", [], tmp_path).stdout)
    assert verb in data["verbs"]


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_ok(tmp_path, flag):
    """--version/-v exit 0 且含 version 字段。"""
    p = run_cli(flag, [], tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "version" in json.loads(p.stdout)


# ---------- 未知动词（exit 64） ----------
@pytest.mark.parametrize(
    "unknown",
    [
        "nope", "foo", "save2", "NEXT", "Help",
        "evidenc", "retire2", "status2",
    ],
)
def test_unknown_verb_exit_64(tmp_path, unknown):
    """未注册动词 → exit 64 且报 UNKNOWN_VERB。"""
    p = run_cli(unknown, [], tmp_path)
    assert p.returncode == 64
    assert "UNKNOWN_VERB" in (p.stdout or "")


# ---------- 缺参 / 找不到目标的失败路径（无副作用） ----------
@pytest.mark.parametrize(
    "verb,args,code,expect",
    [
        ("drop", [], 64, "USAGE"),
        ("ask", [], 64, "USAGE"),
        ("evidence", [], 64, "USAGE"),
        ("finding", [], 64, "USAGE"),
        ("propose", [], 64, "USAGE"),
        ("verdict", [], 64, "USAGE"),
        ("upstream", [], 64, "USAGE"),
        ("drop", ["no_such_file.txt"], 1, "NOT_FOUND"),
        ("evidence", ["no_such_lens"], 1, "UNKNOWN_LENS"),
        ("finding", ["missing_finding.json"], 1, "NOT_FOUND"),
        ("propose", ["missing_wave.md"], 1, "NOT_FOUND"),
        ("verdict", ["missing_verdict.json"], 1, "NOT_FOUND"),
    ],
)
def test_usage_and_not_found_failures(tmp_path, verb, args, code, expect):
    """缺参 → USAGE(64)；目标缺失 → 1 且带明确错误码。全部无副作用。"""
    p = run_cli(verb, args, tmp_path)
    assert p.returncode == code, (verb, args, p.stdout, p.stderr)
    body = p.stdout or p.stderr or ""
    assert expect in body, (verb, args, body)


# ---------- 成功路径（副作用隔离在 tmp 内） ----------
def test_drop_success_moves_to_trash(tmp_path):
    """drop 存在文件 → exit 0，文件移入 .loop/trash，原处消失。"""
    f = tmp_path / "hello.txt"
    f.write_text("x")
    p = run_cli("drop", ["hello.txt"], tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DROPPED" in p.stdout
    assert not f.exists()
    trash = tmp_path / ".loop" / "trash"
    assert any(trash.glob("hello.txt*")), "文件未移入 trash"


def test_finding_bad_json_exit_1(tmp_path):
    """finding 指向存在但非法 JSON → exit 1 且报 BAD_JSON。"""
    (tmp_path / "bad.json").write_text("not json{")
    p = run_cli("finding", ["bad.json"], tmp_path)
    assert p.returncode == 1
    assert "BAD_JSON" in (p.stdout or "")


def test_verdict_bad_json_exit_1(tmp_path):
    """verdict 指向存在但非法 JSON → exit 1 且报 BAD_JSON。"""
    (tmp_path / "bad.json").write_text("not json{")
    p = run_cli("verdict", ["bad.json"], tmp_path)
    assert p.returncode == 1
    assert "BAD_JSON" in (p.stdout or "")


def test_upstream_no_upstream_yaml_exit_1(tmp_path):
    """无 UPSTREAM.yaml → exit 1 且报 NOT_REGISTERED。"""
    p = run_cli("upstream", ["requests"], tmp_path)
    assert p.returncode == 1
    assert "NOT_REGISTERED" in (p.stdout or "")


def test_upstream_registered_success(tmp_path):
    """UPSTREAM.yaml 含该包名 → exit 0 且报 OK（纯读文件，无副作用）。"""
    (tmp_path / "UPSTREAM.yaml").write_text("requests\n")
    p = run_cli("upstream", ["requests"], tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK" in p.stdout