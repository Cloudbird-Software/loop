#!/usr/bin/env python3
"""tests/test_claims.py — R12-1 claim 校验器测试。

覆盖：合法 claim、缺 repro、缺 falsifier、主观措辞、id 冲突、confidence 越界、
reproduction 三态各一，共 ≥10 个用例。

同时承载 R12-3 的角色阀门测试（materialize.py reviewer/reproducer）。
"""
import json, os, sys, tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conductor import claims


# ---------- helpers ----------
def _valid_claim(cid="CL-001"):
    return {
        "id": cid,
        "claim": "gate_heterogeneity.py does not check review/reproduce route",
        "path": "gates/gate_heterogeneity.py",
        "severity": "high",
        "confidence": 0.8,
        "repro": {
            "cmd": "grep -c 'review.*reproduce' gates/gate_heterogeneity.py",
            "expected": "1",
            "actual": "0",
            "env": "commit abc1234 / ubuntu-22.04 / python3.11",
        },
        "predicted_observation": "grep returns 0 matches in the file",
        "falsifier": "grep finds at least one match for review.*reproduce",
        "suggested_checker": "gate_heterogeneity",
    }


def _valid_doc(claims_list=None):
    if claims_list is None:
        claims_list = [_valid_claim()]
    return {
        "schema": 1,
        "review_id": "loop-run-1-attempt-1",
        "reviewer_model": "gpt-5",
        "reviewer_seam_b": "copilot-cli",
        "head_sha": "abc1234def5678",
        "generated_at": "2026-07-31T00:00:00Z",
        "claims": claims_list,
    }


def _valid_reproduction(verdict="REPRODUCED", reproducer="qwen3-max"):
    rep = {
        "schema": 1,
        "claim_id": "CL-001",
        "review_id": "loop-run-1-attempt-1",
        "verdict": verdict,
        "reproducer_model": reproducer,
        "observed": {
            "cmd": "grep -c 'review.*reproduce' gates/gate_heterogeneity.py",
            "exit_code": 0,
            "stdout_excerpt": "1",
        },
        "env": "sandbox-1 / commit abc1234 / ubuntu-22.04",
        "generated_at": "2026-07-31T01:00:00Z",
    }
    if verdict != "REPRODUCED":
        rep["diff_note"] = "命令输出 1，但 claim 声称 actual=0，输出与 claim 记录不符"
    return rep


