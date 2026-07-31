"""tests/test_pr_ci_negative.py — R10-1 负向测试。

对 no-fake-green 与 actions-pinned 两个扫描器各构造『必须违规』与『合规』输入，
断言返回非空 / 空。直接调用 conductor.scan_workflows 本体，不复制平行实现。
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from conductor.scan_workflows import scan_no_fake_green, scan_actions_pinned  # noqa: E402

SHA40 = "11d5960a326750d5838078e36cf38b85af677262"  # 真实 checkout SHA，合规


def _wf(tmp_path, name, body):
    d = tmp_path / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return str(d)


# ── no-fake-green 负向：必须检出 ──────────────────────────────────────────

def test_no_fake_green_catches_pipe_true(tmp_path):
    d = _wf(tmp_path, "bad.yml", "      run: flaky || true\n")
    assert scan_no_fake_green(d) != []


def test_no_fake_green_catches_set_plus_e(tmp_path):
    d = _wf(tmp_path, "bad.yml", "      run: |\n        set +e\n        flaky\n")
    assert scan_no_fake_green(d) != []


def test_no_fake_green_catches_continue_on_error(tmp_path):
    d = _wf(tmp_path, "bad.yml", "    continue-on-error: true\n")
    assert scan_no_fake_green(d) != []


# ── no-fake-green 正向：合规输入必须放行 ──────────────────────────────────

def test_no_fake_green_allows_pipe_true_with_mark(tmp_path):
    d = _wf(tmp_path, "ok.yml", "      # fake-green-ok: 扫描器自身的模式定义\n      run: || true\n")
    assert scan_no_fake_green(d) == []


def test_no_fake_green_allows_inline_mark(tmp_path):
    d = _wf(tmp_path, "ok.yml", "      run: || true  # fake-green-ok: demo\n")
    assert scan_no_fake_green(d) == []


def test_no_fake_green_clean_workflow_passes(tmp_path):
    d = _wf(tmp_path, "ok.yml",
            "on: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo hi\n")
    assert scan_no_fake_green(d) == []


def test_no_fake_green_ignores_comment_lines(tmp_path):
    d = _wf(tmp_path, "ok.yml", "#      run: flaky || true\n# just a comment\n")
    assert scan_no_fake_green(d) == []


# ── actions-pinned 负向：必须检出 ─────────────────────────────────────────

def test_actions_pinned_catches_v4_tag(tmp_path):
    d = _wf(tmp_path, "bad.yml", "      - uses: actions/checkout@v4\n")
    assert scan_actions_pinned(d) != []


def test_actions_pinned_catches_no_ref(tmp_path):
    d = _wf(tmp_path, "bad.yml", "      - uses: actions/checkout\n")
    assert scan_actions_pinned(d) != []


def test_actions_pinned_catches_short_sha(tmp_path):
    d = _wf(tmp_path, "bad.yml", "      - uses: actions/checkout@11d5960\n")
    assert scan_actions_pinned(d) != []


# ── actions-pinned 正向：合规输入必须放行 ─────────────────────────────────

def test_actions_pinned_allows_full_sha(tmp_path):
    d = _wf(tmp_path, "ok.yml", f"      - uses: actions/checkout@{SHA40} # v4.4.0\n")
    assert scan_actions_pinned(d) == []


def test_actions_pinned_allows_local_ref(tmp_path):
    d = _wf(tmp_path, "ok.yml", "      - uses: ./.github/actions/my-action\n")
    assert scan_actions_pinned(d) == []


def test_actions_pinned_allows_docker_ref(tmp_path):
    d = _wf(tmp_path, "ok.yml", "      - uses: docker://alpine:3.19\n")
    assert scan_actions_pinned(d) == []


# ── 本仓自身 workflow 必须干净（防回归）──────────────────────────────────

def test_real_repo_no_fake_green():
    """loop 仓 .github/workflows/ 不得有任何未标注的假绿。"""
    assert scan_no_fake_green() == []


def test_real_repo_actions_pinned():
    """loop 仓所有 uses 引用必须钉到 40 位 SHA。"""
    assert scan_actions_pinned() == []
