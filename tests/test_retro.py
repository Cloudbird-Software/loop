#!/usr/bin/env python3
"""tests/test_retro.py — R14-2 波次验收与通知通道测试。

覆盖：
  - run_wave_acceptance：全通过 / 某条失败 / human-verify 超 1/3 违规 / 报告归档 / 段落解析
  - notify：波次通过 / 波次失败 / Incident 升级 / dry-run 不调 gh

所有 gh 调用与机检命令通过 monkeypatch 替换 subprocess.run，不依赖真实网络与真实命令。
"""
import json
import os
import sys

import pytest

# 把仓库根加入 sys.path，使 `from conductor import retro` 与 CLI 走同一命名空间路径。
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from conductor import retro  # noqa: E402


# ── 辅助构造 ────────────────────────────────────────────────
def _write_wave(tmp_path, wave_id, checks):
    """写一个最小 Wave 文件。checks: [(number, text), ...]。

    『本波次的检查方法』段用反引号包裹的命令表达机检项；无命令的散文项标 human-verify。
    """
    lines = [
        f"# {wave_id} — test wave",
        "",
        "## 本波次的检查方法（Wave-level Gate）",
        "",
    ]
    for num, text in checks:
        lines.append(f"{num}. {text}")
        lines.append("")
    lines += ["## 卡片", ""]
    p = tmp_path / f"{wave_id}.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


class _FakeCP:
    """模拟 subprocess.CompletedProcess。"""
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_run(monkeypatch, machine_rc=None, gh_rc=0, gh_stdout=""):
    """patch retro.subprocess.run。

    machine_rc: callable(cmd_str) -> (returncode, stdout, stderr)，用于机检命令（shell 字符串）。
    gh 调用（cmd 是 list 且首元素 'gh'）统一返回 (gh_rc, gh_stdout, '')。
    返回 calls 列表，收集所有调用以便断言。
    """
    calls = []
    machine_rc = machine_rc or (lambda c: (0, "ok", ""))

    def fake_run(cmd, *a, **kw):
        calls.append({"cmd": cmd, "a": a, "kw": kw})
        if isinstance(cmd, list) and cmd and cmd[0] == "gh":
            return _FakeCP(gh_rc, gh_stdout, "")
        rc, out, err = machine_rc(cmd)
        return _FakeCP(rc, out, err)

    monkeypatch.setattr(retro.subprocess, "run", fake_run)
    return calls


def _gh_calls(calls):
    return [c for c in calls if isinstance(c["cmd"], list) and c["cmd"] and c["cmd"][0] == "gh"]


# ── run_wave_acceptance ────────────────────────────────────
def test_run_wave_acceptance_all_pass(tmp_path, monkeypatch):
    """全通过：所有机检项 pass、无 human-verify → status=passed。"""
    wf = _write_wave(tmp_path, "WAVE-99", [
        (1, "跑测试 `python3 -m pytest tests/ -q`"),
        (2, "跑假绿检查 `bash lenses/no-fake-green.sh`"),
    ])
    _patch_run(monkeypatch)  # 机检全部返回 0
    report = retro.run_wave_acceptance(wf, repo_root=str(tmp_path))
    assert report["status"] == "passed"
    assert report["machine_checks_passed"] == 2
    assert report["machine_checks_failed"] == 0
    assert report["human_verify_count"] == 0
    assert report["human_verify_violation"] is False
    # 每条检查项有真实命令与输出
    assert all(c["command"] for c in report["checks"])
    assert all(c["exit_code"] == 0 for c in report["checks"])


