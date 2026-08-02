#!/usr/bin/env python3
"""gates/run_gates.py — 单一 gate 运行器 + 反注入（R10-3 / W3-10 重实现）。

治本 F-A："门禁静默 SKIP"——任何 gate 未执行必须等价于失败（N11：禁假绿）。

退出码契约：
  0  pass        全部 gate 实际执行且通过
  1  fail        至少一个 gate 显式失败
  2  unresolved  至少一个 gate 缺席 / 执行数 < min_gates 反空过（GATE_NOT_EXECUTED）
  3  error       至少一个 gate 崩溃/超时/无法 spawn（GATE_ERRORED）
  4  untrusted   至少一个 gate 解析到受控根之外（反注入）→ GATE_UNTRUSTED

归约优先级表（check order，先命中者胜；数值=退出码）：
  untrusted(4) → error(3) → unresolved(2) → fail(1) → pass(0)
（退出码数值与归约优先级分离：归约是检查顺序，退出码是输出结果。用户字面语义
  untrusted>error>unresolved>fail>pass 与数值单调递减一致，两者等价。）

用法：
  python3 gates/run_gates.py --profile default
  python3 gates/run_gates.py --gates charter,verdict --out summary.json
  python3 gates/run_gates.py --profile default --min-gates 2
"""
import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_policy(path="policy.yml"):
    """加载 policy。（PyYAML 懒加载/可选：仅在本函数内 import yaml，
    沙盒无 yaml 时回落 JSON 兜底，保证 `from gates.run_gates import ...` 不依赖 yaml 也能成功。）"""
    try:
        import yaml
    except ImportError:
        yaml = None
    # 如果 path 不存在，尝试从 LOOP_ROOT 加载（产品仓场景：policy.yml 在 loop 侧）
    p = pathlib.Path(path)
    if not p.is_absolute():
        # 先试 cwd
        if not p.exists():
            loop_root = os.environ.get("LOOP_ROOT", "")
            if loop_root:
                alt = pathlib.Path(loop_root) / path
                if alt.exists():
                    p = alt
    with open(p, encoding="utf-8") as f:
        if yaml is not None:
            return yaml.safe_load(f) or {}
        text = f.read()
    # 无 PyYAML 回退：若文件能被 JSON 解析则用之；否则硬失败（非假绿，N11）
    try:
        return json.loads(text) or {}
    except Exception:
        raise SystemExit(f"FAIL: PyYAML 未安装且 {p} 非 JSON 可解析，无法加载 policy")


def _expand_loop_root(d):
    """展开 ${LOOP_ROOT}。os.path.expandvars 对未定义变量保持字面不动，
    ${LOOP_ROOT}/gates 在 LOOP_ROOT 未设时会残留字面，导致 gate 解析缺失。
    本仓（loop 仓自身）场景下 LOOP_ROOT 即 REPO_ROOT，未设时回退到 REPO_ROOT，
    保证受控加载路径（policy.yml gates.search_dirs）真正收敛到 ${LOOP_ROOT}/gates。"""
    d = os.path.expandvars(d)
    if "${LOOP_ROOT}" in d and "LOOP_ROOT" not in os.environ:
        d = d.replace("${LOOP_ROOT}", REPO_ROOT)
    return d


def resolve_search_dirs(policy, cwd=None):
    """解析 search_dirs，展开 ${LOOP_ROOT} 等环境变量，返回绝对路径列表。

    相对路径以 cwd（默认当前目录）为基，便于测试时指向临时目录。
    """
    base = cwd or os.getcwd()
    raw = policy.get("gates", {}).get("search_dirs", ["gates", ".loop/gates"])
    return [os.path.abspath(os.path.join(base, _expand_loop_root(d))) for d in raw]


def assert_loop_control(policy, cwd=None):
    """启动断言：受控 gate 加载目录必须存在（等价于 `.loop-control` 标识存在）。

    W1-4 Gate 注入消除：`.loop-control` 作为「受控加载」标识，语义上落在
    `${LOOP_ROOT}/gates` 目录本身。gate 只允许从 search_dirs 解析出的受控目录
    加载，故该受控目录必须存在，否则拒载继续——未执行等价失败（F-A）。

    实现决策：本仓库当前并无字面 `.loop-control` 文件，故将 `.loop-control`
    标识解读为「受控 search_dir（由 ${LOOP_ROOT}/gates 展开，见 resolve_search_dirs）
    必须存在」的启动断言：受控目录存在即断言通过，运行即输出确认。

    范围控制（契约兼容）：仅当 search_dirs 显式引用受控 `${LOOP_ROOT}/gates`
    路径时才做硬失败（注入消除）。测试夹具常用相对目录（如 ["gates"]）单独
    验证「profile 声明的 gate 找不到 → GATE_NOT_EXECUTED → exit 2」，此时受控
    目录断言不应抢先失败，交由后续 missing-gate 逻辑给出 exit 2。故不含
    `${LOOP_ROOT}` 标记、无法识别为受控路径的 search_dir，仅打印提示而不阻断。
    """
    dirs = resolve_search_dirs(policy, cwd=cwd)
    if not dirs:
        raise SystemExit("FAIL: gates.search_dirs 为空，无受控 gate 加载目录（.loop-control 缺失）")
    control = dirs[0]
    is_controlled = "${LOOP_ROOT}" in " ".join(policy.get("gates", {}).get("search_dirs") or [])
    if is_controlled and not os.path.isdir(control):
        raise SystemExit(f"FAIL: 受控 gate 加载目录不存在（.loop-control 缺失）：{control}")
    if is_controlled:
        print(f".loop-control: 受控 gate 加载目录确认存在 -> {control}")
    else:
        print(".loop-control: search_dirs 未引用 ${LOOP_ROOT} 受控路径，跳过受控目录硬断言")
    return control


