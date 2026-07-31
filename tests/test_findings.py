"""tests/test_findings.py — R14-1 conductor.findings 单元测试。

用 monkeypatch 替换 subprocess.run，不依赖真实网络 / gh CLI。
覆盖：fingerprint 稳定性、create/find/update/close 四个原子操作、
dry-run、gh 失败抛 RuntimeError、与 conductor.tick.fingerprint 的兼容性。
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from conductor import findings  # noqa: E402


# ── 公共夹具：每条用例前清掉 FINDINGS_DRY_RUN，避免互相污染 ────────────────

@pytest.fixture(autouse=True)
def _clean_dry_run(monkeypatch):
    monkeypatch.delenv("FINDINGS_DRY_RUN", raising=False)
    yield


class FakeProc:
    """subprocess.run 的轻量替身，只暴露 returncode / stdout / stderr。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _recorder(monkeypatch, proc, record_calls=True):
    """装一个 fake subprocess.run：返回固定 FakeProc，并记录每次调用的命令。"""
    calls = []

    def fake_run(cmd, *a, **kw):
        if record_calls:
            calls.append(list(cmd))
        return proc

    monkeypatch.setattr(findings.subprocess, "run", fake_run)
    return calls


# ── fingerprint ──────────────────────────────────────────────────────────

def test_fingerprint_stable_for_same_input():
    """相同输入必须产生相同指纹（稳定性，去重键的前提）。"""
    a = findings.fingerprint("ci-security", "a/b.py", "foo", "R1")
    b = findings.fingerprint("ci-security", "a/b.py", "foo", "R1")
    assert a == b
    # SHA-256 前 16 位 hex
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_fingerprint_different_for_different_input():
    """任一字段不同即应不同（避免不同根因撞同一指纹）。"""
    base = findings.fingerprint("ci-security", "a/b.py", "foo", "R1")
    assert findings.fingerprint("ci-security", "a/b.py", "foo", "R2") != base
    assert findings.fingerprint("secret-leak", "a/b.py", "foo", "R1") != base
    assert findings.fingerprint("ci-security", "c/d.py", "foo", "R1") != base
    assert findings.fingerprint("ci-security", "a/b.py", "bar", "R1") != base


def test_fingerprint_compatible_with_tick():
    """findings.fingerprint 输出必须与 conductor.tick.fingerprint 完全一致。

    这样 state.json 中既有的指纹键、issue 搜索的查重键才不会因换实现而漂移。
    """
    from conductor import tick
    args = ("ci-security", "src/auth/login.py", "verify_token", "template-injection")
    assert findings.fingerprint(*args) == tick.fingerprint(*args)


# ── create_finding ───────────────────────────────────────────────────────

def test_create_finding_dry_run_returns_fake_number(monkeypatch):
    """FINDINGS_DRY_RUN=1 时不触网，返回假号 999999。"""
    monkeypatch.setenv("FINDINGS_DRY_RUN", "1")
    calls = _recorder(monkeypatch, FakeProc(0, "https://github.com/o/r/issues/1\n", ""))
    num = findings.create_finding("ci-security", "a/b.py", "foo", "R1", "high", {"k": "v"})
    assert num == findings.DRY_RUN_FAKE_NUMBER == 999999
    assert calls == []  # dry-run 绝不调 gh


def test_create_finding_production_calls_gh_issue_create_with_label(monkeypatch):
    """生产模式：必须调 gh issue create 且带 --label lens-finding，并解析返回真实 issue 号。"""
    # label create（成功）+ issue create（成功，输出 issue URL）
    calls = _recorder(monkeypatch, FakeProc(0, "https://github.com/ORG/REPO/issues/42\n", ""))
    num = findings.create_finding("ci-security", "a/b.py", "foo", "R1", "high", {"k": "v"})
    assert num == 42
    # 至少有一次调用形如 gh issue create ... --label lens-finding
    create_calls = [c for c in calls if "issue" in c and "create" in c]
    assert create_calls, calls
    c = create_calls[0]
    assert "--label" in c and findings.LENS_FINDING_LABEL in c
    assert "--title" in c and "--body" in c


