"""tests/test_lockdiff.py — R11-5 lockdiff gate 的四种路径覆盖。

覆盖 acceptance：
  - 新增未登记依赖（红）
  - 升级到未登记版本（红）
  - 删除依赖（绿）
  - 无锁文件变更（绿）
"""
import json
import os
import subprocess
import sys
import textwrap

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATES = os.path.join(REPO_ROOT, "gates")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _init_repo(tmp_path):
    """初始化一个临时 git 仓，返回 (repo_path, base_sha)。"""
    r = subprocess.run(
        ["git", "init"], cwd=str(tmp_path), capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    # 初始提交
    (tmp_path / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), capture_output=True, text=True
    ).stdout.strip()
    return base


def _write_upstream(tmp_path, items):
    (tmp_path / "UPSTREAM.yaml").write_text(
        "items:\n" + "\n".join(
            f"  - name: {i['name']}\n    pin: '{i.get('pin', '')}'\n    sha256: '{i.get('sha256', '')}'\n"
            for i in items
        )
    )


def _run_lockdiff(tmp_path):
    """在 tmp_path 仓里跑 lockdiff.py，返回 (exit_code, stdout_json, stderr)。"""
    p = subprocess.run(
        [sys.executable, os.path.join(GATES, "lockdiff.py")],
        cwd=str(tmp_path), capture_output=True, text=True,
        env={**os.environ, "LOOP_CI_BASE": "HEAD~1"},
    )
    out = None
    try:
        out = json.loads(p.stdout) if p.stdout.strip() else []
    except json.JSONDecodeError:
        pass
    return p.returncode, out, p.stderr


def test_no_lockfile_changes_green(tmp_path):
    """无锁文件变更 → exit 0, stdout=[]。"""
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("changed\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=str(tmp_path), check=True)
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 0, f"expected 0, got {code}: {err}"
    assert out == []


def test_new_unregistered_dep_red(tmp_path):
    """新增未登记依赖 → exit 1。"""
    _init_repo(tmp_path)
    # 写一个不含新依赖的初始 requirements.txt
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "base req"], cwd=str(tmp_path), check=True)
    # 新增一个未登记的依赖
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\nunknownpkg==9.9.9\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "add unknown"], cwd=str(tmp_path), check=True)
    _write_upstream(tmp_path, [
        {"name": "pyyaml", "pin": "6.0.1", "sha256": "abc123"}
    ])
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 1, f"expected 1, got {code}: {err}"
    assert "UNREGISTERED_DEP unknownpkg" in err


def test_version_mismatch_red(tmp_path):
    """升级到与 UPSTREAM.yaml 不符的版本 → exit 1。"""
    _init_repo(tmp_path)
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "base req"], cwd=str(tmp_path), check=True)
    # 升级到不同版本
    (tmp_path / "requirements.txt").write_text("PyYAML==99.0.0\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "upgrade"], cwd=str(tmp_path), check=True)
    _write_upstream(tmp_path, [
        {"name": "pyyaml", "pin": "6.0.1", "sha256": "abc123"}
    ])
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 1, f"expected 1, got {code}: {err}"
    assert "VERSION_MISMATCH" in err and "pyyaml" in err


def test_delete_dep_green(tmp_path):
    """仅删除依赖 → exit 0。"""
    _init_repo(tmp_path)
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\npytest==8.0.0\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "base req"], cwd=str(tmp_path), check=True)
    # 删除一个依赖
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "remove pytest"], cwd=str(tmp_path), check=True)
    _write_upstream(tmp_path, [
        {"name": "pyyaml", "pin": "6.0.1", "sha256": "abc123"},
        {"name": "pytest", "pin": "8.0.0", "sha256": "def456"},
    ])
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 0, f"expected 0, got {code}: {err}"


def test_registered_dep_green(tmp_path):
    """新增已登记且版本匹配的依赖 → exit 0。"""
    _init_repo(tmp_path)
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "base req"], cwd=str(tmp_path), check=True)
    # 新增已登记的依赖
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\npytest==8.0.0\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "add pytest"], cwd=str(tmp_path), check=True)
    _write_upstream(tmp_path, [
        {"name": "pyyaml", "pin": "6.0.1", "sha256": "abc123"},
        {"name": "pytest", "pin": "8.0.0", "sha256": "def456"},
    ])
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 0, f"expected 0, got {code}: {err}"


def test_json_output_for_minage(tmp_path):
    """stdout 输出 JSON 数组供 gate_minage.py 消费。"""
    _init_repo(tmp_path)
    (tmp_path / "requirements.txt").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "empty req"], cwd=str(tmp_path), check=True)
    (tmp_path / "requirements.txt").write_text("PyYAML==6.0.1\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "add yaml"], cwd=str(tmp_path), check=True)
    _write_upstream(tmp_path, [
        {"name": "pyyaml", "pin": "6.0.1", "sha256": "abc123"}
    ])
    code, out, err = _run_lockdiff(tmp_path)
    assert code == 0
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0][0] == "pyyaml"
    assert out[0][1] == "6.0.1"
    assert out[0][2] is None  # published_date unavailable from lockfile
