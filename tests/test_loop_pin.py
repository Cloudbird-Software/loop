"""tests/test_loop_pin.py — conductor/loop_pin.py 单元测试（R13-6）。

覆盖 parse_loop_yml / parse_upstream_loop / validate_pin / compute_lag /
suggest_bump 的核心分支。所有 gh api 调用通过 monkeypatch 替换，不依赖真实网络。
"""
import os
import sys

import pytest

# 把仓库根加入 sys.path，使 `from conductor import loop_pin` 与
# `python3 -m conductor.loop_pin` 走同一命名空间包路径。
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from conductor import loop_pin as lp  # noqa: E402

LOOP_REPO = "Cloudbird-Software/loop"
PIN_SHA = "a" * 40
OTHER_SHA = "b" * 40


# ── 辅助构造 ────────────────────────────────────────────────
def write_loop_yml(path, sha=PIN_SHA, version="v0.1.5",
                   max_lag_tags=2, max_lag_days=30, repo=LOOP_REPO):
    content = (
        "schema: 1\n"
        "loop:\n"
        f"  repo: {repo}\n"
        f'  version: "{version}"\n'
        f'  sha: "{sha}"\n'
        f"  max_lag_tags: {max_lag_tags}\n"
        f"  max_lag_days: {max_lag_days}\n"
    )
    with open(os.path.join(path, "LOOP.yml"), "w", encoding="utf-8") as f:
        f.write(content)


def write_upstream(path, pin=f"v0.1.5@{PIN_SHA}", name=LOOP_REPO):
    content = (
        "policy:\n  min_age_days: 7\n"
        "items:\n"
        f"  - name: {name}\n"
        "    seam: control-plane\n"
        "    kind: workflow\n"
        f'    pin: "{pin}"\n'
        "    degrade_path: x\n"
    )
    with open(os.path.join(path, "UPSTREAM.yaml"), "w", encoding="utf-8") as f:
        f.write(content)


# ── parse_loop_yml ──────────────────────────────────────────
def test_parse_loop_yml_valid(tmp_path):
    write_loop_yml(str(tmp_path), sha=PIN_SHA, version="v0.1.5")
    pin = lp.parse_loop_yml(os.path.join(str(tmp_path), "LOOP.yml"))
    assert pin["version"] == "v0.1.5"
    assert pin["sha"] == PIN_SHA
    assert pin["max_lag_tags"] == 2
    assert pin["max_lag_days"] == 30
    assert pin["repo"] == LOOP_REPO


def test_parse_loop_yml_missing(tmp_path):
    missing = os.path.join(str(tmp_path), "does-not-exist.yml")
    pin = lp.parse_loop_yml(missing)
    # 文件不存在 → 返回默认值（不抛异常）
    assert pin["version"] == ""
    assert pin["sha"] == ""
    assert pin["max_lag_tags"] == 2
    assert pin["max_lag_days"] == 30
    assert pin["repo"] == LOOP_REPO


# ── parse_upstream_loop ─────────────────────────────────────
def test_parse_upstream_loop_found(tmp_path):
    write_upstream(str(tmp_path))
    item = lp.parse_upstream_loop(os.path.join(str(tmp_path), "UPSTREAM.yaml"))
    assert item is not None
    assert item["name"] == LOOP_REPO
    assert "@" in item["pin"]


def test_parse_upstream_loop_not_found(tmp_path):
    content = (
        "items:\n"
        "  - name: other/repo\n"
        "    seam: A\n"
        "    kind: binary\n"
        "    pin: v1.0.0\n"
    )
    with open(os.path.join(str(tmp_path), "UPSTREAM.yaml"), "w", encoding="utf-8") as f:
        f.write(content)
    item = lp.parse_upstream_loop(os.path.join(str(tmp_path), "UPSTREAM.yaml"))
    assert item is None


# ── validate_pin ────────────────────────────────────────────
def test_validate_pin_consistent():
    loop_pin = {"sha": PIN_SHA, "version": "v0.1.5"}
    upstream_item = {"pin": f"v0.1.5@{PIN_SHA}"}
    valid, errors = lp.validate_pin(loop_pin, upstream_item)
    assert valid, errors
    assert errors == []


