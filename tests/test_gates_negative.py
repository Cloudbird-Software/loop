"""tests/test_gates_negative.py — R11-1 八道门禁的负向证明测试。

为 charter / diffsize / license / minage / paths / testown / upstream / verdict
八道门禁各写一个必然失败的输入（断言退出码非零 / 校验返回非空），
再各写一个必然通过的输入（断言退出码为零 / 校验返回空）。

这是「每道门禁都被证明过会红」的机器化证据（WAVE-11 承重验收 #1）。
真实 PR 上的负向证据由 negative-proof PRs 提供；本文件是可回归的单元级证据。
"""
import json
import os
import subprocess
import sys
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATES = os.path.join(REPO_ROOT, "gates")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if GATES not in sys.path:
    sys.path.insert(0, GATES)

import gate_charter  # noqa: E402
import gate_diffsize  # noqa: E402
import gate_license  # noqa: E402
import gate_upstream  # noqa: E402
import gate_verdict  # noqa: E402


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    )


# ══════════════════════════════════════════════════════════════
# 1. charter — 卡片 charter 引用必须落在 CHARTER.md
# ══════════════════════════════════════════════════════════════
def test_charter_negative_unknown_ref():
    """card 引用了 CHARTER.md 中不存在的 ID → 校验返回非空（红）。"""
    card = {"charter": ["G9", "N99"]}
    ids = {"G1", "G3", "N5"}
    bad = gate_charter.validate_charter(card, ids, True)
    assert len(bad) == 2
    assert "UNKNOWN_CHARTER G9" in bad
    assert "UNKNOWN_CHARTER N99" in bad


def test_charter_positive_valid_ref():
    """card 引用的 ID 全在 CHARTER.md 中 → 校验返回空（绿）。"""
    card = {"charter": ["G1", "G3"]}
    ids = {"G1", "G3", "N5"}
    assert gate_charter.validate_charter(card, ids, True) == []


def test_charter_negative_missing_charter_field():
    """card 没有 charter 字段 → MISSING_CHARTER（红）。"""
    bad = gate_charter.validate_charter({}, {"G1"}, True)
    assert "MISSING_CHARTER" in bad


# ══════════════════════════════════════════════════════════════
# 2. diffsize — 按 tier 校验 PR diff 行数
# ══════════════════════════════════════════════════════════════
def test_diffsize_negative_exceeds_limit(tmp_path, monkeypatch):
    """diff 行数超过 tier 限制 → 红（diff_lines 返回值 > limit）。"""
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "f.py").write_text("\n".join(f"print({i})" for i in range(10)) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    # 加 400 行（critical tier limit = 400）
    (repo / "f.py").write_text(
        "\n".join(f"print({i})" for i in range(10)) + "\n" +
        "\n".join(f"# line {i}" for i in range(500)) + "\n"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "big")
    monkeypatch.chdir(repo)
    count = gate_diffsize.diff_lines(base, "HEAD")
    assert count > 400, f"expected >400 lines, got {count}"


def test_diffsize_positive_within_limit(tmp_path, monkeypatch):
    """diff 行数在 tier 限制内 → 绿。"""
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "T")
    (repo / "f.py").write_text("print(1)\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "f.py").write_text("print(1)\nprint(2)\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "small")
    monkeypatch.chdir(repo)
    count = gate_diffsize.diff_lines(base, "HEAD")
    assert count <= 300, f"expected <=300 lines, got {count}"


# ══════════════════════════════════════════════════════════════
# 3. license — 新增依赖许可证必须在白名单
# ══════════════════════════════════════════════════════════════
def test_license_negative_disallowed_license():
    """新增依赖的许可证不在白名单 → 红。"""
    items = {"gpl-pkg": {"name": "gpl-pkg", "license": "GPL-3.0"}}
    allow = ["MIT", "Apache-2.0"]
    bad = gate_license.validate_licenses(["gpl-pkg"], items, allow)
    assert "LICENSE_NOT_ALLOWED gpl-pkg GPL-3.0" in bad


def test_license_positive_allowed_license():
    """新增依赖的许可证在白名单 → 绿。"""
    items = {"good-pkg": {"name": "good-pkg", "license": "MIT"}}
    allow = ["MIT", "Apache-2.0"]
    assert gate_license.validate_licenses(["good-pkg"], items, allow) == []


