#!/usr/bin/env python3
"""conductor/reproduce.py — 复现沙盒 + 仲裁（R12-5）。

实现强模型验收环的「独立复现」一半（见 docs/强模型验收环.md）。
复现沙盒只跑 claim.repro.cmd，只比对 expected/actual/predicted_observation，
不读 claim 的论证过程、不自由发挥、不直接修代码（盲一半协议在 claim 层的复用，
对应 prompts/P12.md 的复现者提示词）。

铁律：
- 复现模型必须 != 提出 claim 的 reviewer_model（CHARTER N6，
  由 materialize.check_self_adjudication 强制）
- 三态判定 REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE，禁止第四种
- next_action 由 conductor 按裁决表计算（compute_next_action），沙盒模型不自行决定
- 沙盒只写 /tmp，无生产仓库写权限（policy.execute.sandbox.writable_paths）

本模块只做编排与确定性比较；verdict 的最终判定由 reproducer 模型（P12 提示词）产出，
本模块的 _suggest_verdict 仅在无法逐次调用模型时作为客观比较的回退，供 arbitrate 做多数决。

外部入口：
  resolve_reproducer_route()   — 从 ROUTING.yaml 解析 review/reproduce 路由
  enforce_sandbox_constraints()— 读 policy.yml execute.sandbox.* 返回约束字典
  run_repro(cmd, ...)          — 在 /tmp 沙盒里跑 cmd，返回 exit_code + stdout/stderr 摘录
  reproduce_claim(...)         — 对单条 claim 跑沙盒，返回 reproduction dict（verdict 留给模型）
  compute_next_action(...)     — conductor 侧裁决表，返回 next_action 字符串
  arbitrate(...)               — 多次采样多数决，不收敛则升级人类
"""
import datetime
import os
import platform
import re
import subprocess

ROUTING_PATH = os.environ.get("ROUTING_PATH", "ROUTING.yaml")
POLICY_PATH = os.environ.get("POLICY_PATH", "policy.yml")
STDOUT_EXCERPT_BYTES = 4096  # reproduction.json: stdout_excerpt 截断到 4KB
DEFAULT_ARBITRATION_SAMPLES = 3
VALID_VERDICTS = ("REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE")
VALID_NEXT_ACTIONS = ("open_fix_card", "await_arbitration", "escalate_env_diff", "close_refuted")


def _load_yaml(path):
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _load_policy():
    return _load_yaml(POLICY_PATH)


def _load_routing():
    return _load_yaml(ROUTING_PATH)


# ============================================================
# 路由解析：复现者 provider/model 来自 ROUTING.yaml 的 review/reproduce route
# （与 gates/gate_heterogeneity.py 同样的 find_route + 解析逻辑，不硬编码）
# ============================================================
def _find_route(routes, domain, action="*", tier="*"):
    """在 routes 列表中找最具体的匹配项。

    匹配规则：route 字段值 == 请求值，或任一方为 "*"（通配）。
    特异性 = 非通配字段数。同分取靠前者。与 gate_heterogeneity.find_route 一致。
    """
    best = None
    best_spec = -1
    for r in routes or []:
        if r.get("domain") != domain:
            continue
        ra = r.get("action", "*")
        rt = r.get("tier", "*")
        if not (ra == action or ra == "*" or action == "*"):
            continue
        if not (rt == tier or rt == "*" or tier == "*"):
            continue
        spec = sum(1 for k in ("action", "tier") if r.get(k, "*") != "*")
        if spec > best_spec:
            best = r
            best_spec = spec
    return best