def test_validate_pin_mismatch():
    loop_pin = {"sha": PIN_SHA, "version": "v0.1.5"}
    upstream_item = {"pin": f"v0.1.5@{OTHER_SHA}"}
    valid, errors = lp.validate_pin(loop_pin, upstream_item)
    assert not valid
    assert any("SHA 不一致" in e for e in errors)


def test_validate_pin_invalid_sha():
    loop_pin = {"sha": "not-a-sha", "version": "v0.1.5"}
    upstream_item = {"pin": f"v0.1.5@{PIN_SHA}"}
    valid, errors = lp.validate_pin(loop_pin, upstream_item)
    assert not valid
    assert any("40 位" in e for e in errors)


def test_validate_pin_no_upstream():
    loop_pin = {"sha": PIN_SHA, "version": "v0.1.5"}
    valid, errors = lp.validate_pin(loop_pin, None)
    assert not valid
    assert any("未找到" in e for e in errors)


# ── compute_lag ─────────────────────────────────────────────
def test_compute_lag_pin_at_latest(monkeypatch):
    tags = [
        {"name": "v0.1.5", "commit": {"sha": PIN_SHA}},
        {"name": "v0.1.4", "commit": {"sha": OTHER_SHA}},
    ]
    # pin 即最新 tag → 两个 commit 同日 → lag_tags=0, lag_days=0
    def mock_fetch(sha, repo=None):
        return {"sha": sha, "commit": {"author": {"date": "2026-07-30T00:00:00Z"}}}
    monkeypatch.setattr(lp, "fetch_commit_info", mock_fetch)
    lag_tags, lag_days, latest_tag, latest_date = lp.compute_lag(PIN_SHA, tags)
    assert lag_tags == 0
    assert lag_days == 0
    assert latest_tag == "v0.1.5"


def test_compute_lag_pin_stale(monkeypatch):
    tags = [
        {"name": "v0.1.8", "commit": {"sha": "c" * 40}},
        {"name": "v0.1.7", "commit": {"sha": "d" * 40}},
        {"name": "v0.1.6", "commit": {"sha": "e" * 40}},
        {"name": "v0.1.5", "commit": {"sha": PIN_SHA}},
    ]
    dates = {
        "c" * 40: "2026-07-30T00:00:00Z",   # 最新 tag
        PIN_SHA: "2026-06-01T00:00:00Z",    # pin（59 天前）
    }

    def mock_fetch(sha, repo=None):
        return {"sha": sha, "commit": {"author": {"date": dates.get(sha, "2026-07-01T00:00:00Z")}}}
    monkeypatch.setattr(lp, "fetch_commit_info", mock_fetch)
    lag_tags, lag_days, latest_tag, latest_date = lp.compute_lag(PIN_SHA, tags)
    assert lag_tags == 3
    assert lag_days > 0
    assert latest_tag == "v0.1.8"


# ── suggest_bump ────────────────────────────────────────────
def test_suggest_bump():
    current_pin = {"version": "v0.1.5", "sha": PIN_SHA}
    latest_tag_info = {"name": "v0.1.6", "commit": {"sha": OTHER_SHA}}
    result = lp.suggest_bump(current_pin, latest_tag_info)
    assert result["new_version"] == "v0.1.6"
    assert result["new_sha"] == OTHER_SHA
    paths = [f["path"] for f in result["files"]]
    # 必须覆盖 LOOP.yml、UPSTREAM.yaml 与三个薄壳 workflow
    assert "LOOP.yml" in paths
    assert "UPSTREAM.yaml" in paths
    assert ".github/workflows/loop-ci.yml" in paths
    assert ".github/workflows/loop-gates.yml" in paths
    assert ".github/workflows/loop-review.yml" in paths
    # UPSTREAM.yaml 条目 old=new_tag@old_sha / new=new_tag@new_sha
    up_entry = [f for f in result["files"] if f["path"] == "UPSTREAM.yaml"][0]
    assert up_entry["old"] == f"v0.1.5@{PIN_SHA}"
    assert up_entry["new"] == f"v0.1.6@{OTHER_SHA}"