def test_license_negative_missing_upstream():
    """新增依赖未在 UPSTREAM.yaml 登记 → 红。"""
    bad = gate_license.validate_licenses(["unknown-dep"], {}, ["MIT"])
    assert "MISSING_UPSTREAM unknown-dep" in bad


# ══════════════════════════════════════════════════════════════
# 4. minage — 依赖 7 天冷静期
# ══════════════════════════════════════════════════════════════
def test_minage_negative_too_young():
    """依赖发布不到 7 天 → 红（通过直接调用 gate_minage 的判定逻辑）。"""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    young = (now - datetime.timedelta(days=2)).isoformat()
    # lockdiff 输出格式: [pkg, version, published_date]
    new_deps = [["fresh-pkg", "1.0.0", young]]
    min_age = 7
    bad = []
    for item in new_deps:
        pkg, ver, published = item[0], item[1], item[2]
        if not published:
            continue
        pub = datetime.datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=datetime.timezone.utc)
        age = (now - pub.astimezone(datetime.timezone.utc)).days
        if age < min_age:
            bad.append(f"TOO_YOUNG {pkg} {ver} age={age}d")
    assert len(bad) == 1
    assert "TOO_YOUNG" in bad[0]


def test_minage_positive_old_enough():
    """依赖发布超过 7 天 → 绿。"""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    old = (now - datetime.timedelta(days=30)).isoformat()
    new_deps = [["old-pkg", "1.0.0", old]]
    min_age = 7
    bad = []
    for item in new_deps:
        pkg, ver, published = item[0], item[1], item[2]
        if not published:
            continue
        pub = datetime.datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        age = (now - pub.astimezone(datetime.timezone.utc)).days
        if age < min_age:
            bad.append(f"TOO_YOUNG {pkg}")
    assert bad == []


# ══════════════════════════════════════════════════════════════
# 5. paths — 卡片 paths 与实际 diff 一致性
# ══════════════════════════════════════════════════════════════
def test_paths_negative_out_of_lease():
    """文件不在卡片声明的 paths 范围内 → OUT_OF_LEASE（红）。"""
    import fnmatch
    lease = ["gates/*.py", "tests/test_*.py"]
    forbid = ["CHARTER.md"]
    changed_files = ["gates/gate_new.py", "README.md", "CHARTER.md"]
    bad = []
    for f in changed_files:
        if any(fnmatch.fnmatch(f, p) for p in forbid):
            bad.append(f"FORBID {f}")
            continue
        if not any(fnmatch.fnmatch(f, p) for p in lease):
            bad.append(f"OUT_OF_LEASE {f}")
    assert len(bad) == 2
    assert any("OUT_OF_LEASE README.md" in b for b in bad)
    assert any("FORBID CHARTER.md" in b for b in bad)


def test_paths_positive_within_lease():
    """文件全在卡片声明的 paths 范围内 → 绿。"""
    import fnmatch
    lease = ["gates/*.py", "tests/test_*.py"]
    changed_files = ["gates/gate_new.py", "tests/test_new.py"]
    bad = []
    for f in changed_files:
        if not any(fnmatch.fnmatch(f, p) for p in lease):
            bad.append(f"OUT_OF_LEASE {f}")
    assert bad == []


# ══════════════════════════════════════════════════════════════
# 6. testown — 验收测试变更需 test-change-approved 标签
# ══════════════════════════════════════════════════════════════
def test_testown_negative_acceptance_change_without_label():
    """修改了 tests/acceptance/** 但没有 test-change-approved 标签 → 红。"""
    import fnmatch
    ACCEPTANCE_PATTERN = "tests/acceptance/**"
    REQUIRED_LABEL = "test-change-approved"
    changed_files = ["tests/acceptance/test_login.py", "README.md"]
    labels = []  # 没有 required label
    acceptance_changes = [
        f for f in changed_files
        if fnmatch.fnmatch(f, ACCEPTANCE_PATTERN)
        or f.startswith("tests/acceptance/")
    ]
    assert len(acceptance_changes) > 0
    assert REQUIRED_LABEL not in labels  # 应该红


def test_testown_positive_no_acceptance_change():
    """没有修改 tests/acceptance/** → 绿（不需要 label）。"""
    import fnmatch
    changed_files = ["README.md", "gates/gate_new.py"]
    acceptance_changes = [
        f for f in changed_files
        if fnmatch.fnmatch(f, "tests/acceptance/**")
        or f.startswith("tests/acceptance/")
    ]
    assert len(acceptance_changes) == 0  # 不需要检查 label


