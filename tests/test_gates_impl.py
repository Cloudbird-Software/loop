import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GATES_DIR = os.path.join(REPO_ROOT, "gates")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if GATES_DIR not in sys.path:
    sys.path.insert(0, GATES_DIR)

import conductor.tick as tick  # noqa: E402
import gate_charter  # noqa: E402
import gate_diffsize  # noqa: E402
import gate_license  # noqa: E402
import gate_upstream  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_parse_flow_handles_real_policy_values():
    assert tick._parse_flow("{shards_per_day: 2}") == {"shards_per_day": 2}
    assert tick._parse_flow("{window_days: 14, adopt_rate_floor: 0.35}") == {"window_days": 14, "adopt_rate_floor": 0.35}
    assert tick._parse_flow("[trivial, standard]") == ["trivial", "standard"]


def test_gate_charter_validates_refs_and_g0_fallback():
    assert gate_charter.validate_charter({"charter": ["G1", "N2"]}, {"G1", "N2"}, True) == []
    assert gate_charter.validate_charter({"charter": ["G9"]}, {"G1"}, True) == ["UNKNOWN_CHARTER G9"]
    assert gate_charter.validate_charter({"charter": ["G0"]}, set(), False) == []
    assert gate_charter.validate_charter({"charter": ["G1"]}, set(), False) == ["UNKNOWN_CHARTER G1 (CHARTER.md missing)"]
    assert gate_charter.validate_charter({}, {"G1"}, True) == ["MISSING_CHARTER"]


def test_gate_diffsize_counts_non_generated_lines(tmp_path, monkeypatch):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Tester")
    (repo / "app.py").write_text("print(1)\n")
    (repo / "requirements.txt").write_text("pkg==1\n")
    (repo / "poetry.lock").write_text("old\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "app.py").write_text("print(1)\nprint(2)\n")
    (repo / "requirements.txt").write_text("pkg==1 \\\n    --hash=sha256:abc\nnewpkg==2\n")
    (repo / "poetry.lock").write_text("old\nnew generated\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "head")
    monkeypatch.chdir(repo)
    assert gate_diffsize.diff_lines(base, "HEAD") == 4


def test_gate_license_requires_upstream_license_allowlist():
    items = {
        "requests": {"name": "requests", "license": "Apache-2.0"},
        "bad": {"name": "bad", "license": "GPL-3.0"},
        "nolicense": {"name": "nolicense"},
    }
    bad = gate_license.validate_licenses(["requests", "missing", "bad", "nolicense"], items, ["Apache-2.0"])
    assert "MISSING_UPSTREAM missing" in bad
    assert "LICENSE_NOT_ALLOWED bad GPL-3.0" in bad
    assert "MISSING_LICENSE nolicense" in bad
    assert all("requests" not in item for item in bad)


def test_gate_upstream_extracts_refs_and_blocks_placeholders():
    refs = set()
    refs.update(gate_upstream.refs_from_added(".github/workflows/ci.yml", "uses: actions/checkout@v4"))
    refs.update(gate_upstream.refs_from_added("loopd/bootstrap.sh", "curl -L https://github.com/cli/cli/releases/x"))
    refs.update(gate_upstream.refs_from_added("requirements.txt", "PyYAML==6.0"))
    assert refs == {"actions/checkout", "cli/cli", "pyyaml"}
    items = {"actions/checkout": {"name": "actions/checkout", "pin": "v4"}, "cli/cli": {"name": "cli/cli", "sha256": "w0-fill"}}
    missing, placeholders = gate_upstream.validate_refs(sorted(refs), items)
    assert missing == ["pyyaml"]
    assert placeholders == ["cli/cli"]
