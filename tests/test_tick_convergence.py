"""tests/test_tick_convergence.py — R11-6 收归验证。

验证 loop 单一 conductor/tick.py 仅靠环境变量/配置即可同时服务 loop 与 product-x
两仓，无需分叉两份代码。只测配置解析逻辑与 --dry-run 输出，**不触网**。

覆盖：
- LOOP_ROOT 三种情况（unset / 相对路径 / 绝对路径）+ 优先级回退
- REPO / CONTROL_REPO 在 product-x 与 loop 两套环境变量组合下的解析
- main(['--dry-run']) 打印解析后的配置并在任何 gh 调用前退出（无网络）
"""
import os
import pathlib
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from conductor import tick  # noqa: E402


# ── LOOP_ROOT 三种情况 (acceptance #1, #3) ────────────────────────────────

def test_loop_root_unset_falls_back_to_workspace():
    """LOOP_ROOT 与 GITHUB_WORKSPACE 均未设置 → /workspace 兜底（绝对，原样使用）。"""
    env = {"GITHUB_REPOSITORY_OWNER": "Cloudbird-Software"}  # 故意不含 LOOP_ROOT / GITHUB_WORKSPACE
    assert tick.resolve_loop_root(env) == pathlib.Path("/workspace")
    assert tick.resolve_loop_root(env).is_absolute()


def test_loop_root_relative_resolved_against_cwd():
    """相对 LOOP_ROOT → 相对 cwd 解析为绝对路径。"""
    env = {"LOOP_ROOT": "some/relative/path"}
    got = tick.resolve_loop_root(env)
    assert got == pathlib.Path.cwd() / "some/relative/path"
    assert got.is_absolute()


def test_loop_root_absolute_used_as_is():
    """绝对 LOOP_ROOT → 原样使用（不重新拼 cwd）。"""
    env = {"LOOP_ROOT": "/tmp/loop-root-abs"}
    assert tick.resolve_loop_root(env) == pathlib.Path("/tmp/loop-root-abs")


def test_loop_root_beats_github_workspace():
    """LOOP_ROOT 优先于 GITHUB_WORKSPACE。"""
    env = {"LOOP_ROOT": "/lr", "GITHUB_WORKSPACE": "/gh"}
    assert tick.resolve_loop_root(env) == pathlib.Path("/lr")


def test_github_workspace_used_when_loop_root_unset():
    """LOOP_ROOT 未设置但 GITHUB_WORKSPACE 设置 → 用 GITHUB_WORKSPACE。"""
    env = {"GITHUB_WORKSPACE": "/gh/ws"}
    assert tick.resolve_loop_root(env) == pathlib.Path("/gh/ws")


# ── REPO / CONTROL_REPO 两仓组合 (acceptance #1, #3) ──────────────────────

def test_repo_and_control_repo_for_product_x_combo():
    """product-x 组合：LOOP_REPO=product-x → REPO 指向 product-x，CONTROL_REPO 默认指向 loop。"""
    env = {"LOOP_ORG": "Cloudbird-Software", "LOOP_REPO": "product-x"}
    assert tick.resolve_repo(env) == "Cloudbird-Software/product-x"
    # 控制面工作流（canary/scribe/audit/...）始终跑在 loop，而非 product-x
    assert tick.resolve_control_repo(env) == "Cloudbird-Software/loop"


def test_repo_and_control_repo_for_loop_combo():
    """loop 组合：LOOP_REPO=loop → REPO 与 CONTROL_REPO 都指向 loop。"""
    env = {"LOOP_ORG": "Cloudbird-Software", "LOOP_REPO": "loop"}
    assert tick.resolve_repo(env) == "Cloudbird-Software/loop"
    assert tick.resolve_control_repo(env) == "Cloudbird-Software/loop"


def test_control_repo_explicit_override():
    """LOOP_CONTROL_REPO 显式覆盖优先级最高。"""
    env = {"LOOP_ORG": "Cloudbird-Software", "LOOP_REPO": "product-x",
           "LOOP_CONTROL_REPO": "Cloudbird-Software/loop"}
    assert tick.resolve_control_repo(env) == "Cloudbird-Software/loop"