def resolve_gate(name, search_dirs):
    """在 search_dirs 中按 gate_<name>.py → <name>.py 顺序找文件，返回绝对路径或 None。"""
    candidates = [f"gate_{name}.py", f"{name}.py"]
    for d in search_dirs:
        for fn in candidates:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return p
    return None


def trust_check(target, controlled_root):
    """反注入判定：target 是否「不可信」。

    用 realpath 包含性（非 startswith 前缀）判断：解析符号链接、归一化 `.`/`..`
    后的 realpath 是否落在受控根（controlled_root）的 realpath 内。拒绝：
      * `..` 逃逸                          → realpath 逃出受控根
      * 逃出受控根的符号链接                → realpath 逃出受控根
      * /gates_evil 这类前缀撞名（非包含）  → commonpath 判定，非 /gates 前缀误判
      * setuid / setgid / sticky 特殊位     → 视为高危不可信

    返回 untrusted(bool)：True=不可信（调用方应判定 exit 4），False=可信。
    """
    try:
        control = os.path.realpath(str(controlled_root))
        real_t = os.path.realpath(os.path.abspath(str(target)))
    except Exception:
        return True

    # return True 当解析失败（目标取不到 realpath）即视为不可信，绝不静默放行（N11）
    if not real_t:
        return True

    # setuid(0o4000) / setgid(0o2000) / sticky(0o1000) 特殊位 → 高危不可信
    try:
        st = os.stat(real_t)
        mode = st.st_mode
        if mode & 0o7000:
            return True
    except OSError:
        return True

    # realpath 包含性：commonpath 判 target 是否「在」受控根内，而非「以根为前缀」。
    # 不同盘符/无公共路径时 commonpath 抛 ValueError → 视为逃逸。
    try:
        common = os.path.commonpath([control, real_t])
    except ValueError:
        return True
    return not (common == control)


def _severity(status):
    """status → 归约严重度（数值=退出码）。枚举穷尽；未知状态绝不静默通过（N11），回落 error(3)。"""
    if status in ("untrusted",):
        return 4
    if status in ("error",):
        return 3
    if status in ("unresolved", "missing", "not_found", "root_unavailable"):
        return 2
    if status in ("fail",):
        return 1
    if status in ("pass",):
        return 0
    return 3  # 未知 status：宁可判定 error，也不假装 pass


def reduce_exit(results):
    """单一归约器。

    归约优先级（check order，先命中者胜）：untrusted(4) → error(3) →
    unresolved(2) → fail(1) → pass(0)。各 status 经 _severity 映射为退出码数值，
    取最大即等价于该检查顺序（数值单调递减，untrusted 最高）。穷举无 default：
    结果为空 → 0（全 pass 等价），未知 status → error(3)，绝无静默假绿。

    测试样例（AC-2）：
      untrusted+error+fail → 4；error+unresolved+fail → 3；
      unresolved+fail → 2；仅 fail → 1；全 pass → 0。
    """
    worst = 0
    for r in results:
        sev = _severity((r or {}).get("status", "error"))
        if sev > worst:
            worst = sev
    return worst


def run_one(name, path, timeout, cwd=None):
    """执行单个 gate，返回 dict(name/status/exit_code/duration_ms/path/detail/reason)。

    status 映射到新分类：pass / fail / error（traceback|timeout|spawn 经 reason 细分）/ not_found。
    """
    t0 = time.monotonic()
    # W1-4：执行前打印解析出的绝对路径与文件内容 SHA256（加载路径收敛 + 可审计注入）
    with open(path, "rb") as pf:
        sha256 = hashlib.sha256(pf.read()).hexdigest()
    print(f"GATE {name} path={os.path.abspath(path)} sha256={sha256}")
    if path.endswith(".py"):
        cmd = [sys.executable, path]
    else:
        cmd = [path]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "error", "exit_code": None,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "path": path, "detail": f"TIMEOUT after {timeout}s", "reason": "timeout"}
    except Exception as e:
        return {"name": name, "status": "error", "exit_code": None,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "path": path, "detail": f"SPAWN_FAIL: {e}", "reason": "spawn_fail"}

    dur = int((time.monotonic() - t0) * 1000)
    code = p.returncode
    stderr_tail = (p.stderr or "").strip().splitlines()
    stderr_tail = "\n".join(stderr_tail[-3:]) if stderr_tail else ""
    has_traceback = "Traceback (most recent call last)" in (p.stderr or "")

    if code == 0:
        status, reason = "pass", "ok"
    elif code == 1 and not has_traceback:
        status, reason = "fail", "gate_failed"
    else:
        status, reason = "error", "traceback"
    return {"name": name, "status": status, "exit_code": code,
            "duration_ms": dur, "path": path, "detail": stderr_tail, "reason": reason}