def test_create_finding_gh_failure_raises_runtime_error(monkeypatch):
    """gh issue create 非零退出时必须抛 RuntimeError（不静默）。"""
    # label create 成功，issue create 失败
    outputs = iter([FakeProc(0, "", ""), FakeProc(1, "", "boom")])

    def fake_run(cmd, *a, **kw):
        return next(outputs)

    monkeypatch.setattr(findings.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        findings.create_finding("ci-security", "a/b.py", "foo", "R1", "high", {"k": "v"})


def test_create_finding_title_contains_lens_path_symbol_rule(monkeypatch):
    """issue 标题格式：[Finding] <lens> <path>:<symbol> (<rule_id>)。"""
    calls = _recorder(monkeypatch, FakeProc(0, "https://github.com/o/r/issues/7\n", ""))
    findings.create_finding("secret-leak", "x/y.py", "load_creds", "gitleaks-aws", "critical", {"v": 1})
    create_calls = [c for c in calls if "issue" in c and "create" in c]
    title_idx = create_calls[0].index("--title")
    title = create_calls[0][title_idx + 1]
    assert title == "[Finding] secret-leak x/y.py:load_creds (gitleaks-aws)"


# ── find_open_finding ────────────────────────────────────────────────────

def test_find_open_finding_returns_number_on_match(monkeypatch):
    """gh 返回非空列表 → 返回首个 issue 号。"""
    _recorder(monkeypatch, FakeProc(0, json.dumps([{"number": 42}, {"number": 43}]), ""))
    assert findings.find_open_finding("abc12345deadbeef") == 42


def test_find_open_finding_returns_none_when_no_match(monkeypatch):
    """gh 返回空列表 → None。"""
    _recorder(monkeypatch, FakeProc(0, "[]", ""))
    assert findings.find_open_finding("abc12345deadbeef") is None


def test_find_open_finding_uses_label_and_search(monkeypatch):
    """查重命令必须含 --label lens-finding --state open --search <fp>。"""
    calls = _recorder(monkeypatch, FakeProc(0, "[]", ""))
    findings.find_open_finding("deadbeefdeadbeef")
    list_calls = [c for c in calls if "issue" in c and "list" in c]
    assert list_calls, calls
    c = list_calls[0]
    assert "--label" in c and findings.LENS_FINDING_LABEL in c
    assert "--state" in c and "open" in c
    assert "--search" in c and "deadbeefdeadbeef" in c


def test_find_open_finding_gh_failure_raises_runtime_error(monkeypatch):
    """gh issue list 非零退出 → RuntimeError（不静默吞错）。"""
    monkeypatch.setattr(findings.subprocess, "run",
                        lambda cmd, *a, **k: FakeProc(1, "", "auth error"))
    with pytest.raises(RuntimeError):
        findings.find_open_finding("abc12345deadbeef")


# ── update_finding ───────────────────────────────────────────────────────

def test_update_finding_calls_gh_issue_comment(monkeypatch):
    """update_finding 必须调 gh issue comment <n> --body <note>。"""
    calls = _recorder(monkeypatch, FakeProc(0, "", ""))
    findings.update_finding(42, "occurrences=2 last_seen=123")
    comment_calls = [c for c in calls if "issue" in c and "comment" in c]
    assert comment_calls, calls
    c = comment_calls[0]
    assert "42" in c
    body_idx = c.index("--body")
    assert c[body_idx + 1] == "occurrences=2 last_seen=123"


def test_update_finding_dry_run_does_not_call_gh(monkeypatch):
    """dry-run 模式下 update_finding 不触网。"""
    monkeypatch.setenv("FINDINGS_DRY_RUN", "1")
    calls = _recorder(monkeypatch, FakeProc(0, "", ""))
    findings.update_finding(42, "note")
    assert calls == []


# ── close_finding ────────────────────────────────────────────────────────

def test_close_finding_calls_gh_issue_close_and_comment(monkeypatch):
    """close_finding 必须（先）调 gh issue comment 附理由，并（后）调 gh issue close。"""
    calls = _recorder(monkeypatch, FakeProc(0, "", ""))
    findings.close_finding(42, "stale 21d no occurrences")
    has_comment = any("issue" in c and "comment" in c and "42" in c for c in calls)
    has_close = any("issue" in c and "close" in c and "42" in c for c in calls)
    assert has_comment, calls
    assert has_close, calls
    # 理由必须出现在某条 comment 的 --body 里
    comment_calls = [c for c in calls if "issue" in c and "comment" in c]
    bodies = [c[c.index("--body") + 1] for c in comment_calls if "--body" in c]
    assert any("stale 21d no occurrences" in b for b in bodies), bodies


def test_close_finding_close_failure_raises_runtime_error(monkeypatch):
    """comment 成功但 close 失败 → 抛 RuntimeError。"""
    outputs = iter([FakeProc(0, "", ""), FakeProc(1, "", "close denied")])

    def fake_run(cmd, *a, **kw):
        return next(outputs)

    monkeypatch.setattr(findings.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        findings.close_finding(42, "stale")


# ── 闭环：find→update / find→create 的典型编排（不触网，验证签名兼容） ────

def test_find_then_update_uses_same_fingerprint_key(monkeypatch):
    """编排：同一指纹查重命中 → update 同一 issue 号（验证 fp 作为贯穿键）。"""
    fp = findings.fingerprint("ci-security", "a/b.py", "foo", "R1")
    seen_nums = []

    def fake_run(cmd, *a, **kw):
        # find_open_finding 的 list 调用返回命中 #55
        if "list" in cmd:
            return FakeProc(0, json.dumps([{"number": 55}]), "")
        # update_finding 的 comment 调用记录 issue 号
        if "comment" in cmd:
            seen_nums.append(cmd[cmd.index(str(55))])
            return FakeProc(0, "", "")
        return FakeProc(0, "", "")

    monkeypatch.setattr(findings.subprocess, "run", fake_run)
    existing = findings.find_open_finding(fp)
    assert existing == 55
    findings.update_finding(existing, "bump")
    assert "55" in seen_nums
