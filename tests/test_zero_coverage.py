#!/usr/bin/env python3
"""tests/test_zero_coverage.py — R14-4：为零测试覆盖的承重模块建立最小可信测试。

覆盖 6 个在 tests/ 与 seam_a/ 中零（承重）覆盖的模块：
  - loopd/loopd.py        ：CAS 领卡(write_block)、lease/heartbeat(heartbeat_thread)、
                            僵尸回收(reap_once)、_validate_finding、_validate_verdict、
                            以及 prio/GLOB/extract_block/_iso_to_ts 等承重纯函数。
  - conductor/materialize.py ：auto_tier / GLOB 父目录冲突 / extract_wave_meta /
                            validate_charter（test_C_pkg 已覆盖 validate/materialize_wave，
                            此处补其未覆盖的承重纯函数）。
  - conductor/scribe_report.py：count_confirm_taps / detect_zombie_cards /
                            detect_bypass_actors / summarize_canary / compute_cost。
  - conductor/routing_metrics.py：aggregate_metrics / compute_demotion /
                            backfill 幂等 / apply_demotion / replay_from_evidence。
  - conductor/claim_intake.py：is_claim_pickable_by_impl / _build_fcard / assert_reproduced。
  - conductor/drift_check.py：fingerprint 稳定指纹。

设计原则（卡片验收 #2）：每条承重路径都有一个会失败的测试——断言保护关键不变量，
对应逻辑被破坏时测试变红。loopd 的网络/gh 调用全部用 monkeypatch 替换；
loopd 未做任何重构（承重纯函数本就可直接 import 测试；状态函数用 _fresh_loopd
重载到 tmp 目录隔离全局状态）。
"""
import importlib
import json
import os
import pathlib
import sys
import threading
import time
import datetime
from subprocess import CompletedProcess

import pytest

# 仓库根加入 sys.path，使 from conductor / import loopd.loopd 走同一命名空间路径
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ============================================================
# 通用辅助
# ============================================================
def _cp(stdout="", returncode=0, stderr=""):
    """构造 subprocess.CompletedProcess 风格对象，供 mock gh 返回。"""
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _loop_block(blk):
    """构造含 ```json loop``` 块的 issue body（write_block/cards 解析所需）。"""
    return (
        "前言\n```json loop\n"
        + json.dumps(blk, indent=2, ensure_ascii=False)
        + "\n```\n后缀\n"
    )


def _fresh_loopd(tmp_path, monkeypatch, lease_min="30", branch_prefix="loop/card"):
    """用一个干净的 LOOP_ROOT 重新 import loopd.loopd，隔离全局状态 / STATE 文件。

    返回已调用 CFG()（LOOP 目录已建、模块全局变量已物化）的模块对象。
    """
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("LOOP_ROOT", str(root))
    monkeypatch.setenv("LOOP_WS", str(root))
    monkeypatch.setenv("LOOP_SANDBOX_ID", "test-sbx")
    monkeypatch.setenv("LOOP_ROLE", "impl")
    monkeypatch.setenv("LOOP_MODEL", "test-model")
    monkeypatch.setenv("LOOP_LEASE_MIN", lease_min)
    monkeypatch.setenv("LOOP_BRANCH_PREFIX", branch_prefix)
    monkeypatch.setenv("LOOP_ORG", "TestOrg")
    monkeypatch.setenv("LOOP_REPO", "loop")
    sys.modules.pop("loopd.loopd", None)
    sys.modules.pop("loopd", None)
    mod = importlib.import_module("loopd.loopd")
    mod.CFG()  # 初始化全局变量 + 建 tmp/.loop
    return mod


