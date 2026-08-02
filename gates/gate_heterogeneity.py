#!/usr/bin/env python3
"""gate_heterogeneity — CI 强制 impl 与 verify 模型异构（R11-2）。

把「独立验证」从文档承诺变成机器强制（CHARTER G3/G4/N12）。

检查项：
  1. ROUTING.yaml 中 impl route 与 verify route 的 provider **且** model 均不相同。
  2. ROUTING.yaml 中 review/accept 与 review/reproduce 的 provider **且** model 均不相同
     （强模型不得自己复现自己的 claim）。
  3. 若 ROUTING.yaml 的注释声称异构而实际配置同构 → 判红（抓谎称）。
  4. 若 PR 上有 VERDICT 评论，校验 verdict.verifier_model != impl route 的 model，
     且 session id 不同（同会话自证一律判失败）。

退出码：
  0  全部异构校验通过
  1  存在同构违规
"""
import json
import os
import re
import subprocess
import sys

ROUTING_PATH = os.environ.get("ROUTING_PATH", "ROUTING.yaml")
POLICY_PATH = os.environ.get("LOOP_POLICY", "policy.yml")


# ── W2-8 身份外置：异构身份读 leases/<card>.json（agent 只读），绝不读 LOOP_MODEL env ──
def _leases_dir():
    """leases 目录（基于 LOOP_STATE / LOOP_ROOT 的 loop-state 布局，与 cas.LOOP_STATE_DIRS 对齐）。

    返回值含字面 `leases/` 路径段。
    """
    base = os.environ.get("LOOP_STATE")
    if not base:
        lr = os.environ.get("LOOP_ROOT", "")
        base = os.path.join(lr, ".loop") if lr else ".loop"
    return os.path.join(base, "leases")


def load_lease(card_id):
    """读租约 leases/<card>.json —— 身份唯一事实来源（AC-3/AC-5，读租约而非 env）。

    返回 {model, family, vendor, ...} 或 None。绝不 fallback 到任何 LOOP_MODEL 环境变量。
    """
    if not card_id:
        return None
    p = os.path.join(_leases_dir(), f"{card_id}.json")
    if not os.path.exists(p):
        # 租约缺失 = 真实结果（fail-closed），由调用方决定兜底，不当作绿
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def card_id_from_ref(ref=None):
    """从 PR 分支（如 agent/C-0NN / refs/heads/C-007-feature）推导卡片 ID。找不到返回 None。

    卡片 ID 以 `[CVF]-NNN` 形式出现，其后跟随分支分隔符（/ . _ -）或字符串结束。
    """
    ref = ref or os.environ.get("GITHUB_REF", "")
    m = re.search(r'(?:refs/heads/)?(?:agent/)?([CVF]-\d{3})(?:[/._-]|$)', ref)
    return m.group(1) if m else None


def _load_policy_models():
    """从 policy.yml 的 models: 段读 model id → {family, vendor}，用于 family/vendor 级比较。"""
    try:
        d = load_yaml(POLICY_PATH)
        m = d.get("models") or {}
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def load_yaml(path):
    try:
        import yaml
        # 产品仓场景：ROUTING.yaml 在 loop 侧（LOOP_ROOT），不在产品仓
        if not os.path.exists(path):
            loop_root = os.environ.get("LOOP_ROOT", "")
            if loop_root:
                alt = os.path.join(loop_root, path)
                if os.path.exists(alt):
                    path = alt
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def find_route(routes, domain, action="*", tier="*"):
    """在 routes 列表中找最具体的匹配项。

    匹配规则：route 的字段值 == 请求值，或任一方为 "*"（通配）。
    特异性 = 非通配字段数。同分取靠前者。
    """
    best = None
    best_spec = -1
    for r in routes or []:
        if r.get("domain") != domain:
            continue
        ra = r.get("action", "*")
        rt = r.get("tier", "*")
        # 匹配条件：任一方为 "*" 或两者相等
        if not (ra == action or ra == "*" or action == "*"):
            continue
        if not (rt == tier or rt == "*" or tier == "*"):
            continue
        spec = sum(1 for k in ("action", "tier") if r.get(k, "*") != "*")
        if spec > best_spec:
            best = r
            best_spec = spec
    return best


def resolve_provider_model(route, providers, default):
    """解析 route 的 (provider, model)。"""
    if not route:
        return None, None
    provider = route.get("provider", default.get("provider"))
    model = route.get("model", default.get("model"))
    return provider, model