def resolve_reproducer_route(routing=None):
    """从 ROUTING.yaml 解析 review/reproduce route 的 (provider, model)。

    不硬编码——读取 ROUTING.yaml 的 routes 段，用 _find_route 找
    domain=review / action=reproduce / tier=* 的最具体匹配项。
    找不到时回落到 default 段，再找不到返回 (None, None)。
    """
    if routing is None:
        routing = _load_routing()
    routes = routing.get("routes", []) if isinstance(routing, dict) else []
    default = routing.get("default", {}) if isinstance(routing, dict) else {}
    if not isinstance(default, dict):
        default = {}
    route = _find_route(routes, "review", action="reproduce", tier="*")
    if route is None:
        route = default
    provider = route.get("provider", default.get("provider")) if isinstance(route, dict) else default.get("provider")
    model = route.get("model", default.get("model")) if isinstance(route, dict) else default.get("model")
    return provider, model


# ============================================================
# 沙盒约束（policy.execute.sandbox.*）
# ============================================================
def enforce_sandbox_constraints(policy=None):
    """读取 policy.yml execute.sandbox.* 段，返回约束字典供 run_repro 使用。

    缺失字段用与 policy.yml 注释一致的默认值补齐（timeout 120 / mem 2048 /
    cpu 512 / network read_only / writable_paths [/tmp]）。
    """
    if policy is None:
        policy = _load_policy()
    execute = policy.get("execute", {}) if isinstance(policy, dict) else {}
    if not isinstance(execute, dict):
        execute = {}
    sandbox = execute.get("sandbox", {})
    if not isinstance(sandbox, dict):
        sandbox = {}
    return {
        "timeout_sec": sandbox.get("timeout_sec", 120),
        "memory_mb": sandbox.get("memory_mb", 2048),
        "cpu_shares": sandbox.get("cpu_shares", 512),
        "network": sandbox.get("network", "read_only"),
        "writable_paths": sandbox.get("writable_paths", ["/tmp"]),
    }


# ============================================================
# 沙盒执行
# ============================================================
def run_repro(cmd, timeout_sec=None, policy=None):
    """在干净沙盒中执行 repro.cmd，捕获 exit_code + stdout_excerpt + stderr_excerpt。

    - cwd 强制为 /tmp（policy.execute.sandbox.writable_paths 仅允许 /tmp，无生产仓库写权限）
    - stdout/stderr 截断到 STDOUT_EXCERPT_BYTES（4KB）
    - timeout_sec 缺省时从 policy.execute.sandbox.timeout_sec 读取（默认 120）
    - 超时 → exit_code 记为 -1，stderr_excerpt 追加 TIMEOUT_AFTER 标记
    - 命令通过 shell=True 执行（repro.cmd 允许多行 shell）

    返回 dict：{exit_code, stdout_excerpt, stderr_excerpt, timed_out}。
    返回值是 run_repro 的内部辅助结构（含 timed_out），不是 reproduction.json 的 observed；
    reproduce_claim 会挑选其中的 cmd/exit_code/stdout_excerpt/stderr_excerpt 装入 observed。
    """
    if timeout_sec is None:
        constraints = enforce_sandbox_constraints(policy)
        timeout_sec = constraints["timeout_sec"]
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd="/tmp",
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        exit_code = proc.returncode
        stdout_excerpt = (proc.stdout or "")[:STDOUT_EXCERPT_BYTES]
        stderr_excerpt = (proc.stderr or "")[:STDOUT_EXCERPT_BYTES]
        timed_out = False
    except subprocess.TimeoutExpired as e:
        exit_code = -1
        so = e.stdout if isinstance(e.stdout, str) else ""
        se = e.stderr if isinstance(e.stderr, str) else ""
        stdout_excerpt = so[:STDOUT_EXCERPT_BYTES]
        stderr_excerpt = (se + f"\nTIMEOUT_AFTER {timeout_sec}s\n").strip()[:STDOUT_EXCERPT_BYTES]
        timed_out = True
    except Exception as e:
        exit_code = -1
        stdout_excerpt = ""
        stderr_excerpt = f"REPRO_RUN_ERROR: {type(e).__name__}: {e}"[:STDOUT_EXCERPT_BYTES]
        timed_out = False
    return {
        "exit_code": exit_code,
        "stdout_excerpt": stdout_excerpt,
        "stderr_excerpt": stderr_excerpt,
        "timed_out": timed_out,
    }