def _make_fake_gh(issues, prs=None):
    """构造内存版 gh：支持 issue view/list/edit + pr list。

    issues: {num_str: {"body":..., "updatedAt":...}}
    prs:    {head_branch: [{"number":.., "updatedAt": iso}, ...]}
    """
    prs = prs or {}

    def _num_after(sub):
        # 找 sub 之后的第一个非 flag 位置参数（issue number）
        for x in sub:
            if x.startswith("-"):
                continue
            return x
        return None

    def fake_gh(*a, **kw):
        if a[0] == "issue" and len(a) > 1 and a[1] == "view":
            num = _num_after(a[2:])
            fields = a[a.index("--json") + 1] if "--json" in a else "body"
            it = issues.get(str(num), {"body": "", "updatedAt": ""})
            out = {}
            if "body" in fields:
                out["body"] = it.get("body", "")
            if "updatedAt" in fields:
                out["updatedAt"] = it.get("updatedAt", "")
            return _cp(json.dumps(out))
        if a[0] == "issue" and len(a) > 1 and a[1] == "edit":
            num = _num_after(a[2:])
            path = a[a.index("--body-file") + 1] if "--body-file" in a else None
            if path and pathlib.Path(path).exists():
                issues[str(num)]["body"] = pathlib.Path(path).read_text()
                # 模拟 GitHub 写后 updatedAt 变化（CAS 语义）
                issues[str(num)]["updatedAt"] = issues[str(num)].get("updatedAt", "T1") + "x"
            return _cp("")
        if a[0] == "issue" and len(a) > 1 and a[1] == "list":
            out = [
                {"number": int(n), "body": d["body"], "updatedAt": d["updatedAt"],
                 "title": f"#{n}", "labels": []}
                for n, d in issues.items()
            ]
            return _cp(json.dumps(out))
        if a[0] == "pr" and len(a) > 1 and a[1] == "list":
            head = a[a.index("--head") + 1] if "--head" in a else None
            return _cp(json.dumps(prs.get(head, [])))
        return _cp("")
    return fake_gh


# 顶层 import 一次 loopd.loopd，供纯函数测试使用（纯函数不触发 CFG/网络）。
import loopd.loopd as L  # noqa: E402
import conductor.materialize as M  # noqa: E402
import conductor.scribe_report as S  # noqa: E402
import conductor.routing_metrics as RM  # noqa: E402
import conductor.claim_intake as CI  # noqa: E402
import conductor.drift_check as DC  # noqa: E402


# ============================================================
# loopd —— CAS 领卡（write_block 是领卡/续约的 CAS 原语）
# ============================================================
class TestLoopdCAS:
    def test_write_block_rejects_stale_updated_at(self, tmp_path, monkeypatch):
        """CAS 不变量：updatedAt 不匹配（并发竞争）→ 拒写，返回 False，issue body 不变。"""
        mod = _fresh_loopd(tmp_path, monkeypatch)
        old_blk = {"id": "C1", "claim_id": "OLD", "state": "ready", "paths": ["src/a"]}
        issues = {"42": {"body": _loop_block(old_blk), "updatedAt": "T1"}}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues))

        new_blk = dict(old_blk, state="claimed", claim_id="NEW")
        # 传入过期的 expected updatedAt → CAS 前置校验必须拒绝
        ok = mod.write_block(42, new_blk, "STALE_TS")
        assert ok is False, "CAS 失效：updatedAt 不匹配仍写入"
        # body 未被改写
        back = mod.extract_block(issues["42"]["body"])
        assert back["claim_id"] == "OLD", "CAS 拒写期间 body 不应改变"

    def test_write_block_success_persists_claim_id(self, tmp_path, monkeypatch):
        """CAS 成功：updatedAt 匹配 → 写入并回读确认 claim_id。"""
        mod = _fresh_loopd(tmp_path, monkeypatch)
        old_blk = {"id": "C1", "claim_id": "OLD", "state": "ready", "paths": ["src/a"]}
        issues = {"42": {"body": _loop_block(old_blk), "updatedAt": "T1"}}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues))

        new_blk = dict(old_blk, state="claimed", claim_id="NEW")
        ok = mod.write_block(42, new_blk, "T1")
        assert ok is True, "CAS 成功应返回 True"
        back = mod.extract_block(issues["42"]["body"])
        assert back["claim_id"] == "NEW" and back["state"] == "claimed"