def check_route_pair(name_a, route_a, name_b, route_b, providers, default):
    """校验两条 route 的 provider 和 model 均不同。返回 violations 列表。"""
    violations = []
    pa, ma = resolve_provider_model(route_a, providers, default)
    pb, mb = resolve_provider_model(route_b, providers, default)

    if route_a is None:
        violations.append(f"ROUTE_NOT_FOUND: {name_a}")
    if route_b is None:
        violations.append(f"ROUTE_NOT_FOUND: {name_b}")
    if route_a is None or route_b is None:
        return violations

    if pa == pb:
        violations.append(
            f"SAME_PROVIDER: {name_a}({pa}) == {name_b}({pb}) — "
            f"异构验证要求 provider 不同"
        )
    if ma == mb:
        violations.append(
            f"SAME_MODEL: {name_a}({ma}) == {name_b}({mb}) — "
            f"异构验证要求 model 不同"
        )
    return violations


def check_comment_consistency(routing_text, pairs):
    """扫描 ROUTING.yaml 注释中声称异构但实际同构的情况。

    pairs: [(label_a, provider_a, model_a, label_b, provider_b, model_b), ...]
    """
    violations = []
    # 匹配注释中「异构」「不同 provider」「不同模型」「verifier 专用」等声明
    hetero_claims = re.findall(
        r"#.*?(异构|不同\s*provider|不同\s*模型|verifier.*专用|verify.*不同|独立验证)",
        routing_text,
    )
    if not hetero_claims:
        return violations

    for label_a, pa, ma, label_b, pb, mb in pairs:
        if pa == pb or ma == mb:
            violations.append(
                f"COMMENT_CONTRADICTS_CONFIG: 注释声称异构，"
                f"但 {label_a}({pa}/{ma}) 与 {label_b}({pb}/{mb}) 实际同构"
            )
    return violations