# ============================================================
# R12-1: claim 校验器测试
# ============================================================
class TestClaimValidation:
    def test_valid_claim_accepted(self):
        """合法 claim 应通过校验。"""
        doc = _valid_doc()
        errors, warnings, valid = claims.validate_claim_document(doc)
        assert errors == [], f"valid claim should pass, got errors: {errors}"
        assert len(valid) == 1
        assert warnings == []

    def test_missing_repro_rejected(self):
        """缺 repro 字段应拒收。"""
        c = _valid_claim()
        del c["repro"]
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("MISSING_FIELDS" in e for e in errors)
        assert any("repro" in e for e in errors)

    def test_missing_falsifier_rejected(self):
        """缺 falsifier 字段应拒收。"""
        c = _valid_claim()
        del c["falsifier"]
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("MISSING_FIELDS" in e for e in errors)
        assert any("falsifier" in e for e in errors)

    def test_missing_predicted_observation_rejected(self):
        """缺 predicted_observation 字段应拒收。"""
        c = _valid_claim()
        del c["predicted_observation"]
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("MISSING_FIELDS" in e for e in errors)
        assert any("predicted_observation" in e for e in errors)

    def test_subjective_wording_without_repro_rejected(self):
        """命中主观词表且无可执行 repro 的 claim 应拒收。"""
        c = _valid_claim()
        c["claim"] = "这段代码不够优雅，建议重构"
        c["repro"] = {"cmd": "", "expected": "", "actual": "", "env": ""}
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("SUBJECTIVE_WORD_WITHOUT_REPRO" in e for e in errors)

    def test_subjective_wording_with_repro_accepted(self):
        """命中主观词表但有可执行 repro 的 claim 应通过（不越权判断真值）。"""
        c = _valid_claim()
        c["claim"] = "这段代码不够优雅，建议重构——grep 证实缺少 heterogeneity 检查"
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert errors == [], f"subjective+repro should pass, got: {errors}"

    def test_duplicate_id_rejected(self):
        """同一评审轮内 id 冲突应拒收。"""
        c1 = _valid_claim("CL-001")
        c2 = _valid_claim("CL-001")
        c2["claim"] = "另一条不同的断言"
        doc = _valid_doc([c1, c2])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("DUPLICATE_ID" in e for e in errors)

    def test_bad_id_format_rejected(self):
        """id 不符合 ^CL-\\d{3}$ 应拒收。"""
        c = _valid_claim("CL-1")
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("BAD_ID" in e for e in errors)

    def test_confidence_out_of_range_rejected(self):
        """confidence >1 应拒收。"""
        c = _valid_claim()
        c["confidence"] = 1.5
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("CONFIDENCE_OUT_OF_RANGE" in e for e in errors)

    def test_confidence_below_min_dropped_not_rejected(self):
        """confidence 低于 min_confidence 应丢弃(warning)而非拒收(error)。"""
        c = _valid_claim()
        c["confidence"] = 0.3
        doc = _valid_doc([c])
        errors, warnings, valid = claims.validate_claim_document(doc)
        assert errors == [], "low confidence should not reject the batch"
        assert len(warnings) == 1
        assert "LOW_CONFIDENCE" in warnings[0]
        assert len(valid) == 0, "low-confidence claim should be dropped from valid"

    def test_bad_severity_rejected(self):
        """非法 severity 应拒收。"""
        c = _valid_claim()
        c["severity"] = "blocker"
        doc = _valid_doc([c])
        errors, _, _ = claims.validate_claim_document(doc)
        assert any("BAD_SEVERITY" in e for e in errors)

    def test_next_id_allocation(self):
        """next_id 应分配下一个可用 id。"""
        existing = {"CL-001", "CL-002"}
        assert claims.next_id(existing) == "CL-003"
        existing2 = {"CL-001", "CL-003"}
        assert claims.next_id(existing2) == "CL-002"

    def test_cli_validate_valid_file(self, tmp_path):
        """CLI validate 子命令对合法文件应返回 0。"""
        f = tmp_path / "claims.json"
        f.write_text(json.dumps(_valid_doc()), encoding="utf-8")
        rc = claims._cmd_validate(str(f))
        assert rc == 0

    def test_cli_validate_rejects_bad_file(self, tmp_path):
        """CLI validate 子命令对非法文件应返回 1。"""
        doc = _valid_doc()
        del doc["claims"]
        f = tmp_path / "claims.json"
        f.write_text(json.dumps(doc), encoding="utf-8")
        rc = claims._cmd_validate(str(f))
        assert rc == 1

    def test_cli_ingest_returns_structure(self, tmp_path):
        """CLI ingest 子命令应返回结构化 JSON。"""
        f = tmp_path / "claims.json"
        f.write_text(json.dumps(_valid_doc()), encoding="utf-8")
        rc = claims._cmd_ingest(str(f))
        assert rc == 0


# ============================================================
# R12-1: reproduction 三态测试
# ============================================================
class TestReproductionValidation:
    def test_reproduced_valid(self):
        """REPRODUCED verdict 应通过。"""
        rep = _valid_reproduction("REPRODUCED")
        errs = claims.validate_reproduction(rep)
        assert errs == [], f"REPRODUCED should pass, got: {errs}"

    def test_not_reproduced_valid_with_diff_note(self):
        """NOT_REPRODUCED + diff_note 应通过。"""
        rep = _valid_reproduction("NOT_REPRODUCED")
        errs = claims.validate_reproduction(rep)
        assert errs == [], f"NOT_REPRODUCED with diff_note should pass, got: {errs}"

    def test_inconclusive_valid_with_diff_note(self):
        """INCONCLUSIVE + diff_note 应通过。"""
        rep = _valid_reproduction("INCONCLUSIVE")
        errs = claims.validate_reproduction(rep)
        assert errs == [], f"INCONCLUSIVE with diff_note should pass, got: {errs}"

    def test_not_reproduced_without_diff_note_rejected(self):
        """NOT_REPRODUCED 缺 diff_note 应拒收。"""
        rep = _valid_reproduction("NOT_REPRODUCED")
        del rep["diff_note"]
        errs = claims.validate_reproduction(rep)
        assert any("MISSING_DIFF_NOTE" in e for e in errs)

    def test_self_adjudication_rejected(self):
        """reproducer_model == reviewer_model 应拒收（异构强制）。"""
        rep = _valid_reproduction("REPRODUCED", reproducer="gpt-5")
        errs = claims.validate_reproduction(rep, reviewer_model="gpt-5")
        assert any("SELF_ADJUDICATION" in e for e in errs)

    def test_bad_verdict_rejected(self):
        """非法 verdict 应拒收。"""
        rep = _valid_reproduction("MAYBE")
        errs = claims.validate_reproduction(rep)
        assert any("BAD_VERDICT" in e for e in errs)