# ============================================================
# loopd —— lease / heartbeat（heartbeat_thread 续约租约）
# ============================================================
class TestLoopdHeartbeat:
    def test_heartbeat_extends_lease_and_updates_heartbeat_at(self, tmp_path, monkeypatch):
        """heartbeat 单次迭代必须：推进 heartbeat_at、把 lease_until 续期 LOOP_LEASE_MIN 分钟。"""
        mod = _fresh_loopd(tmp_path, monkeypatch, lease_min="30")
        now = int(time.time())
        old_lease = now - 1000
        blk = {"id": "C1", "claim_id": "X1", "state": "claimed",
               "lease_until": old_lease, "heartbeat_at": old_lease, "paths": ["src/a"], "attempt": 0}
        # 预置活跃卡到 STATE
        mod.st(card={"num": 42, "blk": blk})
        issues = {"42": {"body": _loop_block(blk), "updatedAt": "T1"}}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues))

        # 让 heartbeat_thread 跑完一次 sleep 即抛出，打断 while True
        calls = {"n": 0}

        def boom(_):
            calls["n"] += 1
            raise StopIteration("one-beat-done")

        monkeypatch.setattr(mod.time, "sleep", boom)
        with pytest.raises(StopIteration):
            mod.heartbeat_thread()

        assert calls["n"] == 1, "heartbeat 应至少完成一次循环体"
        d = mod.st()
        new_blk = d["card"]["blk"]
        # 续约不变量：heartbeat_at 推进、lease_until 续期约 30 分钟
        assert new_blk["heartbeat_at"] > old_lease, "heartbeat_at 未推进"
        assert new_blk["lease_until"] >= old_lease + 29 * 60, "lease 未续期 LOOP_LEASE_MIN 分钟"


# ============================================================
# loopd —— 僵尸回收（reap_once：lease 过期且无 commit → 退回 ready）
# ============================================================
class TestLoopdReaper:
    def test_reap_once_reclaims_expired_no_commit_card(self, tmp_path, monkeypatch):
        """lease 过期 + lease 期内无 PR commit → 退回 ready，attempt+1，清 claim/lease 字段。"""
        mod = _fresh_loopd(tmp_path, monkeypatch, lease_min="45")
        now = int(time.time())
        blk_a = {"id": "CA", "claim_id": "XA", "state": "claimed",
                 "lease_until": now - 100, "heartbeat_at": now - 100, "attempt": 0, "paths": ["src/a"]}
        # 无 PR → has_commit=False
        issues = {"1": {"body": _loop_block(blk_a), "updatedAt": "T1"}}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues))

        reclaimed = mod.reap_once()
        assert [r[0] for r in reclaimed] == [1], "过期无 commit 的卡应被回收"
        after = mod.extract_block(issues["1"]["body"])
        assert after["state"] == "ready"
        assert after["attempt"] == 1
        assert "claim_id" not in after and "lease_until" not in after and "heartbeat_at" not in after

    def test_reap_once_skips_card_with_recent_commit(self, tmp_path, monkeypatch):
        """lease 过期但 lease 期内有 PR commit（沙盒还在干活）→ 不回收。"""
        mod = _fresh_loopd(tmp_path, monkeypatch, lease_min="45")
        now = int(time.time())
        blk_b = {"id": "CB", "claim_id": "XB", "state": "in_progress",
                 "lease_until": now - 100, "heartbeat_at": now - 100, "attempt": 0, "paths": ["src/b"]}
        issues = {"2": {"body": _loop_block(blk_b), "updatedAt": "T2"}}
        # lease_start = lease_until - 45*60 ≈ now-2800；PR updatedAt=now-10 > lease_start → 有 commit
        iso_recent = datetime.datetime.fromtimestamp(now - 10, datetime.timezone.utc).isoformat()
        prs = {"loop/card/CB": [{"number": 9, "updatedAt": iso_recent}]}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues, prs))

        reclaimed = mod.reap_once()
        assert [r[0] for r in reclaimed] == [], "lease 期内有 commit 的卡不应被回收"
        assert mod.extract_block(issues["2"]["body"])["state"] == "in_progress"

    def test_reap_once_skips_non_expired_lease(self, tmp_path, monkeypatch):
        """lease 未过期 → 不回收。"""
        mod = _fresh_loopd(tmp_path, monkeypatch, lease_min="45")
        now = int(time.time())
        blk_c = {"id": "CC", "claim_id": "XC", "state": "claimed",
                 "lease_until": now + 9999, "heartbeat_at": now, "attempt": 0, "paths": ["src/c"]}
        issues = {"3": {"body": _loop_block(blk_c), "updatedAt": "T3"}}
        monkeypatch.setattr(mod, "gh", _make_fake_gh(issues))

        reclaimed = mod.reap_once()
        assert [r[0] for r in reclaimed] == [], "未过期 lease 的卡不应被回收"


