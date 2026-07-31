"""tests/test_gate_conformance.py — 产品仓合规门禁（R13-2）测试。

对六项检查各覆盖至少一个失败用例与一个通过用例。所有 gh api 调用通过
monkeypatch 替换 subprocess.run 模拟，不依赖真实网络。
"""
import json
import os
import sys

import pytest

GATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gates")
if GATES_DIR not in sys.path:
    sys.path.insert(0, GATES_DIR)

import gate_conformance as gc  # noqa: E402

LOOP_REPO = "Cloudbird-Software/loop"
PIN_SHA = "a" * 40
OTHER_SHA = "b" * 40


# ── 辅助构造 ────────────────────────────────────────────────
def make_gh_run(commit_ok=True, tags=None, commit_date="2026-07-31T00:00:00Z"):
    """构造一个模拟 `gh api` 的 subprocess.run 替身。"""
    def _run(cmd, *args, **kwargs):
        class R:
            pass
        r = R()
        r.returncode = 0
        r.stderr = ""
        if cmd[0] == "gh" and len(cmd) > 2 and cmd[1] == "api":
            ep = cmd[2]
            if "/tags" in ep:
                r.stdout = json.dumps(tags if tags is not None else [])
            elif "/commits/" in ep:
                if commit_ok:
                    sha = ep.rsplit("/", 1)[-1]
                    r.stdout = json.dumps({
                        "sha": sha,
                        "commit": {"committer": {"date": commit_date}},
                    })
                else:
                    r.returncode = 1
                    r.stdout = ""
                    r.stderr = "404 Not Found"
            else:
                r.stdout = "{}"
        else:
            r.stdout = ""
        return r
    return _run


def write_loop_yml(path, sha=PIN_SHA, version="v0.1.5",
                   max_lag_tags=2, max_lag_days=30):
    content = (
        "schema: 1\n"
        "product:\n  name: product-x\n"
        "loop:\n"
        f"  repo: {LOOP_REPO}\n"
        f'  version: "{version}"\n'
        f'  sha: "{sha}"\n'
        f"  max_lag_tags: {max_lag_tags}\n"
        f"  max_lag_days: {max_lag_days}\n"
    )
    with open(os.path.join(path, "LOOP.yml"), "w", encoding="utf-8") as f:
        f.write(content)


def write_charter(path, last_edit="2026-07-30"):
    content = (
        "# CHARTER.md\n\n"
        "## P 产品\n\n样例。\n\n"
        "## 索引（machine-readable，勿删）\n\n"
        "G1 端到端可用\n"
        "N9 不在产品仓复制 loop 的机制文件\n"
        "\n<!-- last-human-edit: " + last_edit + " — 人类审定 -->\n"
    )
    with open(os.path.join(path, "CHARTER.md"), "w", encoding="utf-8") as f:
        f.write(content)


def write_upstream(path):
    with open(os.path.join(path, "UPSTREAM.yaml"), "w", encoding="utf-8") as f:
        f.write("schema: 1\nitems: []\n")


def write_shell(path, name="loop-ci.yml", sha=PIN_SHA, with_run=False):
    wf = os.path.join(path, ".github", "workflows")
    os.makedirs(wf, exist_ok=True)
    content = (
        f"name: {name}\n"
        "on: [push]\n"
        "jobs:\n"
        "  ci:\n"
        f"    uses: {LOOP_REPO}/.github/workflows/reusable-product-ci.yml@{sha}\n"
        "    secrets: inherit\n"
    )
    if with_run:
        content += (
            "  extra:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: echo local logic\n"
        )
    with open(os.path.join(wf, name), "w", encoding="utf-8") as f:
        f.write(content)


# ── 检查 1：pin 存在且合法 ──────────────────────────────────
def test_check1_pin_valid(tmp_path, monkeypatch):
    write_loop_yml(str(tmp_path), sha=PIN_SHA)
    monkeypatch.setattr(gc.subprocess, "run", make_gh_run(commit_ok=True))
    ok, detail = gc.check1_pin_valid(str(tmp_path), LOOP_REPO)
    assert ok, detail


def test_check1_pin_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gc.subprocess, "run", make_gh_run())
    ok, detail = gc.check1_pin_valid(str(tmp_path), LOOP_REPO)
    assert not ok
    assert "LOOP.yml" in detail


def test_check1_pin_invalid(tmp_path, monkeypatch):
    write_loop_yml(str(tmp_path), sha="not-a-sha")
    monkeypatch.setattr(gc.subprocess, "run", make_gh_run())
    ok, detail = gc.check1_pin_valid(str(tmp_path), LOOP_REPO)
    assert not ok
    assert "40 位" in detail