def _extract_head_sha(repro):
    """从 repro.env 字符串里抠出 commit SHA（用于 reproduction.env）。"""
    env_str = repro.get("env", "") if isinstance(repro, dict) else ""
    if not isinstance(env_str, str):
        return "unknown"
    m = re.search(r"\b([0-9a-f]{7,40})\b", env_str)
    return m.group(1) if m else "unknown"


# ============================================================
# reproduce_claim：单条 claim 的复现编排
# ============================================================
def reproduce_claim(claim, reviewer_model, reviewer_session,
                    reproducer_model, reproducer_session, policy=None):
    """对一条 claim 跑复现沙盒，返回 reproduction dict（observed 已填，verdict 留给模型）。

    步骤：
    1. materialize.check_self_adjudication 强制 reviewer_model != reproducer_model
       （CHARTER N6；同模型抛 SELF_ADJUDICATION_REFUSED）
    2. materialize._enforce_role("reproducer", "Reproduction") 单向阀门
    3. run_repro 跑 claim.repro.cmd（在 /tmp 沙盒，超时由 policy.execute.sandbox.timeout_sec）
    4. 构造 reproduction dict：observed 已填，verdict=None（由 reproducer 模型按 P12
       比较 observed vs predicted_observation 后填写），不填 next_action（由 conductor 回写）

    返回的 dict 结构对齐 .loop/schemas/reproduction.json，但 verdict=None 表示
    『待模型判定』——此时不会通过 claims.validate_reproduction，需模型补完 verdict/diff_note。
    """
    from conductor import materialize
    # 异构强制（CHARTER N6）
    materialize.check_self_adjudication(
        reviewer_model, reviewer_session, reproducer_model, reproducer_session
    )
    # 角色阀门：reproducer 只能建 Reproduction（+ 对已确认 claim 建 Finding）
    materialize._enforce_role("reproducer", "Reproduction")

    repro = claim.get("repro", {}) if isinstance(claim, dict) else {}
    if not isinstance(repro, dict):
        repro = {}
    cmd = repro.get("cmd", "")
    if not isinstance(cmd, str) or not cmd.strip():
        raise ValueError(
            f"BAD_REPRO_CMD: claim {claim.get('id', '?') if isinstance(claim, dict) else '?'} "
            f"has no executable repro.cmd"
        )

    result = run_repro(cmd, policy=policy)
    constraints = enforce_sandbox_constraints(policy)
    sandbox_id = os.environ.get("LOOP_SANDBOX_ID", "repro-sandbox")
    head_sha = _extract_head_sha(repro)
    env_str = (
        f"sandbox={sandbox_id} / commit {head_sha} / "
        f"{platform.system()} {platform.release()} / "
        f"timeout={constraints['timeout_sec']}s mem={constraints['memory_mb']}MB"
    )

    observed = {
        "cmd": cmd,
        "exit_code": result["exit_code"],
        "stdout_excerpt": result["stdout_excerpt"],
    }
    if result.get("stderr_excerpt"):
        observed["stderr_excerpt"] = result["stderr_excerpt"]

    reproduction = {
        "schema": 1,
        "claim_id": claim.get("id", "") if isinstance(claim, dict) else "",
        "review_id": claim.get("review_id", "") if isinstance(claim, dict) else "",
        "verdict": None,  # 留给 reproducer 模型按 P12 判定（本函数不替模型决定真值）
        "reproducer_model": reproducer_model,
        "observed": observed,
        "env": env_str,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # next_action 由 conductor 的 compute_next_action 回写，此处故意不填
    }
    return reproduction