# ── VERDICT evidence 校验 ──
def gh_json(*args):
    env = dict(os.environ)
    token = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
    if token:
        env["GH_TOKEN"] = token
    p = subprocess.run(["gh", *args], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def get_pr_number():
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
    if len(parts) >= 3 and parts[1] == "pull":
        return parts[2]
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if event_path:
        try:
            ev = json.loads(open(event_path).read())
            if "pull_request" in ev:
                return str(ev["pull_request"]["number"])
        except Exception:
            pass
    return None


def find_verdict_in_comments(pr_num):
    """搜索 PR 评论中的 ```json verdict 块。"""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or not pr_num:
        return None
    comments = gh_json(
        "api", f"repos/{repo}/issues/{pr_num}/comments", "--paginate"
    )
    if not comments or not isinstance(comments, list):
        return None
    marker = "```json verdict"
    for c in reversed(comments):
        body = c.get("body", "")
        if marker not in body:
            continue
        seg = body.split(marker, 1)[1].split("```", 1)[0]
        try:
            return json.loads(seg)
        except json.JSONDecodeError:
            continue
    return None


def get_impl_model_from_routing(routing_data):
    """从 ROUTING.yaml 取 impl/standard route 的 model。"""
    routes = routing_data.get("routes", [])
    providers = routing_data.get("providers", {})
    default = routing_data.get("default", {})
    impl_route = find_route(routes, "impl", action="*", tier="standard")
    _, model = resolve_provider_model(impl_route, providers, default)
    return model


def check_verdict_evidence(verdict, impl_identity, models_map=None):
    """校验 VERDICT 中 verifier 身份与 impl 身份异构。

    impl 身份来自 leases/<card>.json（租约，非 LOOP_MODEL env）；比较在
    model / family / vendor 三个层级上做（家族、厂商级同构同样判红）。
    """
    violations = []
    if not verdict:
        return violations
    verifier_model = verdict.get("verifier_model") or verdict.get("model")
    session_id = verdict.get("session_id") or verdict.get("blind_phase_commit")
    impl_session = verdict.get("impl_session_id")
    # impl_identity 既可以是租约 dict（{model,family,vendor}），也可以是裸 model 字符串
    if isinstance(impl_identity, str):
        impl_model, impl_family, impl_vendor = impl_identity, None, None
    else:
        impl_id = impl_identity or {}
        impl_model = impl_id.get("model")
        impl_family = impl_id.get("family")
        impl_vendor = impl_id.get("vendor")
    models_map = models_map or {}

    if verifier_model and impl_model and verifier_model == impl_model:
        violations.append(
            f"VERDICT_SELF_VERIFY: verifier_model({verifier_model}) == "
            f"impl_model({impl_model}) — 同模型自证"
        )
    # family/vendor 级：即便 model 字符串不同，同族或同厂商也判定同构（读租约）
    vmeta = models_map.get(verifier_model) or {}
    vfam, vvend = vmeta.get("family"), vmeta.get("vendor")
    if impl_family and vfam and impl_family == vfam:
        violations.append(
            f"SAME_FAMILY: verifier_model({verifier_model}) family({vfam}) == "
            f"impl family({impl_family}) — 同家族验证，违反异构"
        )
    if impl_vendor and vvend and impl_vendor == vvend:
        violations.append(
            f"SAME_VENDOR: verifier_model({verifier_model}) vendor({vvend}) == "
            f"impl vendor({impl_vendor}) — 同厂商验证，违反异构"
        )
    if session_id and impl_session and session_id == impl_session:
        violations.append(
            f"VERDICT_SAME_SESSION: session_id 相同 — 同会话自证"
        )
    return violations


def main():
    routing_path = ROUTING_PATH
    # 产品仓场景：ROUTING.yaml 在 loop 侧（LOOP_ROOT）
    if not os.path.exists(routing_path):
        loop_root = os.environ.get("LOOP_ROOT", "")
        if loop_root:
            alt = os.path.join(loop_root, routing_path)
            if os.path.exists(alt):
                routing_path = alt
    routing_data = load_yaml(routing_path)
    if not routing_data:
        print(f"FAIL: cannot load ROUTING.yaml (tried {routing_path})")
        sys.exit(1)

    routes = routing_data.get("routes", [])
    providers = routing_data.get("providers", {})
    default = routing_data.get("default", {})

    # 1. impl vs verify 异构
    impl_route = find_route(routes, "impl", action="*", tier="standard")
    verify_route = find_route(routes, "verify", action="*", tier="*")
    violations = check_route_pair(
        "impl", impl_route, "verify", verify_route, providers, default
    )

    # 2. review/accept vs review/reproduce 异构
    accept_route = find_route(routes, "review", action="accept", tier="*")
    reproduce_route = find_route(routes, "review", action="reproduce", tier="*")
    violations += check_route_pair(
        "review/accept", accept_route,
        "review/reproduce", reproduce_route,
        providers, default,
    )

    # 3. 注释一致性检查
    try:
        with open(routing_path, encoding="utf-8") as f:
            routing_text = f.read()
        pa, ma = resolve_provider_model(impl_route, providers, default)
        pb, mb = resolve_provider_model(verify_route, providers, default)
        violations += check_comment_consistency(
            routing_text,
            [("impl", pa, ma, "verify", pb, mb)],
        )
    except Exception:
        pass

    # 4. VERDICT evidence 校验（PR 上下文）
    #    W2-8：impl 身份改读 leases/<card>.json（租约，非 LOOP_MODEL env，AC-5）。
    #    无租约时回退到 ROUTING impl route（保持既有门功能性）。
    pr_num = get_pr_number()
    if pr_num:
        verdict = find_verdict_in_comments(pr_num)
        if verdict:
            impl_identity = None
            card_id = card_id_from_ref()
            if card_id:
                lease = load_lease(card_id)
                if lease:
                    impl_identity = {
                        "model": lease.get("model"),
                        "family": lease.get("family"),
                        "vendor": lease.get("vendor"),
                        "source": f"leases/{card_id}.json",
                    }
                    print(f"  • verdict identity from lease leases/{card_id}.json: "
                          f"model={impl_identity['model']} family={impl_identity['family']} "
                          f"vendor={impl_identity['vendor']}")
            if impl_identity is None:
                # 无租约 → 回退 ROUTING impl route（不读 env，租约优先）
                brand = f"leases/{card_id}.json" if card_id else "N/A (no card)"
                impl_identity = {
                    "model": get_impl_model_from_routing(routing_data),
                    "family": None,
                    "vendor": None,
                    "source": "ROUTING (no lease)",
                }
                print(f"  • WARN: no lease for {brand}; fell back to ROUTING impl model")
            violations += check_verdict_evidence(
                verdict, impl_identity, _load_policy_models()
            )

    if violations:
        print("FAIL: HETEROGENEITY_VIOLATION")
        for v in violations:
            print(f"  - {v}")
        # 打印完整路由解析结果便于排查
        print("\nRoute resolution:")
        for label, route in [
            ("impl", impl_route), ("verify", verify_route),
            ("review/accept", accept_route), ("review/reproduce", reproduce_route),
        ]:
            p, m = resolve_provider_model(route, providers, default)
            print(f"  {label}: provider={p}, model={m}")
        sys.exit(1)

    # 打印解析结果
    pa, ma = resolve_provider_model(impl_route, providers, default)
    pb, mb = resolve_provider_model(verify_route, providers, default)
    print(
        f"OK heterogeneity: impl({pa}/{ma}) != verify({pb}/{mb}), "
        f"review routes also heterogeneous"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
