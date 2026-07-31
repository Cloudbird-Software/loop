"""tests/test_metrics.py — bench/metrics.py 的 CHARTER Q 指标计算测试（R14-3）。

覆盖 compute_q_metrics（从假 evidence 算 Q0~Q5、可回放、evidence 缺失不崩）、
check_q_thresholds（全达标/未达标）、write_dashboard（合法 JSON）、
compare_experiments（A/B 横向比较、缺字段不崩）。全部用 tmp_path 构造假 evidence，
不依赖网络/时间。
"""
import json
import os
import pathlib
import sys

import pytest

# 把仓库根加入 sys.path，使 `from bench import metrics` 与脚本直跑同路径。
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

from bench import metrics as M  # noqa: E402

METRICS_PY = pathlib.Path(WORKSPACE) / "bench" / "metrics.py"


# ---------- helpers：构造假 evidence ----------
def _replay_card(card_id="R-001", first_ci_pass=True, diff_lines=10):
    return {
        "id": card_id,
        "baseline_metrics": {
            "first_ci_pass": first_ci_pass,
            "reopen_count": 0,
            "diff_lines": diff_lines,
            "cost_yuan": 0.0,
        },
    }


def _claim_doc(verdicts=None):
    """verdicts: list of "REPRODUCED"/"NOT_REPRODUCED" 对应每条 claim 的复现结果。"""
    claims = []
    for i in range(len(verdicts or [])):
        claims.append({
            "id": f"CL-{i+1:03d}",
            "claim": f"assertion {i+1}",
            "repro": {"cmd": "true", "expected": "0", "actual": "0", "env": "env"},
            "falsifier": "exit non-zero",
        })
    return {
        "schema": 1,
        "review_id": "run-1",
        "reviewer_model": "gpt-5",
        "head_sha": "abc1234",
        "generated_at": "2026-07-31T00:00:00Z",
        "claims": claims,
    }


def _reproduction(claim_id, verdict):
    return {
        "schema": 1,
        "claim_id": claim_id,
        "review_id": "run-1",
        "verdict": verdict,
        "reproducer_model": "qwen3-max",
        "observed": {"cmd": "true", "exit_code": 0, "stdout_excerpt": ""},
        "env": "sandbox-1",
        "generated_at": "2026-07-31T01:00:00Z",
    }