# ============================================================
# loopd —— _validate_finding（finding schema 校验，无证据拒收）
# ============================================================
class TestLoopdValidateFinding:
    def _valid(self):
        return {
            "lens": "dead-code", "severity": "high", "message": "unused fn",
            "path": "src/a.py",
            "evidence": [{"tool": "lens", "rule_id": "DC-1", "location": "src/a.py:10"}],
        }

    def test_valid_finding_accepted(self):
        ok, err = L._validate_finding(self._valid())
        assert ok is True and err == ""

    def test_missing_evidence_field_rejected(self):
        f = self._valid()
        del f["evidence"]
        ok, err = L._validate_finding(f)
        assert ok is False and "MISSING_FIELDS" in err and "evidence" in err

    def test_empty_evidence_array_rejected(self):
        f = self._valid()
        f["evidence"] = []
        ok, err = L._validate_finding(f)
        assert ok is False and "NO_EVIDENCE" in err

    def test_bad_evidence_item_missing_tool_rejected(self):
        f = self._valid()
        f["evidence"] = [{"rule_id": "DC-1", "location": "src/a.py:10"}]  # 缺 tool
        ok, err = L._validate_finding(f)
        assert ok is False and "BAD_EVIDENCE" in err

    def test_bad_severity_rejected(self):
        f = self._valid()
        f["severity"] = "blocker"
        ok, err = L._validate_finding(f)
        assert ok is False and "BAD_SEVERITY" in err

    def test_non_dict_rejected(self):
        ok, err = L._validate_finding("not a dict")
        assert ok is False


# ============================================================
# loopd —— _validate_verdict（接口契约 0.6 VERDICT schema）
# ============================================================
class TestLoopdValidateVerdict:
    def _valid(self):
        return {
            "head_sha": "abc123", "blind_phase_commit": "def456",
            "artifact_digest": "sha256:xyz", "test_plan_version": "v1",
            "acs": [{"id": "AC1", "pass": True, "evidence": "f.py::t1"}],
        }

    def test_valid_verdict_accepted(self):
        ok, err = L._validate_verdict(self._valid())
        assert ok is True and err == ""

    def test_missing_acs_rejected(self):
        v = self._valid()
        del v["acs"]
        ok, err = L._validate_verdict(v)
        assert ok is False and "MISSING_FIELDS" in err

    def test_empty_acs_rejected(self):
        v = self._valid()
        v["acs"] = []
        ok, err = L._validate_verdict(v)
        assert ok is False and "NO_ACS" in err

    def test_ac_pass_not_bool_rejected(self):
        v = self._valid()
        v["acs"] = [{"id": "AC1", "pass": "yes", "evidence": "f.py::t1"}]
        ok, err = L._validate_verdict(v)
        assert ok is False and "BAD_AC" in err and "pass must be bool" in err

    def test_ac_missing_evidence_rejected(self):
        v = self._valid()
        v["acs"] = [{"id": "AC1", "pass": True}]  # 缺 evidence
        ok, err = L._validate_verdict(v)
        assert ok is False and "BAD_AC" in err and "evidence" in err

    def test_empty_head_sha_rejected(self):
        v = self._valid()
        v["head_sha"] = "  "
        ok, err = L._validate_verdict(v)
        assert ok is False and "EMPTY_FIELD" in err and "head_sha" in err


