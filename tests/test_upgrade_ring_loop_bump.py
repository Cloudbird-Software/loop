"""tests/test_upgrade_ring_loop_bump.py — conductor/upgrade_ring.py 的 loop 控制面
bump PR 逻辑测试（R13-6 #3/#4/#5）。

覆盖 is_loop_control_plane / load_products_yml / bump_loop_pin / open_rollback_pr
（以及辅助 _apply_file_change）的核心分支。所有 gh 调用通过 monkeypatch 替换
upgrade_ring.subprocess.run，不依赖真实网络/gh。
"""
import base64 as _b64
import json
import os
import sys

import pytest

# 把仓库根加入 sys.path，使 `from conductor import upgrade_ring` 与
# `python3 -m conductor.upgrade_ring` 走同一命名空间包路径。
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from conductor import upgrade_ring as ur  # noqa: E402

PIN_SHA = "a" * 40
NEW_SHA = "b" * 40
LOOP_REPO = "Cloudbird-Software/loop"
PRODUCT_REPO = "Cloudbird-Software/product-x"


class _Args:
    """最小 args 替身：只带 upgrade_ring 新逻辑关心的 dry_run 标志。"""
    def __init__(self, dry_run=False):
        self.dry_run = dry_run


# ── is_loop_control_plane ───────────────────────────────────
def test_is_loop_control_plane_positive():
    item = {"seam": "control-plane", "kind": "workflow", "name": LOOP_REPO}
    assert ur.is_loop_control_plane(item) is True


def test_is_loop_control_plane_negative_wrong_seam():
    assert ur.is_loop_control_plane({"seam": "A", "kind": "workflow"}) is False
    assert ur.is_loop_control_plane({"seam": "gate", "kind": "workflow"}) is False


def test_is_loop_control_plane_negative_wrong_kind():
    assert ur.is_loop_control_plane({"seam": "control-plane", "kind": "binary"}) is False
    assert ur.is_loop_control_plane({"seam": "control-plane", "kind": "action"}) is False


def test_is_loop_control_plane_missing_fields():
    assert ur.is_loop_control_plane({}) is False
    assert ur.is_loop_control_plane({"seam": "control-plane"}) is False


# ── load_products_yml ───────────────────────────────────────
def test_load_products_yml_reads_enabled(tmp_path):
    content = (
        "schema: 1\n"
        "products:\n"
        "  - name: product-x\n"
        "    repo: Cloudbird-Software/product-x\n"
        "    default_branch: main\n"
        "    enabled: true\n"
        "  - name: product-y\n"
        "    repo: Cloudbird-Software/product-y\n"
        "    default_branch: main\n"
        "    enabled: false\n"
    )
    p = tmp_path / "products.yml"
    p.write_text(content, encoding="utf-8")
    products = ur.load_products_yml(str(p))
    # enabled=false 的 product-y 被过滤
    assert len(products) == 1
    assert products[0]["name"] == "product-x"
    assert products[0]["repo"] == "Cloudbird-Software/product-x"
    assert products[0]["default_branch"] == "main"


def test_load_products_yml_missing_returns_empty(tmp_path):
    assert ur.load_products_yml(str(tmp_path / "nope.yml")) == []


def test_load_products_yml_malformed_returns_empty(tmp_path):
    p = tmp_path / "products.yml"
    p.write_text(":::not yaml:::\n  - [", encoding="utf-8")
    # 不应抛异常，返回空列表
    assert ur.load_products_yml(str(p)) == []


def test_load_products_yml_default_enabled(tmp_path):
    # 缺省 enabled 字段视作 enabled
    content = (
        "products:\n"
        "  - name: product-x\n"
        "    repo: Cloudbird-Software/product-x\n"
        "    default_branch: main\n"
    )
    p = tmp_path / "products.yml"
    p.write_text(content, encoding="utf-8")
    products = ur.load_products_yml(str(p))
    assert len(products) == 1
    assert products[0]["name"] == "product-x"


# ── bump_loop_pin dry-run ───────────────────────────────────
def test_bump_loop_pin_dry_run_only_prints(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        class R:
            pass
        r = R(); r.returncode = 0; r.stdout = ""; r.stderr = ""
        return r

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=True)
    item = {"seam": "control-plane", "kind": "workflow", "name": LOOP_REPO}
    current_pin = {"version": "v0.1.5", "sha": PIN_SHA}

    result = ur.bump_loop_pin(args, item, "v0.1.6", NEW_SHA, current_pin,
                              PRODUCT_REPO, "main")

    assert result is None
    # dry-run：不应调用任何 gh
    assert all(c[0] != "gh" for c in calls), calls
    out = capsys.readouterr().out
    assert "[dry-run] bump_loop_pin" in out
    assert "v0.1.6" in out
    # 必须覆盖全部 5 个文件路径
    assert "LOOP.yml" in out
    assert "UPSTREAM.yaml" in out
    assert "loop-ci.yml" in out
    assert "loop-gates.yml" in out
    assert "loop-review.yml" in out
    assert "no PR created" in out


