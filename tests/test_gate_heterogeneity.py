"""tests/test_gate_heterogeneity.py — R11-2 异构门禁测试。

覆盖 acceptance：
  - 同 provider 同 model → 红
  - 同 provider 异 model → 红（provider 必须也不同）
  - 异 provider → 绿
  - 注释声称异构但实际同构 → 红
  - review/accept 与 review/reproduce 同构 → 红
  - VERDICT 自证（verifier_model == impl_model）→ 红
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
if GATES not in sys.path:
    sys.path.insert(0, GATES)

import gate_heterogeneity as gh  # noqa: E402


def _make_routing(tmp_path, impl, verify, review_accept=None, review_repro=None,
                  comment_hetero=False):
    """写一个 ROUTING.yaml 到 tmp_path。impl/verify/review_accept/review_repro 是 (provider, model) 元组。"""
    providers = {}
    for pair in [impl, verify, review_accept, review_repro]:
        if pair is None:
            continue
        p = pair[0]
        if p and p not in providers:
            providers[p] = {"base_url": f"https://{p}.example.com/v1", "api_key_env": f"{p.upper()}_KEY"}

    lines = [
        "schema: 1",
        "providers:",
    ]
    for name, cfg in providers.items():
        lines.append(f"  {name}:")
        lines.append(f"    base_url: \"{cfg['base_url']}\"")
        lines.append(f"    api_key_env: \"{cfg['api_key_env']}\"")
    lines.append("default:")
    lines.append(f"  provider: {impl[0]}")
    lines.append(f"  model: {impl[1]}")
    lines.append("routes:")
    if comment_hetero:
        lines.append("  # 验证工专用池：必须与实现工的 provider 不同（异构验证的机器保证）")
    lines.append("  - domain: impl")
    lines.append("    action: '*'")
    lines.append("    tier: standard")
    lines.append(f"    provider: {impl[0]}")
    lines.append(f"    model: {impl[1]}")
    lines.append("  - domain: verify")
    lines.append("    action: '*'")
    lines.append("    tier: '*'")
    lines.append(f"    provider: {verify[0]}")
    lines.append(f"    model: {verify[1]}")
    if review_accept:
        lines.append("  - domain: review")
        lines.append("    action: accept")
        lines.append("    tier: '*'")
        lines.append(f"    provider: {review_accept[0]}")
        lines.append(f"    model: {review_accept[1]}")
    if review_repro:
        lines.append("  - domain: review")
        lines.append("    action: reproduce")
        lines.append("    tier: '*'")
        lines.append(f"    provider: {review_repro[0]}")
        lines.append(f"    model: {review_repro[1]}")
    (tmp_path / "ROUTING.yaml").write_text("\n".join(lines) + "\n")


def _run_gate(tmp_path):
    p = subprocess.run(
        [sys.executable, os.path.join(GATES, "gate_heterogeneity.py")],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    return p.returncode, p.stdout, p.stderr


def test_same_provider_same_model_red(tmp_path):
    """impl 和 verify 同 provider 同 model → 红。"""
    _make_routing(tmp_path, ("qwen", "qwen3-max"), ("qwen", "qwen3-max"))
    code, out, err = _run_gate(tmp_path)
    assert code == 1
    assert "SAME_PROVIDER" in out
    assert "SAME_MODEL" in out


def test_same_provider_diff_model_red(tmp_path):
    """impl 和 verify 同 provider 异 model → 红（provider 必须也不同）。"""
    _make_routing(tmp_path, ("qwen", "qwen3-max"), ("qwen", "qwen-turbo"))
    code, out, err = _run_gate(tmp_path)
    assert code == 1
    assert "SAME_PROVIDER" in out
    assert "SAME_MODEL" not in out  # model 不同，但 provider 相同


def test_diff_provider_diff_model_green(tmp_path):
    """impl 和 verify 异 provider 异 model → 绿。"""
    _make_routing(
        tmp_path, ("qwen", "qwen3-max"), ("deepseek", "deepseek-chat"),
        review_accept=("strongest", "gpt-5"),
        review_repro=("qwen", "qwen3-max"),
    )
    code, out, err = _run_gate(tmp_path)
    assert code == 0, f"expected 0, got {code}: {out} {err}"
    assert "OK" in out


def test_comment_claims_hetero_but_same_red(tmp_path):
    """注释声称异构但实际同 provider → 红（COMMENT_CONTRADICTS_CONFIG）。"""
    _make_routing(
        tmp_path, ("qwen", "qwen3-max"), ("qwen", "qwen-turbo"),
        comment_hetero=True,
    )
    code, out, err = _run_gate(tmp_path)
    assert code == 1
    assert "COMMENT_CONTRADICTS_CONFIG" in out or "SAME_PROVIDER" in out


def test_review_accept_same_as_reproduce_red(tmp_path):
    """review/accept 与 review/reproduce 同构 → 红。"""
    _make_routing(
        tmp_path, ("qwen", "qwen3-max"), ("deepseek", "deepseek-chat"),
        review_accept=("strongest", "gpt-5"),
        review_repro=("strongest", "gpt-5"),  # same as accept
    )
    code, out, err = _run_gate(tmp_path)
    assert code == 1
    assert "review/accept" in out and "review/reproduce" in out


def test_unit_check_route_pair_pass():
    """单元测试：两条 route 异构 → 无 violation。"""
    route_a = {"provider": "qwen", "model": "qwen3-max"}
    route_b = {"provider": "deepseek", "model": "deepseek-chat"}
    v = gh.check_route_pair("a", route_a, "b", route_b, {}, {})
    assert v == []


def test_unit_check_route_pair_same_model():
    """单元测试：同 model → SAME_MODEL violation。"""
    route_a = {"provider": "qwen", "model": "gpt-5"}
    route_b = {"provider": "deepseek", "model": "gpt-5"}
    v = gh.check_route_pair("a", route_a, "b", route_b, {}, {})
    assert any("SAME_MODEL" in x for x in v)


def test_unit_check_verdict_evidence_self_verify():
    """VERDICT 中 verifier_model == impl_model → 红。"""
    verdict = {"verifier_model": "qwen3-max", "session_id": "s1", "impl_session_id": "s2"}
    v = gh.check_verdict_evidence(verdict, "qwen3-max")
    assert any("VERDICT_SELF_VERIFY" in x for x in v)


def test_unit_check_verdict_evidence_same_session():
    """VERDICT 中 session_id == impl_session_id → 红。"""
    verdict = {
        "verifier_model": "deepseek-chat",
        "session_id": "s1",
        "impl_session_id": "s1",
    }
    v = gh.check_verdict_evidence(verdict, "qwen3-max")
    assert any("VERDICT_SAME_SESSION" in x for x in v)


def test_unit_check_verdict_evidence_pass():
    """VERDICT 异构 → 无 violation。"""
    verdict = {
        "verifier_model": "deepseek-chat",
        "session_id": "s1",
        "impl_session_id": "s2",
    }
    v = gh.check_verdict_evidence(verdict, "qwen3-max")
    assert v == []


def test_actual_routing_yaml_green():
    """用仓库实际的 ROUTING.yaml 跑一次，应通过。"""
    code, out, err = _run_gate_path(REPO_ROOT)
    assert code == 0, f"actual ROUTING.yaml should pass: {out} {err}"


def _run_gate_path(path):
    p = subprocess.run(
        [sys.executable, os.path.join(GATES, "gate_heterogeneity.py")],
        cwd=str(path), capture_output=True, text=True,
    )
    return p.returncode, p.stdout, p.stderr