# ============================================================
# loopd —— 其他承重纯函数
# ============================================================
class TestLoopdPureHelpers:
    def test_prio_tier_then_id_ordering(self):
        """prio: trivial < standard < critical；同 tier 按 id 升序。"""
        trivial = L.prio({"tier": "trivial", "id": "z"})
        standard = L.prio({"tier": "standard", "id": "a"})
        critical = L.prio({"tier": "critical", "id": "a"})
        assert trivial < standard < critical
        # 同 tier 按 id 升序
        assert L.prio({"tier": "standard", "id": "a"}) < L.prio({"tier": "standard", "id": "b"})

    def test_glob_overlap_and_disjoint(self):
        assert L.GLOB(["src/a/**"], ["src/a/b/**"]) is True
        assert L.GLOB(["src/x/**"], ["src/y/**"]) is False

    def test_extract_block_parses_and_rejects_bad(self):
        blk = {"id": "C1", "state": "ready"}
        body = _loop_block(blk)
        assert L.extract_block(body) == blk
        assert L.extract_block("no block here") is None
        assert L.extract_block("```json loop\n{not json}\n```") is None

    def test_iso_to_ts_valid_and_invalid(self):
        ts = L._iso_to_ts("2026-07-31T00:00:00+00:00")
        assert ts > 0
        # 无效输入返回 0.0（不能崩）
        assert L._iso_to_ts("not-a-date") == 0.0
        assert L._iso_to_ts("") == 0.0

    def test_enforce_checker_title_only_at_occ_ge_3(self):
        """occurrences<3 不改标题；>=3 单一 rule_id → 标题含 lens.rule_id。"""
        finding = {"lens": "dead-code", "occurrences": 2,
                   "evidence": [{"rule_id": "DC-1", "tool": "lens", "location": "x"}]}
        pc = {"title": "原标题"}
        L._enforce_checker_title(dict(finding), pc)
        assert pc["title"] == "原标题", "occ<3 不应改写标题"

        finding3 = {"lens": "dead-code", "occurrences": 3,
                    "evidence": [{"rule_id": "DC-1", "tool": "lens", "location": "x"}]}
        pc2 = {"title": "原标题"}
        L._enforce_checker_title(dict(finding3), pc2)
        assert pc2["title"] == "为 dead-code.DC-1 写一个检查器"

    def test_finding_body_contains_fingerprint_and_proposed_card(self):
        finding = {"lens": "dead-code", "severity": "high", "message": "m", "path": "p",
                   "evidence": [{"tool": "lens", "rule_id": "DC-1", "location": "p"}],
                   "occurrences": 1}
        body = L._finding_body(dict(finding), "fpabcd1234")
        assert "```json finding" in body
        assert "fpabcd1234" in body
        assert "```json loop" in body  # proposed_card 块

    def test_bump_occurrences_merges_evidence_and_increments(self):
        old_finding = {"lens": "l", "severity": "high", "message": "m", "path": "p",
                       "evidence": [{"tool": "t", "rule_id": "r1", "location": "a"}],
                       "occurrences": 2, "fingerprint": "fp1"}
        # _bump_occurrences 保留 finding 块之前的 head 内容，重写 finding 块本身
        ex_issue = {"body": "preamble-before\n```json finding\n" + json.dumps(old_finding) + "\n```\n"}
        new_finding = {"evidence": [{"tool": "t", "rule_id": "r2", "location": "b"},
                                    {"tool": "t", "rule_id": "r1", "location": "a"}]}  # r1 与旧重复
        new_body, occ = L._bump_occurrences(ex_issue, "fp1", new_finding)
        assert occ == 3, "occurrences 必须 +1"
        assert "preamble-before" in new_body  # 保留 finding 块之前的 head
        assert '"r1"' in new_body and '"r2"' in new_body  # evidence 合并
        assert '"occurrences": 3' in new_body