# ── bump_loop_pin 生产模式开 PR ─────────────────────────────
def _gh_ok(cmd):
    """模拟一套成功的 gh 调用：取 branch sha / 建 ref / GET 文件 / PUT 文件 / pr create。"""
    class R:
        pass
    r = R(); r.returncode = 0; r.stderr = ""
    if cmd[0] == "gh" and len(cmd) > 1 and cmd[1] == "api":
        arg = cmd[2] if len(cmd) > 2 else ""
        if "/branches/" in arg:
            r.stdout = json.dumps({"commit": {"sha": "base123"}})
        elif "/contents/" in arg:
            if "-X" in cmd and "PUT" in cmd:
                r.stdout = "{}"
            else:
                # GET 文件内容 → 返回占位 content + sha
                r.stdout = json.dumps({"content": _b64.b64encode(b"placeholder").decode(),
                                       "sha": "fileSHA"})
        else:
            r.stdout = "{}"
    elif cmd[0] == "gh" and len(cmd) > 1 and cmd[1] == "pr":
        r.stdout = f"https://github.com/{PRODUCT_REPO}/pull/1"
    else:
        r.stdout = ""
    return r


def test_bump_loop_pin_production_opens_pr(monkeypatch):
    calls = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        return _gh_ok(list(cmd))

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=False)
    item = {"seam": "control-plane", "kind": "workflow", "name": LOOP_REPO}
    current_pin = {"version": "v0.1.5", "sha": PIN_SHA}

    url = ur.bump_loop_pin(args, item, "v0.1.6", NEW_SHA, current_pin,
                           PRODUCT_REPO, "main")

    assert url == f"https://github.com/{PRODUCT_REPO}/pull/1"
    # 必须调用了 gh pr create
    pr_calls = [c for c in calls
                if c[0] == "gh" and len(c) > 1 and c[1] == "pr" and "create" in c]
    assert pr_calls, calls
    pr_create = pr_calls[0]
    # PR 标题正确：[loop-bump] <tag> @<sha[:12]>
    assert "[loop-bump] v0.1.6 @bbbbbbbbbbbb" in pr_create
    # 必须调用了 gh api 建 ref（分支 loop-bump/v0.1.6）
    ref_calls = [c for c in calls
                 if c[0] == "gh" and len(c) > 1 and c[1] == "api"
                 and "/git/refs" in (c[2] if len(c) > 2 else "")]
    assert ref_calls, calls
    assert any("refs/heads/loop-bump/v0.1.6" in arg for arg in ref_calls[0])
    # 必须对每个文件做了 PUT（5 个不同 path：LOOP.yml / UPSTREAM.yaml / 3 薄壳）
    put_calls = [c for c in calls
                 if c[0] == "gh" and c[1] == "api" and "-X" in c and "PUT" in c]
    assert len(put_calls) == 5, len(put_calls)


# ── bump_loop_pin 失败抛 RuntimeError ───────────────────────
def test_bump_loop_pin_failure_raises(monkeypatch):
    def fake_run(cmd, *a, **kw):
        class R:
            pass
        r = R(); r.returncode = 1; r.stdout = ""; r.stderr = "boom"
        return r

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=False)
    item = {"seam": "control-plane", "kind": "workflow", "name": LOOP_REPO}
    current_pin = {"version": "v0.1.5", "sha": PIN_SHA}

    with pytest.raises(RuntimeError):
        ur.bump_loop_pin(args, item, "v0.1.6", NEW_SHA, current_pin,
                         PRODUCT_REPO, "main")


# ── open_rollback_pr dry-run ────────────────────────────────
def test_open_rollback_pr_dry_run_only_prints(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        class R:
            pass
        r = R(); r.returncode = 0; r.stdout = ""; r.stderr = ""
        return r

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=True)

    result = ur.open_rollback_pr(args, PRODUCT_REPO, "main",
                                 PIN_SHA, "v0.1.5", "v0.1.6", NEW_SHA,
                                 "gate failure after merge")

    assert result is None
    assert all(c[0] != "gh" for c in calls), calls
    out = capsys.readouterr().out
    assert "[dry-run] open_rollback_pr" in out
    assert "revert v0.1.6 -> v0.1.5" in out
    assert "no PR created" in out