def test_run_wave_acceptance_one_fails(tmp_path, monkeypatch):
    """某条失败：一条机检失败 → status=failed，且失败项含真实输出。"""
    wf = _write_wave(tmp_path, "WAVE-98", [
        (1, "跑测试 `python3 -m pytest tests/ -q`"),
        (2, "必失败的检查 `python3 -c \"exit 1\"`"),
    ])

    def machine_rc(cmd):
        if "exit 1" in cmd:
            return (1, "", "boom")
        return (0, "ok", "")

    _patch_run(monkeypatch, machine_rc=machine_rc)
    report = retro.run_wave_acceptance(wf, repo_root=str(tmp_path))
    assert report["status"] == "failed"
    assert report["machine_checks_failed"] == 1
    assert report["machine_checks_passed"] == 1
    failed = [c for c in report["checks"] if c["passed"] is False]
    assert len(failed) == 1
    assert failed[0]["exit_code"] == 1
    assert failed[0]["stderr"] == "boom"  # 真实输出被记录


def test_run_wave_acceptance_human_verify_overflow(tmp_path, monkeypatch):
    """human-verify 项超 1/3 → 标记违规，并生成待办清单。"""
    wf = _write_wave(tmp_path, "WAVE-97", [
        (1, "人为观察 7 天连续运行"),
        (2, "人类签署验收报告"),
        (3, "跑测试 `python3 -m pytest tests/ -q`"),
    ])
    _patch_run(monkeypatch)  # 机检项（第 3 条）pass
    report = retro.run_wave_acceptance(wf, repo_root=str(tmp_path))
    # 3 项中 2 项 human-verify → 2*3=6 > 3 → 违规
    assert report["human_verify_count"] == 2
    assert report["human_verify_violation"] is True
    assert report["status"] == "failed"
    # 待办清单自动生成，不静默挂起
    assert len(report["human_verify_todos"]) == 2
    assert all("需人类验证" in t["action"] for t in report["human_verify_todos"])


def test_run_wave_acceptance_writes_evidence(tmp_path, monkeypatch):
    """报告归档进 evidence/wave-acceptance/<wave-id>.json。"""
    wf = _write_wave(tmp_path, "WAVE-96", [
        (1, "跑测试 `python3 -m pytest tests/ -q`"),
    ])
    _patch_run(monkeypatch)
    report = retro.run_wave_acceptance(wf, repo_root=str(tmp_path))
    ev = os.path.join(str(tmp_path), "evidence", "wave-acceptance", "WAVE-96.json")
    assert os.path.isfile(ev), f"evidence report not written: {ev}"
    data = json.load(open(ev, encoding="utf-8"))
    assert data["wave_id"] == "WAVE-96"
    assert data["status"] == "passed"
    assert data["schema"] == "wave-acceptance-v1"
    # 落盘 JSON 不含内部字段 _report_path（保持报告干净）
    assert "_report_path" not in data
    # 返回值含 _report_path 指向落盘路径
    assert report["_report_path"] == ev


def test_run_wave_acceptance_parses_section(tmp_path):
    """解析 WAVE-XX.md 的『本波次的检查方法』段：编号、文本、命令提取。"""
    wf = _write_wave(tmp_path, "WAVE-95", [
        (1, "第一项检查 `python3 -m pytest`"),
        (2, "第二项：人为观察 7 天"),
    ])
    items = retro._parse_acceptance_section(wf)
    assert len(items) == 2
    assert items[0]["id"] == 1
    assert items[1]["id"] == 2
    # 反引号命令被提取
    assert items[0]["command"] == "python3 -m pytest"
    # 无反引号命令 → None
    assert items[1]["command"] is None


def test_run_wave_acceptance_needs_human_within_ratio(tmp_path, monkeypatch):
    """全部机检通过、human-verify 在 1/3 内 → status=needs_human（不自动关闭）。"""
    wf = _write_wave(tmp_path, "WAVE-94", [
        (1, "跑测试 `python3 -m pytest tests/ -q`"),
        (2, "跑假绿检查 `bash lenses/no-fake-green.sh`"),
        (3, "人为签署最终验收"),
    ])
    _patch_run(monkeypatch)
    report = retro.run_wave_acceptance(wf, repo_root=str(tmp_path))
    # 3 项中 1 项 human-verify → 1*3=3 不大于 3 → 未违规
    assert report["human_verify_count"] == 1
    assert report["human_verify_violation"] is False
    # 全部机检通过但有 human-verify → needs_human
    assert report["status"] == "needs_human"
    assert report["machine_checks_failed"] == 0