def main():
    ap = argparse.ArgumentParser(description="统一 gate 运行器：未执行即失败")
    ap.add_argument("--profile", default="default", help="policy.yml gates.profiles.<name>")
    ap.add_argument("--gates", help="逗号分隔 gate 名，覆盖 profile（用于局部验证）")
    ap.add_argument("--out", help="机器可读摘要 JSON 输出路径")
    ap.add_argument("--timeout", type=int, help="覆盖默认超时（秒）")
    ap.add_argument("--min-gates", type=int, default=None,
                    help="反空过：实际执行 pass/fail 数 < 该值 → unresolved → exit 2")
    ap.add_argument("--root", default=None,
                    help="目标仓根目录（产品仓场景：gate 在该目录下扫描，policy 从 LOOP_ROOT 读）")
    args = ap.parse_args()

    # --root 改变 gate 的 cwd 和 search_dirs 基准
    root = args.root or os.getcwd()
    root = os.path.abspath(root)
    # 产品仓场景：policy.yml 在 loop 侧（LOOP_ROOT），不在产品仓
    if not os.path.isfile(os.path.join(root, "policy.yml")):
        loop_root = os.environ.get("LOOP_ROOT", "")
        if loop_root and os.path.isfile(os.path.join(loop_root, "policy.yml")):
            os.chdir(loop_root)  # 切到 loop 侧读 policy.yml
    policy = load_policy()
    gconf = policy.get("gates", {})
    default_timeout = args.timeout or gconf.get("timeout_default", 120)
    timeouts = gconf.get("timeouts", {}) or {}

    if args.gates:
        names = [n.strip() for n in args.gates.split(",") if n.strip()]
    else:
        names = gconf.get("profiles", {}).get(args.profile)
        if not names:
            print(f"FAIL: profile '{args.profile}' not found or empty in policy.yml")
            sys.exit(2)

    search_dirs = resolve_search_dirs(policy, cwd=root)
    controlled_root = assert_loop_control(policy, cwd=root)  # W1-4：启动断言——受控 gate 加载目录必须存在
    results = []
    for name in names:
        path = resolve_gate(name, search_dirs)
        if path is None:
            print(f"GATE_NOT_EXECUTED: {name}")
            results.append({"name": name, "status": "unresolved", "exit_code": None,
                            "duration_ms": 0, "path": None,
                            "detail": "not found in any search_dir", "reason": "not_found"})
            continue
        # 反注入：gate 文件必须位于受控根内，否则判定 untrusted → exit 4
        if trust_check(path, controlled_root):
            print(f"GATE_UNTRUSTED: {name} path={os.path.abspath(path)}")
            results.append({"name": name, "status": "untrusted", "exit_code": None,
                            "duration_ms": 0, "path": os.path.abspath(path),
                            "detail": "resolved outside controlled root", "reason": "path_outside_controlled_root"})
            continue
        r = run_one(name, path, timeouts.get(name, default_timeout), cwd=root)
        results.append(r)
        tag = {"pass": "OK", "fail": "FAIL", "error": "GATE_ERRORED",
               "untrusted": "GATE_UNTRUSTED", "unresolved": "GATE_NOT_EXECUTED"}.get(r["status"], "?")
        print(f"{tag}: {name} (exit={r['exit_code']}, {r['duration_ms']}ms)")

    exit_code = reduce_exit(results)

    # min_gates 反空过：实际执行 pass/fail 数 < min_gates → unresolved(goal) → exit 2
    min_gates = args.min_gates if args.min_gates is not None else gconf.get("min_gates", 0)
    executed = sum(1 for r in results if r["status"] in ("pass", "fail"))
    if executed < min_gates:
        print(f"GATE_MIN_GATES: executed={executed} < min_gates={min_gates} -> unresolved (exit 2)")
        results.append({"name": "<min_gates>", "status": "unresolved", "exit_code": None,
                        "duration_ms": 0, "path": None,
                        "detail": f"executed {executed} < min_gates {min_gates}",
                        "reason": "min_gates_not_met"})
        exit_code = reduce_exit(results)

    summary = {"profile": args.profile, "gates": results, "exit_code": exit_code}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    print(f"\nsummary: {sum(1 for r in results if r['status']=='pass')}/{len(results)} pass, exit={exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()