# ── open_rollback_pr 生产模式开 PR ──────────────────────────
def test_open_rollback_pr_production_opens_pr(monkeypatch):
    calls = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        class R:
            pass
        r = R(); r.returncode = 0; r.stderr = ""
        if cmd[0] == "gh" and len(cmd) > 1 and cmd[1] == "api":
            arg = cmd[2] if len(cmd) > 2 else ""
            if "/branches/" in arg:
                r.stdout = json.dumps({"commit": {"sha": "base123"}})
            elif "/contents/" in arg:
                if "-X" in cmd and "PUT" in cmd:
                    r.stdout = "{}"
                else:
                    r.stdout = json.dumps({"content": _b64.b64encode(b"x").decode(),
                                           "sha": "fsha"})
            else:
                r.stdout = "{}"
        elif cmd[0] == "gh" and len(cmd) > 1 and cmd[1] == "pr":
            r.stdout = f"https://github.com/{PRODUCT_REPO}/pull/2"
        else:
            r.stdout = ""
        return r

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=False)

    url = ur.open_rollback_pr(args, PRODUCT_REPO, "main",
                              PIN_SHA, "v0.1.5", "v0.1.6", NEW_SHA,
                              "gate failure after merge")

    assert url.endswith("/pull/2")
    pr_calls = [c for c in calls
                if c[0] == "gh" and len(c) > 1 and c[1] == "pr" and "create" in c]
    assert pr_calls
    assert "[loop-rollback] revert v0.1.6 -> v0.1.5" in pr_calls[0]
    # 回退分支名 loop-rollback/v0.1.6
    ref_calls = [c for c in calls
                 if c[0] == "gh" and c[1] == "api" and "/git/refs" in (c[2] if len(c) > 2 else "")]
    assert any("refs/heads/loop-rollback/v0.1.6" in arg for arg in ref_calls[0])


# ── open_rollback_pr 失败抛 RuntimeError ────────────────────
def test_open_rollback_pr_failure_raises(monkeypatch):
    def fake_run(cmd, *a, **kw):
        class R:
            pass
        r = R(); r.returncode = 1; r.stdout = ""; r.stderr = "boom"
        return r

    monkeypatch.setattr(ur.subprocess, "run", fake_run)
    args = _Args(dry_run=False)
    with pytest.raises(RuntimeError):
        ur.open_rollback_pr(args, PRODUCT_REPO, "main",
                            PIN_SHA, "v0.1.5", "v0.1.6", NEW_SHA,
                            "gate failure after merge")


# ── _apply_file_change 纯函数 ───────────────────────────────
def test_apply_file_change_loop_yml_updates_version_and_sha():
    content = (
        "schema: 1\n"
        "loop:\n"
        '  repo: Cloudbird-Software/loop\n'
        '  version: "v0.1.5"\n'
        f'  sha: "{PIN_SHA}"\n'
        "  max_lag_tags: 2\n"
        "reusable:\n  ci: x\n"
    )
    new = ur._apply_file_change(content, {"path": "LOOP.yml",
                                          "field": "loop.version", "new": "v0.1.6"})
    assert 'version: "v0.1.6"' in new
    assert f'sha: "{PIN_SHA}"' in new  # sha 未变
    new2 = ur._apply_file_change(new, {"path": "LOOP.yml",
                                       "field": "loop.sha", "new": NEW_SHA})
    assert 'version: "v0.1.6"' in new2
    assert f'sha: "{NEW_SHA}"' in new2


def test_apply_file_change_upstream_yaml_updates_pin():
    content = (
        "items:\n"
        "  - name: Cloudbird-Software/loop\n"
        "    seam: control-plane\n"
        f'    pin: "v0.1.5@{PIN_SHA}"\n'
        "  - name: other/repo\n"
        '    pin: "v9.9.9"\n'
    )
    new = ur._apply_file_change(content, {"path": "UPSTREAM.yaml",
                                          "new": f"v0.1.6@{NEW_SHA}"})
    assert f'pin: "v0.1.6@{NEW_SHA}"' in new
    # other/repo 的 pin 不受影响
    assert 'pin: "v9.9.9"' in new


def test_apply_file_change_workflow_replaces_sha():
    content = (
        "jobs:\n  ci:\n"
        f"    uses: {LOOP_REPO}/.github/workflows/reusable-product-ci.yml@{PIN_SHA}\n"
    )
    new = ur._apply_file_change(content, {"path": ".github/workflows/loop-ci.yml",
                                          "old_sha": PIN_SHA, "new_sha": NEW_SHA})
    assert f"@{NEW_SHA}" in new
    assert f"@{PIN_SHA}" not in new