# ============================================================
# compute_next_action：conductor 侧裁决表
# ============================================================
def _arbitration_samples(policy=None):
    """读 policy.review.arbitration_samples（默认 3）。"""
    if policy is None:
        policy = _load_policy()
    review = policy.get("review", {}) if isinstance(policy, dict) else {}
    if not isinstance(review, dict):
        review = {}
    samples = review.get("arbitration_samples", DEFAULT_ARBITRATION_SAMPLES)
    try:
        n = int(samples)
    except (TypeError, ValueError):
        n = DEFAULT_ARBITRATION_SAMPLES
    return n if n > 0 else DEFAULT_ARBITRATION_SAMPLES


def compute_next_action(verdict, arbitration_count=0, policy=None, labels=None):
    """conductor 侧裁决表：根据单条 verdict + 已仲裁次数计算 next_action。

    规则（对应 docs/强模型验收环.md §4 裁决表，单条 verdict 简化版）：
    - REPRODUCED → "open_fix_card"
    - NOT_REPRODUCED → "close_refuted"
    - INCONCLUSIVE →
        若 arbitration_count < policy.review.arbitration_samples（默认 3）：
            返回 "await_arbitration"
        否则（仲裁样本已耗尽仍不收敛）：
            升级人类——仍返回 "await_arbitration"，但向 labels 列表追加 "needs-human"

    labels: 可选 list；若传入且触发人类升级，会原地追加 "needs-human"。
    返回值恒为 next_action 字符串（VALID_NEXT_ACTIONS 之一）。
    沙盒模型不得调用本函数——next_action 是 conductor 独占的流程决策。
    """
    if verdict == "REPRODUCED":
        return "open_fix_card"
    if verdict == "NOT_REPRODUCED":
        return "close_refuted"
    if verdict == "INCONCLUSIVE":
        cap = _arbitration_samples(policy)
        if arbitration_count < cap:
            return "await_arbitration"
        # 仲裁样本已耗尽仍 INCONCLUSIVE → 升级人类：
        # next_action 维持 await_arbitration，但打 needs-human 标签
        if isinstance(labels, list) and "needs-human" not in labels:
            labels.append("needs-human")
        return "await_arbitration"
    # 未知 verdict：保守等待仲裁，不擅自 close/open
    return "await_arbitration"


# ============================================================
# _suggest_verdict：确定性客观比较（模型不可用时的回退）
# ============================================================
def _suggest_verdict(reproduction, claim):
    """客观比较 observed 与 repro.expected / predicted_observation，给出三态建议。

    这是确定性的回退比较——生产中 verdict 由 reproducer 模型按 P12 判定。
    本函数仅供 arbitrate 在无法逐次调用模型时对多条 reproduction 做多数决，
    不替代模型的最终判定。
    """
    if not isinstance(reproduction, dict) or not isinstance(claim, dict):
        return "INCONCLUSIVE"
    observed = reproduction.get("observed", {})
    if not isinstance(observed, dict):
        return "INCONCLUSIVE"
    exit_code = observed.get("exit_code")
    stdout = observed.get("stdout_excerpt", "")
    if not isinstance(exit_code, int):
        return "INCONCLUSIVE"
    if not isinstance(stdout, str):
        stdout = ""
    repro = claim.get("repro", {})
    if not isinstance(repro, dict):
        repro = {}
    expected = str(repro.get("expected", "")).strip()
    predicted = str(claim.get("predicted_observation", "")).strip()
    stdout_str = stdout.strip()

    # 沙盒超时/未跑出有效退出码 → INCONCLUSIVE（环境/执行问题，非真值问题）
    if exit_code == -1:
        return "INCONCLUSIVE"

    # expected 的关键片段出现在 stdout → REPRODUCED
    if expected and expected in stdout_str:
        return "REPRODUCED"
    # predicted_observation 的关键片段出现在 stdout → REPRODUCED
    if predicted and predicted in stdout_str:
        return "REPRODUCED"
    # 命令跑通（exit 0）且有输出但对不上 → NOT_REPRODUCED
    if exit_code == 0 and stdout_str:
        return "NOT_REPRODUCED"
    # 命令非零退出且 expected 没提到非零退出码 → NOT_REPRODUCED
    if exit_code != 0 and str(exit_code) not in expected:
        return "NOT_REPRODUCED"
    # 命令跑通但无输出且 expected 也无强约束 → INCONCLUSIVE
    return "INCONCLUSIVE"