def test_control_repo_github_repository_fallback():
    """无 LOOP_CONTROL_REPO 时回退到 GITHUB_REPOSITORY。"""
    env = {"GITHUB_REPOSITORY": "Cloudbird-Software/loop"}
    assert tick.resolve_control_repo(env) == "Cloudbird-Software/loop"


def test_org_fallback_to_github_repository_owner():
    """LOOP_ORG 未设置时回退到 GITHUB_REPOSITORY_OWNER。"""
    env = {"GITHUB_REPOSITORY_OWNER": "Cloudbird-Software", "LOOP_REPO": "product-x"}
    assert tick.resolve_repo(env) == "Cloudbird-Software/product-x"
    assert tick.resolve_control_repo(env) == "Cloudbird-Software/loop"


# ── --dry-run 输出 (acceptance #2, #3) ────────────────────────────────────

def test_dry_run_product_x_combo(monkeypatch, capsys):
    """--dry-run 在 product-x 组合下打印的解析配置，且在任何 gh 调用前退出（无网络）。"""
    env = {"LOOP_ORG": "Cloudbird-Software", "LOOP_REPO": "product-x"}
    monkeypatch.setattr(tick, "REPO", tick.resolve_repo(env))
    monkeypatch.setattr(tick, "CONTROL_REPO", tick.resolve_control_repo(env))
    monkeypatch.setattr(tick, "LOOP_ROOT", pathlib.Path("/tmp"))
    monkeypatch.setattr(tick, "POLICY_FILE", "policy.yml")

    tick.main(["--dry-run"])  # 显式传 argv，避免 main 读 sys.argv（pytest 参数）

    out = capsys.readouterr().out
    assert "[dry-run] REPO=Cloudbird-Software/product-x" in out
    assert "[dry-run] CONTROL_REPO=Cloudbird-Software/loop" in out
    assert "[dry-run] LOOP_ROOT=/tmp" in out
    assert "[dry-run] POLICY_FILE=policy.yml" in out
    assert "exiting before any gh calls" in out
    # 真正的调度步骤不应出现在 dry-run 输出里（证明提前退出）
    assert "Zombie reclaim" not in out


def test_dry_run_loop_combo(monkeypatch, capsys):
    """--dry-run 在 loop 组合下打印的解析配置（无网络）。"""
    env = {"LOOP_ORG": "Cloudbird-Software", "LOOP_REPO": "loop"}
    monkeypatch.setattr(tick, "REPO", tick.resolve_repo(env))
    monkeypatch.setattr(tick, "CONTROL_REPO", tick.resolve_control_repo(env))
    monkeypatch.setattr(tick, "LOOP_ROOT", pathlib.Path("/workspace"))
    monkeypatch.setattr(tick, "POLICY_FILE", "policy.yml")

    tick.main(["--dry-run"])

    out = capsys.readouterr().out
    assert "[dry-run] REPO=Cloudbird-Software/loop" in out
    assert "[dry-run] CONTROL_REPO=Cloudbird-Software/loop" in out
    assert "[dry-run] LOOP_ROOT=/workspace" in out
    assert "[dry-run] POLICY_FILE=policy.yml" in out
    assert "exiting before any gh calls" in out


def test_dry_run_does_not_read_sys_argv_when_argv_passed(monkeypatch, capsys):
    """显式传 argv 时 main 不读 sys.argv，避免 pytest 参数污染。"""
    monkeypatch.setattr(sys, "argv", ["tick.py", "--unknown-noise", "x"])
    monkeypatch.setattr(tick, "REPO", "Cloudbird-Software/loop")
    monkeypatch.setattr(tick, "CONTROL_REPO", "Cloudbird-Software/loop")
    monkeypatch.setattr(tick, "LOOP_ROOT", pathlib.Path("/ws"))
    monkeypatch.setattr(tick, "POLICY_FILE", "policy.yml")
    tick.main(["--dry-run"])
    out = capsys.readouterr().out
    assert "[dry-run] REPO=Cloudbird-Software/loop" in out
    assert "--unknown-noise" not in out