# ============================================================
# materialize —— 补 test_C_pkg 未覆盖的承重纯函数
# ============================================================
class TestMaterializeHelpers:
    def test_auto_tier_promotes_sensitive_paths_to_critical(self):
        card = {"id": "C1", "tier": "standard", "paths": ["src/auth/login.py"]}
        M.auto_tier(card)
        assert card["tier"] == "critical", "auth 路径应自动升 critical"

    def test_auto_tier_leaves_normal_paths(self):
        card = {"id": "C2", "tier": "standard", "paths": ["docs/guide.md"]}
        M.auto_tier(card)
        assert card["tier"] == "standard"

    def test_glob_parent_dir_conflict(self):
        """GLOB 父目录关系：src/a/** 与 src/a/b/** 视为交叉。"""
        assert M.GLOB(["src/a/**"], ["src/a/b/**"]) is True
        assert M.GLOB(["src/a/b/**"], ["src/a/**"]) is True
        assert M.GLOB(["src/x/**"], ["src/y/**"]) is False

    def test_extract_wave_meta_id_from_title_and_fallback(self):
        wid, title, summary = M.extract_wave_meta("# WAVE-14: Foo\n> A summary\n")
        assert wid == "WAVE-14"
        assert title == "WAVE-14: Foo"
        assert summary == "A summary"
        # fallback：标题无 WAVE，但从正文派生
        wid2, _, _ = M.extract_wave_meta("# Some Title\n> see WAVE-99\n")
        assert wid2 == "WAVE-99"

    def test_validate_charter_placeholder_when_charter_missing(self):
        """CHARTER.md 缺失（charter_ids=None）→ charter 自动降到 ['G0'] 占位，不报错。"""
        card = {"id": "C1", "charter": ["G9"]}
        err = M.validate_charter(card, None, "C1")
        assert err is None
        assert card["charter"] == ["G0"], "CHARTER.md 缺失应自动降为 G0 占位"

    def test_validate_charter_unknown_ref_rejected(self):
        card = {"id": "C1", "charter": ["G9"]}
        err = M.validate_charter(card, {"G0", "G1"}, "C1")
        assert err is not None and "G9" in err


# ============================================================
# scribe_report —— 日报五字段确定性
# ============================================================
class TestScribeReport:
    def test_count_confirm_taps(self, tmp_path):
        assert S.count_confirm_taps(str(tmp_path)) == (0, [])  # 无文件
        (tmp_path / "taps.log").write_text("line1\nline2\n\nline3\n")
        n, lines = S.count_confirm_taps(str(tmp_path))
        assert n == 3 and len(lines) == 3

    def test_detect_zombie_cards(self):
        ref_ts = 200.0
        issues = [
            # 僵尸：claimed 且 lease < ref
            {"number": 1, "body": _loop_block({"id": "Z1", "state": "claimed", "lease_until": 100})},
            # 非僵尸：ready
            {"number": 2, "body": _loop_block({"id": "Z2", "state": "ready", "lease_until": 100})},
            # 非僵尸：lease 未过期
            {"number": 3, "body": _loop_block({"id": "Z3", "state": "claimed", "lease_until": 300})},
            # 非 loop 块 → 跳过
            {"number": 4, "body": "no block"},
        ]
        z = S.detect_zombie_cards(issues, ref_ts)
        assert len(z) == 1 and z[0]["number"] == 1

    def test_detect_bypass_actors(self):
        suites = [
            {"result": "bypass", "bypass_actor": {"login": "alice"}},
            {"result": "bypass", "bypass_actor": {"login": "alice"}},  # 累加
            {"result": "pass", "actor": {"login": "bob"}},  # 非 bypass
            {"result": "bypass", "actor": {"login": "carol"}},  # 无 bypass_actor，用 actor
        ]
        actors = S.detect_bypass_actors(suites)
        assert actors == {"alice": 2, "carol": 1}

    def test_summarize_canary(self):
        runs = [
            {"name": "canary-chain", "conclusion": "success",
             "run_started_at": "2026-01-01T00:00:00Z", "id": 1},
            {"name": "canary-chain", "conclusion": "failure",
             "run_started_at": "2026-01-02T00:00:00Z", "id": 2},
            {"name": "pr-ci", "conclusion": "success",
             "run_started_at": "2026-01-03T00:00:00Z", "id": 3},  # 非 canary
        ]
        c = S.summarize_canary(runs, 0)
        assert c["total"] == 2 and c["success"] == 1 and c["failure"] == 1
        assert "#2" in c["latest"]

    def test_compute_cost_from_duration_and_timestamps(self):
        # 显式 duration_ms 优先
        runs1 = [{"run_duration_ms": 60000}]  # 60s = 1min
        minutes, usd, _ = S.compute_cost(runs1)
        assert minutes == pytest.approx(1.0)
        assert usd == pytest.approx(0.008)
        # 由 start/end 推算（2 分钟）
        runs2 = [{"run_started_at": "2026-01-01T00:00:00Z",
                  "updated_at": "2026-01-01T00:02:00Z"}]
        minutes2, _, _ = S.compute_cost(runs2)
        assert minutes2 == pytest.approx(2.0)


