#!/usr/bin/env python3
"""seam_a/test_router.py — 接缝 A 路由器本地验收（mock 证明）。

不依赖任何真实模型 API。起一个 mock provider（返回固定 chat completion），
起 router，用不同 X-Loop-* 头打过去，断言：
  1. router 200 返回 mock 的应答；
  2. mock 收到的 body.model == ROUTING.yaml 解析出的真实模型名；
  3. 最具体匹配优先、default 兜底均正确；
  4. router 源码不 import litellm（OPC-v4 §1.3 红线）。

运行：  python seam_a/test_router.py
"""
import json, os, sys, threading, tempfile, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import router  # noqa: E402

# ---- 1. 源码不 import litellm（红线；注释里提及「禁止 litellm」是允许的）----
import ast
src = open(os.path.join(HERE, "router.py")).read()
_litellm_imports = [n for n in ast.walk(ast.parse(src))
                    if (isinstance(n, ast.Import) and any(a.name == "litellm" for a in n.names))
                    or (isinstance(n, ast.ImportFrom) and n.module == "litellm")]
assert not _litellm_imports, "RED LINE: litellm import detected"
print("[1] OK: router 源码无 litellm import（仅注释提及禁令）")

# ---- 2. 构造临时 ROUTING.yaml 指向 mock provider ----
CFG = {
    "schema": 1,
    "providers": {
        "mock": {"base_url": "http://127.0.0.1:%d" % 0, "api_key_env": "MOCK_KEY"},
        "strong": {"base_url": "http://127.0.0.1:%d" % 0, "api_key_env": "MOCK_KEY"},
    },
    "default": {"provider": "mock", "model": "default-model"},
    "routes": [
        {"domain": "plan", "action": "propose", "tier": "critical",
         "provider": "strong", "model": "gpt-5"},
        {"domain": "verify", "action": "*", "tier": "*",
         "provider": "mock", "model": "verify-model"},
        {"domain": "impl", "action": "*", "tier": "trivial",
         "provider": "mock", "model": "cheap-model"},
    ],
}

# ---- 3. 单元测 resolve()（无网络）----
router.CFG = CFG
assert router.resolve("plan", "propose", "critical") == ("strong", "gpt-5"), "exact match"
assert router.resolve("verify", "anything", "critical") == ("mock", "verify-model"), "wildcard"
assert router.resolve("impl", "chat", "trivial") == ("mock", "cheap-model"), "tier trivial"
# impl/standard 无匹配 → default
assert router.resolve("impl", "chat", "standard") == ("mock", "default-model"), "default fallback"
# 最具体优先：plan/propose/critical 命中 3 分，不应被 plan/*/* 的低分项抢（此处无冲突，仅证分数）
print("[2] OK: resolve() exact/wildcard/default 全部正确")

# ---- 4. 端到端：mock provider + router 真实 HTTP ----
received = {}


class MockProvider(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n))
        received["model"] = body.get("model")
        received["auth"] = self.headers.get("Authorization", "")
        resp = {"id": "chatcmpl-mock", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "routed:" + str(body.get("model"))}}]}
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _Dummy(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass


def free_port():
    s = ThreadingHTTPServer(("127.0.0.1", 0), _Dummy)
    p = s.server_address[1]
    s.server_close()
    return p


mp_port = free_port()
CFG["providers"]["mock"]["base_url"] = "http://127.0.0.1:%d" % mp_port
CFG["providers"]["strong"]["base_url"] = "http://127.0.0.1:%d" % mp_port
os.environ["MOCK_KEY"] = "test-key"
mp = ThreadingHTTPServer(("127.0.0.1", mp_port), MockProvider)
threading.Thread(target=mp.serve_forever, daemon=True).start()

rport = free_port()
os.environ["LOOP_ROUTING_PORT"] = str(rport)
rs = ThreadingHTTPServer(("127.0.0.1", rport), router.H)
threading.Thread(target=rs.serve_forever, daemon=True).start()


def post(headers, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request("http://127.0.0.1:%d/v1/chat/completions" % rport,
                                 data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    r = urllib.request.urlopen(req, timeout=5)
    return r.status, json.loads(r.read())


# healthz
assert urllib.request.urlopen("http://127.0.0.1:%d/healthz" % rport, timeout=5).status == 200
print("[3] OK: GET /healthz 200")

# plan/propose/critical → gpt-5
st, resp = post({"X-Loop-Domain": "plan", "X-Loop-Action": "propose", "X-Loop-Tier": "critical"},
                {"model": "whatever", "messages": [{"role": "user", "content": "hi"}]})
assert st == 200, st
assert received["model"] == "gpt-5", received
assert received["auth"] == "Bearer test-key", received
assert resp["choices"][0]["message"]["content"] == "routed:gpt-5", resp
print("[4] OK: plan/propose/critical → gpt-5，model 已改写、Authorization 已注入")

# verify/*/* → verify-model
st, resp = post({"X-Loop-Domain": "verify", "X-Loop-Action": "x", "X-Loop-Tier": "trivial"},
                {"model": "whatever", "messages": []})
assert received["model"] == "verify-model", received
print("[5] OK: verify/*/* → verify-model（通配匹配）")

# 缺省头 → default-model
st, resp = post({}, {"model": "whatever", "messages": []})
assert received["model"] == "default-model", received
print("[6] OK: 无 X-Loop-* 头 → default-model（default 兜底）")

# /v1/models 列表
ml = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % rport, timeout=5).read())
ids = {m["id"] for m in ml["data"]}
assert ids == {"gpt-5", "verify-model", "cheap-model", "default-model"}, ids
print("[7] OK: GET /v1/models 列出全部路由模型")

mp.shutdown(); rs.shutdown()
print("\nALL PASS — 接缝 A 路由器本地 mock 调通（OpenAI 兼容、无 LiteLLM）。")