# ── notify ─────────────────────────────────────────────────
def test_notify_wave_passed(monkeypatch):
    """波次通过 → 调 gh issue comment 贴到父 issue。"""
    monkeypatch.delenv("LOOP_NOTIFY_DRY_RUN", raising=False)
    calls = _patch_run(monkeypatch, gh_stdout="https://github.com/o/r/issues/1#issuecomment-9")
    sent = retro.notify(
        "wave_passed",
        {"wave_id": "WAVE-14", "parent_issue": 42, "report": {"summary": "total=1, machine_passed=1"}},
        repo="o/r",
    )
    assert sent["returncode"] == 0
    gh = _gh_calls(calls)
    assert len(gh) == 1
    cmd = gh[0]["cmd"]
    assert cmd[1] == "issue" and cmd[2] == "comment"
    assert "42" in cmd  # 贴到父 issue #42
    assert "-R" in cmd and "o/r" in cmd


def test_notify_wave_failed(monkeypatch):
    """波次失败 → 调 gh issue comment 贴到父 issue。"""
    monkeypatch.delenv("LOOP_NOTIFY_DRY_RUN", raising=False)
    calls = _patch_run(monkeypatch, gh_stdout="comment-url")
    sent = retro.notify(
        "wave_failed",
        {"wave_id": "WAVE-14", "parent_issue": 7, "report": {"summary": "machine_failed=1"}},
        repo="o/r",
    )
    assert sent["returncode"] == 0
    gh = _gh_calls(calls)
    assert len(gh) == 1
    assert gh[0]["cmd"][1] == "issue" and gh[0]["cmd"][2] == "comment"
    assert "7" in gh[0]["cmd"]


def test_notify_incident(monkeypatch):
    """Incident 升级 → 调 gh issue create 开新 issue（label: incident）。"""
    monkeypatch.delenv("LOOP_NOTIFY_DRY_RUN", raising=False)
    calls = _patch_run(monkeypatch, gh_stdout="https://github.com/o/r/issues/55")
    sent = retro.notify(
        "incident",
        {"wave_id": "WAVE-14", "title": "Incident: bench 劣化", "message": "Q1 超阈值"},
        repo="o/r",
    )
    assert sent["returncode"] == 0
    assert sent["issue_url"] == "https://github.com/o/r/issues/55"
    gh = _gh_calls(calls)
    assert len(gh) == 1
    cmd = gh[0]["cmd"]
    assert cmd[1] == "issue" and cmd[2] == "create"
    assert "--label" in cmd
    assert "incident" in cmd  # 默认 incident 标签


def test_notify_dry_run(monkeypatch):
    """dry-run → 不调 gh，只返回 would-send。"""
    calls = _patch_run(monkeypatch)
    sent = retro.notify(
        "wave_passed",
        {"wave_id": "WAVE-14", "parent_issue": 42, "report": {}, "dry_run": True},
        repo="o/r",
    )
    assert sent["dry_run"] is True
    assert sent["would_send"] is True
    # 不产生任何 gh 调用
    assert len(_gh_calls(calls)) == 0


def test_notify_dry_run_via_env(monkeypatch):
    """LOOP_NOTIFY_DRY_RUN=1 → 同样不调 gh。"""
    monkeypatch.setenv("LOOP_NOTIFY_DRY_RUN", "1")
    calls = _patch_run(monkeypatch)
    sent = retro.notify(
        "incident",
        {"wave_id": "WAVE-14", "title": "Incident", "message": "x"},
        repo="o/r",
    )
    assert sent["dry_run"] is True
    assert len(_gh_calls(calls)) == 0