# ============================================================
# routing_metrics —— claim 精度聚合 / 降权 / 回填幂等
# ============================================================
class TestRoutingMetrics:
    def test_aggregate_metrics_precision(self, monkeypatch, tmp_path):
        """precision = reproduced / total；NOT_REPRODUCED 计入 refuted，INCONCLUSIVE 不计。"""
        claims = [{"reviewer_model": "gpt5", "claims": [{"id": "C1"}, {"id": "C2"}, {"id": "C3"}]}]
        reproductions = [
            {"claim_id": "C1", "verdict": "REPRODUCED"},
            {"claim_id": "C2", "verdict": "NOT_REPRODUCED"},
            {"claim_id": "C3", "verdict": "INCONCLUSIVE"},
        ]
        # 指向空 ROUTING.yaml → 走 (review/accept/unknown) 回落
        empty = tmp_path / "ROUTING.yaml"
        empty.write_text("routes: []\n")
        monkeypatch.setattr(RM, "ROUTING_PATH", str(empty))
        m = RM.aggregate_metrics(claims, reproductions)
        key = "review/accept/unknown/gpt5"
        assert key in m
        e = m[key]
        assert e["claims_total"] == 3
        assert e["claims_reproduced"] == 1
        assert e["claims_refuted"] == 1
        assert e["precision"] == pytest.approx(1 / 3)

    def test_compute_demotion_insufficient_and_below_floor(self, tmp_path):
        policy = tmp_path / "policy.yml"
        policy.write_text("review:\n  min_samples_for_demotion: 10\n  precision_floor: 0.5\n")
        RM.POLICY_PATH = str(policy)
        # 样本不足 → None（打印 INSUFFICIENT_SAMPLES）
        assert RM.compute_demotion({"claims_total": 5, "precision": 0.1}, {"review": {"min_samples_for_demotion": 10, "precision_floor": 0.5}}) is None
        # 样本足、精度低于 floor → 降权建议
        dem = RM.compute_demotion(
            {"claims_total": 15, "precision": 0.3, "provider": "P", "model": "M",
             "domain": "review", "action": "accept"},
            {"review": {"min_samples_for_demotion": 10, "precision_floor": 0.5}})
        assert dem is not None and dem["suggested_action"] == "demote"
        assert "M" in dem["model"]
        # 样本足、精度达标 → None
        assert RM.compute_demotion(
            {"claims_total": 15, "precision": 0.7},
            {"review": {"min_samples_for_demotion": 10, "precision_floor": 0.5}}) is None

    def test_backfill_routing_metrics_idempotent(self, tmp_path):
        routing = tmp_path / "ROUTING.yaml"
        routing.write_text(
            "routes:\n"
            "  - domain: review\n"
            "    action: accept\n"
            "    provider: P\n"
            "    model: M\n"
            "    metrics:\n"
            "      claims_total: 0\n"
            "      claims_reproduced: 0\n"
            "      claims_refuted: 0\n"
            "      precision: 0.0\n"
        )
        metrics = {"review/accept/P/M": {"claims_total": 12, "claims_reproduced": 9,
                                         "claims_refuted": 3, "precision": 0.75}}
        RM.backfill_routing_metrics(metrics, str(routing))
        first = routing.read_text()
        assert "claims_total: 12" in first and "precision: 0.75" in first
        # 第二次回填 → 逐字相同（幂等）
        RM.backfill_routing_metrics(metrics, str(routing))
        assert routing.read_text() == first

    def test_apply_demotion_adds_status(self, tmp_path):
        routing = tmp_path / "ROUTING.yaml"
        routing.write_text(
            "routes:\n"
            "  - domain: review\n"
            "    action: accept\n"
            "    provider: P\n"
            "    model: M\n"
        )
        dem = {"provider": "P", "model": "M", "current_route": "review/accept/P/M",
               "reason": "low precision", "suggested_action": "demote"}
        RM.apply_demotion(dem, str(routing))
        text = routing.read_text()
        assert "status: demoted" in text
        # 幂等：再调一次不重复添加
        RM.apply_demotion(dem, str(routing))
        assert routing.read_text().count("status: demoted") == 1

    def test_replay_from_evidence(self, tmp_path):
        (tmp_path / "claim-1.json").write_text(json.dumps(
            {"reviewer_model": "gpt5", "claims": [{"id": "C1"}, {"id": "C2"}]}))
        (tmp_path / "repro-1.json").write_text(json.dumps(
            {"claim_id": "C1", "verdict": "REPRODUCED"}))
        monkeypatch_cls = pytest.MonkeyPatch()
        monkeypatch_cls.setattr(RM, "ROUTING_PATH", str(tmp_path / "noop.yaml"))
        try:
            m = RM.replay_from_evidence(str(tmp_path))
        finally:
            monkeypatch_cls.undo()
        key = "review/accept/unknown/gpt5"
        assert key in m
        assert m[key]["claims_total"] == 2 and m[key]["claims_reproduced"] == 1