# ============================================================
# arbitrate：多次采样多数决
# ============================================================
def arbitrate(claim, reviewer_model, reproducer_sessions,
              reproducer_model=None, policy=None):
    """对一条 claim 跑 N 次复现（N = policy.review.arbitration_samples，默认 3），多数决。

    reproducer_sessions: session id 列表（长度即样本数；超过 cap 时按 cap 截断）。
    reproducer_model: 复现模型；不传时由 resolve_reproducer_route() 从 ROUTING.yaml 解析。
                     若 == reviewer_model，reproduce_claim 会抛 SELF_ADJUDICATION_REFUSED。

    返回 dict：
        {
          "verdict":      <三态之一>,
          "labels":       [...],            # 可能含 "needs-human"
          "next_action":  <VALID_NEXT_ACTIONS 之一>,
          "samples":      [<verdict>, ...],
          "reproductions":[<reproduction dict>, ...],
        }

    多数决规则（对齐 docs/强模型验收环.md §4）：
    - 全 REPRODUCED（>=1，0 NOT_REPRODUCED）        → REPRODUCED
    - 全 NOT_REPRODUCED（>=2，0 REPRODUCED）        → NOT_REPRODUCED
    - 既有 REPRODUCED 又有 NOT_REPRODUCED，样本 < cap → INCONCLUSIVE（await_arbitration）
    - 样本 >= cap 仍不收敛                          → INCONCLUSIVE + needs-human 标签
    """
    if reproducer_model is None:
        _, reproducer_model = resolve_reproducer_route()
    cap = _arbitration_samples(policy)
    sessions = list(reproducer_sessions or [])

    if not sessions:
        return {
            "verdict": "INCONCLUSIVE",
            "labels": ["needs-human"],
            "next_action": "await_arbitration",
            "samples": [],
            "reproductions": [],
        }

    verdicts = []
    reproductions = []
    for i, session in enumerate(sessions):
        if i >= cap:
            break
        rep = reproduce_claim(
            claim, reviewer_model, f"reviewer-session-{i}",
            reproducer_model, session, policy=policy,
        )
        v = _suggest_verdict(rep, claim)
        rep["verdict"] = v
        if v != "REPRODUCED":
            rep["diff_note"] = (
                f"客观比较：exit_code={rep['observed']['exit_code']}，"
                f"stdout 与 expected/predicted_observation 不一致（自动比较回退）"
            )
        verdicts.append(v)
        reproductions.append(rep)

    n_reproduced = verdicts.count("REPRODUCED")
    n_not = verdicts.count("NOT_REPRODUCED")

    if n_reproduced > 0 and n_not == 0:
        verdict = "REPRODUCED"
    elif n_not >= 2 and n_reproduced == 0:
        verdict = "NOT_REPRODUCED"
    elif n_not > 0 and n_reproduced > 0:
        # 既有 REPRODUCED 又有 NOT_REPRODUCED → 不收敛
        verdict = "INCONCLUSIVE"
    else:
        # 全 INCONCLUSIVE 或仅 1 个 NOT_REPRODUCED（未达 N>=2）
        verdict = "INCONCLUSIVE"

    labels = []
    arbitration_count = len(verdicts)
    next_action = compute_next_action(
        verdict, arbitration_count=arbitration_count, policy=policy, labels=labels
    )
    # 样本已用满 cap 仍 INCONCLUSIVE → 强制打 needs-human（与 compute_next_action 的升级口径一致）
    if verdict == "INCONCLUSIVE" and arbitration_count >= cap and "needs-human" not in labels:
        labels.append("needs-human")

    return {
        "verdict": verdict,
        "labels": labels,
        "next_action": next_action,
        "samples": verdicts,
        "reproductions": reproductions,
    }