def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def _full_passing_evidence(tmp_path):
    """构造一份全部 Q 达标的 evidence。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    _write_json(tmp_path / "R-001.json", _replay_card("R-001", first_ci_pass=True))
    _write_json(tmp_path / "R-002.json", _replay_card("R-002", first_ci_pass=True))
    # Q4：1 条 claim，复现成功
    _write_json(tmp_path / "claim-001.json", _claim_doc(verdicts=["REPRODUCED"]))
    _write_json(tmp_path / "repro-001.json", _reproduction("CL-001", "REPRODUCED"))
    # Q5：升级成功 + pin 新鲜 + 副本 0 + 豁免 0
    _write_json(tmp_path / "upgrade-001.json", {"upgrade_ok": True, "pkg": "some/dep"})
    _write_json(tmp_path / "pin.json", {
        "pin_lag_tags": 0, "pin_lag_days": 0,
        "mechanism_copy_count": 0, "template_sync_exemptions": 0,
    })
    # Q3：假绿 0
    _write_json(tmp_path / "gate.json", {"fake_green_count": 0,
                 "negative_test_coverage": 1.0, "settings_roundtrip_ok": True})
    return tmp_path


# ============================================================
# compute_q_metrics
# ============================================================
def test_compute_q_metrics_from_fake_evidence(tmp_path):
    """从假 evidence 算出全部 Q 指标，结构与数值符合预期。"""
    d = _full_passing_evidence(tmp_path)
    q = M.compute_q_metrics(str(d))

    # 全部 Q0~Q5 在
    assert set(q) == {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}
    for k, entry in q.items():
        assert {"value", "target", "status", "sub"}.issubset(entry), k

    # Q0：2 张卡都过 → 闭环成功率 1.0
    assert q["Q0"]["value"] == 1.0
    assert q["Q0"]["status"] == "pass"
    assert q["Q0"]["sub"]["Q0.3"]["value"] == 1.0

    # Q4：1 条复现 REPRODUCED → 1.0
    assert q["Q4"]["value"] == 1.0
    assert q["Q4"]["sub"]["Q4.1"]["value"] == 1.0

    # Q5：升级成功 + pin 新鲜 + 副本 0 + 豁免 0 → 1.0
    assert q["Q5"]["value"] == 1.0
    assert q["Q5"]["status"] == "pass"
    assert q["Q5"]["sub"]["Q5.4"]["value"] == 1.0

    # Q3：假绿 0
    assert q["Q3"]["value"] == 0
    assert q["Q3"]["status"] == "pass"


def test_compute_q_metrics_reproducible(tmp_path):
    """可回放：同一份 evidence 两次调用得到完全相同的结果。"""
    d = _full_passing_evidence(tmp_path)
    a = M.compute_q_metrics(str(d))
    b = M.compute_q_metrics(str(d))
    assert a == b, "同一份 evidence 重算必须得到相同数字"


def test_compute_q_metrics_missing_evidence_no_crash(tmp_path):
    """evidence 缺失时返回默认/零值，不崩；Q0~Q5 齐全。"""
    # 空目录
    q = M.compute_q_metrics(str(tmp_path))
    assert set(q) == {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}
    # 无 replay → Q0=0.0（fail）；无升级/pin → Q5=0.0（fail）；其余默认 pass
    assert q["Q0"]["value"] == 0.0
    assert q["Q0"]["status"] == "fail"
    assert q["Q5"]["value"] == 0.0
    assert q["Q5"]["status"] == "fail"
    # Q4 无 claim → 1.0（vacuous pass）
    assert q["Q4"]["value"] == 1.0
    # 不存在的目录也不崩
    q2 = M.compute_q_metrics(str(tmp_path / "does-not-exist"))
    assert set(q2) == {"Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}


def test_compute_q_metrics_q4_not_reproduced_fails(tmp_path):
    """Q4：复现 NOT_REPRODUCED → Q4.1=0.0，headline Q4 fail。"""
    _write_json(tmp_path / "claim-001.json", _claim_doc(verdicts=["NOT_REPRODUCED"]))
    _write_json(tmp_path / "repro-001.json", _reproduction("CL-001", "NOT_REPRODUCED"))
    q = M.compute_q_metrics(str(tmp_path))
    assert q["Q4"]["sub"]["Q4.1"]["value"] == 0.0
    assert q["Q4"]["status"] == "fail"


def test_compute_q_metrics_q5_upgrade_failure(tmp_path):
    """Q5：升级失败 → Q5.4=0.0，headline Q5 fail。"""
    _write_json(tmp_path / "upgrade-001.json", {"upgrade_ok": False, "pkg": "some/dep"})
    q = M.compute_q_metrics(str(tmp_path))
    assert q["Q5"]["sub"]["Q5.4"]["value"] == 0.0
    assert q["Q5"]["status"] == "fail"


# ============================================================
# check_q_thresholds
# ============================================================
def test_check_q_thresholds_all_pass(tmp_path):
    """全达标返回空列表。"""
    d = _full_passing_evidence(tmp_path)
    q = M.compute_q_metrics(str(d))
    failed = M.check_q_thresholds(q)
    assert failed == [], f"应全达标，但未达标项：{failed}"


def test_check_q_thresholds_returns_failures(tmp_path):
    """未达标返回非空列表，含 metric/value/target。"""
    # 一张失败的 replay 卡 → 闭环成功率 0.0 < 0.8
    _write_json(tmp_path / "R-001.json", _replay_card("R-001", first_ci_pass=False))
    q = M.compute_q_metrics(str(tmp_path))
    failed = M.check_q_thresholds(q)
    assert failed, "Q0 未达标应出现在 failed 列表"
    metrics_failed = [f["metric"] for f in failed]
    assert "Q0" in metrics_failed
    q0_fail = [f for f in failed if f["metric"] == "Q0"][0]
    assert q0_fail["value"] == 0.0
    assert q0_fail["target"] == 0.8


def test_check_q_thresholds_with_override_targets(tmp_path):
    """传入自定义 charter_targets 收紧阈值，原本 pass 的变 fail。"""
    d = _full_passing_evidence(tmp_path)
    q = M.compute_q_metrics(str(d))
    # 把 Q0 阈值抬高到 1.5（必 fail）
    stricter = dict(M.CHARTER_Q_TARGETS)
    stricter["Q0"] = {"target": 1.5, "direction": "ge"}
    failed = M.check_q_thresholds(q, stricter)
    assert any(f["metric"] == "Q0" for f in failed)


# ============================================================
# write_dashboard
# ============================================================
def test_write_dashboard_valid_json(tmp_path):
    """写出合法 JSON，含 metrics/charter_targets/failed 三段。"""
    d = _full_passing_evidence(tmp_path)
    q = M.compute_q_metrics(str(d))
    out = tmp_path / "dashboard.json"
    path = M.write_dashboard(q, str(out))
    assert path == str(out)
    data = json.loads(out.read_text())
    assert "metrics" in data
    assert "charter_targets" in data
    assert "failed" in data
    assert "generated_at" in data
    assert data["metrics"]["Q0"]["value"] == 1.0
    # 全达标 → failed 为空
    assert data["failed"] == []


def test_write_dashboard_overwrites(tmp_path):
    """每次运行覆盖写（不追加）。"""
    out = tmp_path / "dashboard.json"
    M.write_dashboard({"Q0": M._q_entry(0.5, 0.8, "ge")}, str(out))
    M.write_dashboard({"Q0": M._q_entry(1.0, 0.8, "ge")}, str(out))
    data = json.loads(out.read_text())
    assert data["metrics"]["Q0"]["value"] == 1.0


# ============================================================
# compare_experiments
# ============================================================
def test_compare_experiments_returns_table(tmp_path):
    """A/B 横向比较返回 rows + summary，delta 正负方向正确。"""
    # baseline：Q0=0.5（半数通过）
    d_b = tmp_path / "baseline"
    d_b.mkdir()
    _write_json(d_b / "R-001.json", _replay_card("R-001", first_ci_pass=True))
    _write_json(d_b / "R-002.json", _replay_card("R-002", first_ci_pass=False))
    # experiment：Q0=1.0（全通过，含升级证据使其余也达标）
    d_e = _full_passing_evidence(tmp_path / "experiment")

    b = M.compute_q_metrics(str(d_b))
    e = M.compute_q_metrics(str(d_e))
    cmp = M.compare_experiments(b, e)

    assert "rows" in cmp and "summary" in cmp
    rows = {r["metric"]: r for r in cmp["rows"]}
    assert "Q0" in rows
    # Q0 是 ge 方向，experiment 1.0 - baseline 0.5 = 0.5 → 更好
    assert rows["Q0"]["delta"] == 0.5
    assert rows["Q0"]["baseline_value"] == 0.5
    assert rows["Q0"]["experiment_value"] == 1.0
    assert cmp["summary"]["better"] >= 1
    assert cmp["summary"]["total"] == 6  # Q0~Q5


def test_compare_experiments_missing_fields_no_crash():
    """缺字段不崩：baseline 缺 Q2~Q5，experiment 缺 Q1，delta 记 None。"""
    baseline = {
        "Q0": M._q_entry(0.5, 0.8, "ge"),
        "Q1": M._q_entry(100, 1800, "le"),
    }
    experiment = {
        "Q0": M._q_entry(1.0, 0.8, "ge"),
        "Q2": M._q_entry(3, 5, "le"),
    }
    cmp = M.compare_experiments(baseline, experiment)
    rows = {r["metric"]: r for r in cmp["rows"]}
    # Q0 两边都有 → delta=0.5
    assert rows["Q0"]["delta"] == 0.5
    # Q1 仅 baseline 有 → experiment_value=None，delta=None
    assert rows["Q1"]["experiment_value"] is None
    assert rows["Q1"]["delta"] is None
    # Q2 仅 experiment 有 → baseline_value=None，delta=None
    assert rows["Q2"]["baseline_value"] is None
    assert rows["Q2"]["delta"] is None
    assert cmp["summary"]["total"] == 3


# ============================================================
# CLI（compute-q / dashboard）
# ============================================================
def test_cli_compute_q_outputs_json(tmp_path):
    """`metrics compute-q` 输出合法 JSON 且 --check 未达标退出 1。"""
    d = _full_passing_evidence(tmp_path)
    import subprocess
    r = subprocess.run(
        ["python3", str(METRICS_PY),
         "compute-q", "--evidence-dir", str(d), "--check"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # stdout 前半段是 JSON
    data = json.loads(r.stdout)
    assert data["Q0"]["value"] == 1.0


def test_cli_compute_q_check_exits_nonzero_on_fail(tmp_path):
    """未达标时 --check 退出 1 并打印 Q_THRESHOLD_FAILED 行。"""
    _write_json(tmp_path / "R-001.json", _replay_card("R-001", first_ci_pass=False))
    import subprocess
    r = subprocess.run(
        ["python3", str(METRICS_PY),
         "compute-q", "--evidence-dir", str(tmp_path), "--check"],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "Q_THRESHOLD_FAILED: Q0" in r.stdout