# ============================================================
# claim_intake —— wave-level gate #2 防御（未复现 claim 不可被领）
# ============================================================
class TestClaimIntake:
    def test_is_claim_pickable_by_impl_blocks_unconfirmed(self):
        """未复现（state=unconfirmed）的 claim F-card 不可被 impl 领取。"""
        assert CI.is_claim_pickable_by_impl({"state": "unconfirmed"}) is False
        assert CI.is_claim_pickable_by_impl({"state": "ready"}) is True
        assert CI.is_claim_pickable_by_impl({}) is True  # 无 state 字段交由其它校验
        assert CI.is_claim_pickable_by_impl(None) is True  # 非 dict 不在此拦
        assert CI.is_claim_pickable_by_impl("notadict") is True

    def test_build_fcard_severity_to_tier_and_unconfirmed_state(self):
        claim = {"id": "CL-001", "severity": "high", "path": "src/x.py", "claim": "msg"}
        rd = {"review_id": "r1", "reviewer_model": "m", "head_sha": "abc"}
        fcard = CI._build_fcard(claim, rd)
        assert fcard["state"] == "unconfirmed"
        assert fcard["tier"] == "critical"  # high → critical
        assert fcard["lens"] == "review-claim"
        assert fcard["claim_id"] == "CL-001"
        assert fcard["paths"] == ["src/x.py"]
        assert fcard["evidence"][0]["tool"] == "reviewer"
        assert fcard["reviewer_model"] == "m"

    def test_assert_reproduced_raises_on_unconfirmed(self):
        with pytest.raises(CI.CLAIM_NOT_REPRODUCED, match="wave-level gate #2"):
            CI.assert_reproduced({"state": "unconfirmed", "id": "X", "claim_id": "Y"})
        # 已复现（非 unconfirmed）不抛
        CI.assert_reproduced({"state": "ready"})


# ============================================================
# drift_check —— 稳定指纹（顺序无关、确定性）
# ============================================================
class TestDriftCheck:
    def test_fingerprint_stable_and_order_independent(self):
        a = [{"file": "main.json", "diffs": ["x"]}, {"file": "protection.json", "diffs": ["y"]}]
        b = list(reversed(a))
        fp1 = DC.fingerprint(a)
        fp2 = DC.fingerprint(b)
        assert fp1 == fp2, "指纹必须顺序无关（同一组 drift 任意检出顺序同指纹）"
        assert len(fp1) == 8, "指纹为 sha256 前 8 位"
        # 不同输入 → 不同指纹
        c = [{"file": "main.json", "diffs": ["different"]}]
        assert DC.fingerprint(c) != fp1