# ── 检查 2：pin 新鲜 ────────────────────────────────────────
def test_check2_pin_fresh(tmp_path, monkeypatch):
    write_loop_yml(str(tmp_path), sha=PIN_SHA, max_lag_tags=2, max_lag_days=30)
    tags = [
        {"name": "v0.1.5", "commit": {"sha": PIN_SHA}},
        {"name": "v0.1.4", "commit": {"sha": OTHER_SHA}},
    ]
    monkeypatch.setattr(gc.subprocess, "run",
                        make_gh_run(tags=tags, commit_date="2026-07-30T00:00:00Z"))
    ok, detail = gc.check2_pin_fresh(str(tmp_path), LOOP_REPO)
    assert ok, detail


def test_check2_pin_stale(tmp_path, monkeypatch):
    write_loop_yml(str(tmp_path), sha=PIN_SHA, max_lag_tags=2, max_lag_days=30)
    # pin 落后 3 个 tag（上限 2）
    tags = [
        {"name": "v0.1.8", "commit": {"sha": "c" * 40}},
        {"name": "v0.1.7", "commit": {"sha": "d" * 40}},
        {"name": "v0.1.6", "commit": {"sha": "e" * 40}},
        {"name": "v0.1.5", "commit": {"sha": PIN_SHA}},
    ]
    # commit date > 30 天前（今天 2026-07-31）
    monkeypatch.setattr(gc.subprocess, "run",
                        make_gh_run(tags=tags, commit_date="2026-06-01T00:00:00Z"))
    ok, detail = gc.check2_pin_fresh(str(tmp_path), LOOP_REPO)
    assert not ok
    assert "tag" in detail


# ── 检查 3：必需文件齐备 ────────────────────────────────────
def test_check3_files_complete(tmp_path):
    write_charter(str(tmp_path), last_edit="2026-07-30")
    write_loop_yml(str(tmp_path))
    write_upstream(str(tmp_path))
    write_shell(str(tmp_path), "loop-ci.yml")
    ok, detail = gc.check3_files_complete(str(tmp_path))
    assert ok, detail


def test_check3_charter_pending(tmp_path):
    write_charter(str(tmp_path), last_edit="PENDING")
    write_loop_yml(str(tmp_path))
    write_upstream(str(tmp_path))
    write_shell(str(tmp_path), "loop-ci.yml")
    ok, detail = gc.check3_files_complete(str(tmp_path))
    assert not ok
    assert "PENDING" in detail


def test_check3_files_missing(tmp_path):
    write_charter(str(tmp_path))
    write_loop_yml(str(tmp_path))
    # 缺少 UPSTREAM.yaml
    write_shell(str(tmp_path), "loop-ci.yml")
    ok, detail = gc.check3_files_complete(str(tmp_path))
    assert not ok
    assert "UPSTREAM.yaml" in detail


# ── 检查 4：薄壳未被魔改 ────────────────────────────────────
def test_check4_shell_clean(tmp_path):
    write_shell(str(tmp_path), "loop-ci.yml", sha=PIN_SHA, with_run=False)
    ok, detail = gc.check4_shell_unmodified(str(tmp_path))
    assert ok, detail


def test_check4_shell_modified(tmp_path):
    write_shell(str(tmp_path), "loop-ci.yml", sha=PIN_SHA, with_run=True)
    ok, detail = gc.check4_shell_unmodified(str(tmp_path))
    assert not ok
    assert "run:" in detail


# ── 检查 5：机制副本为零 ────────────────────────────────────
def test_check5_no_copies(tmp_path):
    ok, detail = gc.check5_no_copies(str(tmp_path))
    assert ok, detail


def test_check5_has_copies(tmp_path):
    gates_dir = os.path.join(str(tmp_path), "gates")
    os.makedirs(gates_dir, exist_ok=True)
    with open(os.path.join(gates_dir, "gate_paths.py"), "w", encoding="utf-8") as f:
        f.write("# loop 机制副本\n")
    ok, detail = gc.check5_no_copies(str(tmp_path))
    assert not ok
    assert "gate_paths.py" in detail


# ── 检查 6：薄壳引用 SHA 与 LOOP.yml 一致 ──────────────────
def test_check6_sha_consistent(tmp_path):
    write_loop_yml(str(tmp_path), sha=PIN_SHA)
    write_shell(str(tmp_path), "loop-ci.yml", sha=PIN_SHA)
    ok, detail = gc.check6_sha_consistency(str(tmp_path), LOOP_REPO)
    assert ok, detail


def test_check6_sha_mismatch(tmp_path):
    write_loop_yml(str(tmp_path), sha=PIN_SHA)
    write_shell(str(tmp_path), "loop-ci.yml", sha=OTHER_SHA)
    ok, detail = gc.check6_sha_consistency(str(tmp_path), LOOP_REPO)
    assert not ok
    assert "!=" in detail