# ============================================================
# R12-3: materialize.py 角色阀门测试（本文件承载，不新增测试文件）
# ============================================================
class TestRoleValves:
    def test_reviewer_can_create_claim(self):
        """reviewer 角色应能创建 Claim 对象。"""
        from conductor import materialize
        materialize._enforce_role("reviewer", "Claim")  # should not raise

    def test_reviewer_cannot_create_card(self):
        """reviewer 角色不应能创建 Card。"""
        from conductor import materialize
        with pytest.raises(ValueError, match="ROLE_VALVE_VIOLATION"):
            materialize._enforce_role("reviewer", "Card")

    def test_reproducer_can_create_reproduction(self):
        """reproducer 角色应能创建 Reproduction 对象。"""
        from conductor import materialize
        materialize._enforce_role("reproducer", "Reproduction")  # should not raise

    def test_reproducer_can_create_finding_on_confirmed(self):
        """reproducer 角色应能创建 Finding（对已确认 claim）。"""
        from conductor import materialize
        materialize._enforce_role("reproducer", "Finding")  # should not raise

    def test_reproducer_cannot_create_card(self):
        """reproducer 角色不应能创建 Card。"""
        from conductor import materialize
        with pytest.raises(ValueError, match="ROLE_VALVE_VIOLATION"):
            materialize._enforce_role("reproducer", "Card")

    def test_self_adjudication_refused(self):
        """同一 (model, session_id) 既是 claim 作者又是 reproducer 应拒绝。"""
        from conductor import materialize
        with pytest.raises(ValueError, match="SELF_ADJUDICATION_REFUSED"):
            materialize.check_self_adjudication(
                reviewer_model="gpt-5", reviewer_session="sess-1",
                reproducer_model="gpt-5", reproducer_session="sess-1",
            )

    def test_self_adjudication_same_model_diff_session_refused(self):
        """同 model 不同 session 也应拒绝（model 维度即可判定自证）。"""
        from conductor import materialize
        with pytest.raises(ValueError, match="SELF_ADJUDICATION_REFUSED"):
            materialize.check_self_adjudication(
                reviewer_model="gpt-5", reviewer_session="sess-1",
                reproducer_model="gpt-5", reproducer_session="sess-2",
            )

    def test_heterogeneous_models_allowed(self):
        """异构 model + 不同 session 应通过。"""
        from conductor import materialize
        materialize.check_self_adjudication(
            reviewer_model="gpt-5", reviewer_session="sess-1",
            reproducer_model="qwen3-max", reproducer_session="sess-2",
        )  # should not raise

    def test_existing_roles_not_weakened(self):
        """既有角色阀门不得被削弱：impl 仍不能建 Card。"""
        from conductor import materialize
        with pytest.raises(ValueError, match="ROLE_VALVE_VIOLATION"):
            materialize._enforce_role("impl", "Card")
        with pytest.raises(ValueError, match="ROLE_VALVE_VIOLATION"):
            materialize._enforce_role("verify", "Card")

    def test_existing_create_types_still_work(self):
        """既有创建类型仍应正常工作。"""
        from conductor import materialize
        materialize._enforce_role("materializer", "Card")  # should not raise
        materialize._enforce_role("auditor", "Finding")    # should not raise
        materialize._enforce_role("planner", "Wave")       # should not raise