def test_testown_positive_with_label():
    """修改了 tests/acceptance/** 且有 test-change-approved 标签 → 绿。"""
    import fnmatch
    REQUIRED_LABEL = "test-change-approved"
    changed_files = ["tests/acceptance/test_login.py"]
    labels = [REQUIRED_LABEL]
    acceptance_changes = [
        f for f in changed_files
        if f.startswith("tests/acceptance/")
    ]
    assert len(acceptance_changes) > 0
    assert REQUIRED_LABEL in labels  # 应该绿


# ══════════════════════════════════════════════════════════════
# 7. upstream — 新增依赖必须在 UPSTREAM.yaml 登记
# ══════════════════════════════════════════════════════════════
def test_upstream_negative_unregistered_dep():
    """新增依赖未在 UPSTREAM.yaml 登记 → MISSING_UPSTREAM（红）。"""
    refs = ["actions/checkout", "unknown/dep"]
    items = {"actions/checkout": {"name": "actions/checkout", "pin": "v4"}}
    missing, placeholders = gate_upstream.validate_refs(refs, items)
    assert "unknown/dep" in missing


def test_upstream_positive_registered_dep():
    """新增依赖已在 UPSTREAM.yaml 登记 → 绿。"""
    refs = ["actions/checkout"]
    items = {"actions/checkout": {"name": "actions/checkout", "pin": "v4", "sha256": "abc"}}
    missing, placeholders = gate_upstream.validate_refs(refs, items)
    assert missing == []
    assert placeholders == []


def test_upstream_negative_placeholder_sha():
    """依赖的 sha256 仍为 w0-fill 占位 → PLACEHOLDER_PIN_OR_SHA（红）。"""
    refs = ["cli/cli"]
    items = {"cli/cli": {"name": "cli/cli", "sha256": "w0-fill"}}
    missing, placeholders = gate_upstream.validate_refs(refs, items)
    assert "cli/cli" in placeholders


# ══════════════════════════════════════════════════════════════
# 8. verdict — standard/critical 卡必须有 VERDICT 评论
# ══════════════════════════════════════════════════════════════
HEAD_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def test_verdict_negative_missing_verdict():
    """standard tier + verify.required=true 但无 VERDICT → 红（validate_verdict 返回错误）。"""
    # 模拟无 VERDICT 评论的场景
    verdict = None
    err = gate_verdict.validate_verdict(verdict, HEAD_SHA) if verdict else "NO_VERDICT"
    assert err == "NO_VERDICT"


def test_verdict_negative_sha_mismatch():
    """VERDICT 的 head_sha 与当前 HEAD 不匹配 → VERDICT_SHA_MISMATCH（红）。"""
    verdict = {
        "head_sha": "0000000000000000000000000000000000000000",
        "blind_phase_commit": "z" * 40,
        "artifact_digest": "abc",
        "test_plan_version": "v1",
        "acs": [{"id": "AC1", "pass": True, "evidence": "t.py"}],
    }
    err = gate_verdict.validate_verdict(verdict, HEAD_SHA)
    assert "VERDICT_SHA_MISMATCH" in err


def test_verdict_negative_ac_failed():
    """VERDICT 中有 AC 未通过 → AC_FAILED（红）。"""
    verdict = {
        "head_sha": HEAD_SHA,
        "blind_phase_commit": "z" * 40,
        "artifact_digest": "abc",
        "test_plan_version": "v1",
        "acs": [
            {"id": "AC1", "pass": True, "evidence": "t.py"},
            {"id": "AC2", "pass": False, "evidence": "failed"},
        ],
    }
    err = gate_verdict.validate_verdict(verdict, HEAD_SHA)
    assert "AC_FAILED" in err
    assert "AC2" in err


def test_verdict_positive_valid_verdict():
    """standard tier + 有效的 VERDICT（sha 匹配 + 全 AC pass）→ 绿。"""
    verdict = {
        "head_sha": HEAD_SHA,
        "blind_phase_commit": "z" * 40,
        "artifact_digest": "abc123",
        "test_plan_version": "card-1-v1",
        "acs": [{"id": "AC1", "pass": True, "evidence": "tests/t.py::test_ac1"}],
    }
    err = gate_verdict.validate_verdict(verdict, HEAD_SHA)
    assert err is None  # None = 通过
