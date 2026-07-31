#!/usr/bin/env python3
"""seam_a/router.py — 接缝 A 模型路由器（OpenAI 兼容，严禁 LiteLLM 进程）。

契约（OPC-v4 §2.1 接缝 A、§1.3 拒绝 LiteLLM）：
  - 暴露 OpenAI 兼容 base_url（POST /v1/chat/completions、GET /v1/models、GET /healthz）。
  - 读 ROUTING.yaml（domain×action×tier→provider/model），按请求头
    X-Loop-Domain / X-Loop-Action / X-Loop-Tier 解析路由（缺省 default/chat/standard）。
  - 把请求 body.model 改写为解析出的真实模型名，转发到 provider.base_url+/chat/completions。
  - Authorization 取 provider.api_key_env 指向的环境变量；本文件绝不出现明文 key。
  - 仅用 Python 标准库 + 可选 PyYAML；不 import litellm，不拉起 LiteLLM 进程。

运行：  python seam_a/router.py
环境：  LOOP_ROUTING_PORT（默认 8787）、LOOP_ROUTING_CONFIG（默认 ../ROUTING.yaml）、
        LOOP_ROUTER_TIMEOUT（默认 120）、各 provider 的 api_key_env。
"""
import json, os, sys, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CFG = None  # 路由表，main() / 测试注入

# R12-7: review 域指标感知降权读 policy.yml（precision_floor / min_samples_for_demotion）
_POLICY_PATH = os.environ.get(
    "LOOP_POLICY_PATH",
    os.path.join(os.path.dirname(__file__), "..", "policy.yml"),
)


def _load(path):
    with open(path) as f:
        text = f.read()
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        return json.loads(text)  # ROUTING.yaml 也接受 JSON 写法


def _key(env):
    return os.environ.get(env, "") if env else ""


def _load_policy():
    """读 policy.yml（review.precision_floor / review.min_samples_for_demotion）。

    失败回落空 dict——此时降权判定用默认阈值（floor 0.5 / min_samples 10）。
    与 _load 同风格：标准库 + 可选 PyYAML，绝不引入 litellm。
    """
    try:
        import yaml
        with open(_POLICY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve(domain, action, tier):
    """最具体匹配优先；无命中走 default。返回 (provider, model)。"""
    best, best_score = None, -1
    for r in CFG.get("routes", []):
        if not (r["domain"] in ("*", domain) and r["action"] in ("*", action)
                and r["tier"] in ("*", tier)):
            continue
        score = sum(1 for k in ("domain", "action", "tier") if r[k] != "*")
        if score > best_score:
            best, best_score = r, score
    if best is None:
        d = CFG.get("default", {})
        return d.get("provider"), d.get("model")
    return best["provider"], best["model"]


# ============================================================
# R12-7: review 域指标感知降权（纯增量，不破坏既有 resolve 行为）
# ============================================================
def _route_metrics_for(provider, model, domain, action):
    """从 CFG.routes 找匹配 (domain, action, provider, model) 的 route，返回其 metrics dict。

    匹配规则与 resolve 同源（action 任一方为 "*" 即视为匹配）。无匹配返回 {}。
    """
    for r in CFG.get("routes", []):
        if not isinstance(r, dict):
            continue
        ra = r.get("action", "*")
        if r.get("provider") != provider or r.get("model") != model:
            continue
        if r.get("domain") != domain:
            continue
        if not (ra == action or ra == "*" or action == "*"):
            continue
        m = r.get("metrics", {}) or {}
        return m if isinstance(m, dict) else {}
    return {}


def _review_min_samples(policy=None):
    """读 policy.review.min_samples_for_demotion（默认 10）。"""
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    if not isinstance(review, dict):
        review = {}
    try:
        return int(review.get("min_samples_for_demotion", 10))
    except (TypeError, ValueError):
        return 10


def _review_precision_floor(policy=None):
    """读 policy.review.precision_floor（默认 0.5）。"""
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    if not isinstance(review, dict):
        review = {}
    try:
        return float(review.get("precision_floor", 0.5))
    except (TypeError, ValueError):
        return 0.5


def resolve_with_demotion_check(domain, action, tier, policy=None):
    """带指标感知的解析：review 域查 metrics，精度过低则回落 default provider。

    非 review 域：行为与 resolve() 完全一致（纯增量，不破坏既有路由）。
    review 域：读 route 的 metrics；
      - claims_total < min_samples → 打印 INSUFFICIENT_SAMPLES，保留原路由（不降权）；
      - claims_total >= min_samples 且 precision < floor → 记降权警告并回落到
        default provider（R12-7：模型不确定性不能卡合并线，但可降权到默认档）。
    """
    provider, model = resolve(domain, action, tier)
    if domain != "review" or not provider:
        return provider, model
    metrics = _route_metrics_for(provider, model, domain, action)
    try:
        total = int(metrics.get("claims_total", 0) or 0)
    except (TypeError, ValueError):
        total = 0
    min_samples = _review_min_samples(policy)
    if total < min_samples:
        print("INSUFFICIENT_SAMPLES")
        return provider, model
    try:
        precision = float(metrics.get("precision", 0.0) or 0.0)
    except (TypeError, ValueError):
        precision = 0.0
    floor = _review_precision_floor(policy)
    if precision < floor:
        sys.stderr.write(
            f"DEMOTION_WARNING: review model {model} (provider={provider}) "
            f"precision {precision} < floor {floor} over {total} samples; "
            f"falling back to default provider\n"
        )
        d = CFG.get("default", {}) or {}
        return d.get("provider"), d.get("model")
    return provider, model


def _forward(provider, body):
    prov = CFG["providers"][provider]
    url = prov["base_url"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    k = _key(prov.get("api_key_env", ""))
    if k:
        req.add_header("Authorization", "Bearer " + k)
    to = int(os.environ.get("LOOP_ROUTER_TIMEOUT", "120"))
    try:
        r = urllib.request.urlopen(req, timeout=to)
        return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "application/json")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/healthz", "/"):
            self._send(200, b'{"status":"ok"}')
        elif self.path == "/v1/models":
            ms = sorted({r.get("model") for r in CFG.get("routes", [])}
                        | {CFG.get("default", {}).get("model")})
            self._send(200, json.dumps({"data": [{"id": m} for m in ms if m]}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, b'{"error":"not found"}')
            return
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        domain = self.headers.get("X-Loop-Domain", "default")
        action = self.headers.get("X-Loop-Action", "chat")
        tier = self.headers.get("X-Loop-Tier", "standard")
        # R12-7: review 域走指标感知解析（其它域与原 resolve 行为一致）
        prov, model = resolve_with_demotion_check(domain, action, tier)
        if not prov or prov not in CFG.get("providers", {}):
            self._send(502, b'{"error":"no route"}')
            return
        try:
            payload = json.loads(body)
            payload["model"] = model or payload.get("model")
            body = json.dumps(payload).encode()
        except Exception:
            pass  # 非 JSON 原样透传
        code, data, ctype = _forward(prov, body)
        self._send(code, data, ctype)


def main():
    global CFG
    cfg = os.environ.get("LOOP_ROUTING_CONFIG",
                         os.path.join(os.path.dirname(__file__), "..", "ROUTING.yaml"))
    CFG = _load(cfg)
    port = int(os.environ.get("LOOP_ROUTING_PORT", "8787"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    sys.stderr.write(f"seam_a router on :{port} (cfg={cfg})\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
