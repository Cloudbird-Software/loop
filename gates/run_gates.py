#!/usr/bin/env python3
"""gates/run_gates.py — 单一 gate 运行器（R10-3）。

治本 F-A："门禁静默 SKIP"——任何 gate 未执行必须等价于失败。

退出码契约：
  0  全部 gate 实际执行且返回 0
  1  至少一个 gate 显式失败（gate 自身 exit 1）
  2  至少一个 gate 缺席（profile 声明了但三处目录都找不到）→ GATE_NOT_EXECUTED
  3  至少一个 gate 崩溃/超时（exit 非 0 非 1，或被 timeout 杀掉）→ GATE_ERRORED

优先级：missing(2) > errored(3) > fail(1) > pass(0)。

用法：
  python3 gates/run_gates.py --profile default
  python3 gates/run_gates.py --gates charter,verdict --out summary.json
"""
import argparse
import json
import os
import subprocess
import sys
import time
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_policy(path="policy.yml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_search_dirs(policy, cwd=None):
    """解析 search_dirs，展开 ${LOOP_ROOT} 等环境变量，返回绝对路径列表。

    相对路径以 cwd（默认当前目录）为基，便于测试时指向临时目录。
    """
    base = cwd or os.getcwd()
    raw = policy.get("gates", {}).get("search_dirs", ["gates", ".loop/gates"])
    return [os.path.abspath(os.path.join(base, os.path.expandvars(d))) for d in raw]


def resolve_gate(name, search_dirs):
    """在 search_dirs 中按 gate_<name>.py → <name>.py 顺序找文件，返回绝对路径或 None。"""
    candidates = [f"gate_{name}.py", f"{name}.py"]
    for d in search_dirs:
        for fn in candidates:
            p = os.path.join(d, fn)
            if os.path.isfile(p):
                return p
    return None


def run_one(name, path, timeout):
    """执行单个 gate，返回 dict(name/status/exit_code/duration_ms/path/stderr_tail)。"""
    t0 = time.monotonic()
    if path.endswith(".py"):
        cmd = [sys.executable, path]
    else:
        cmd = [path]
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "error", "exit_code": None,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "path": path, "detail": f"TIMEOUT after {timeout}s"}
    except Exception as e:
        return {"name": name, "status": "error", "exit_code": None,
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "path": path, "detail": f"SPAWN_FAIL: {e}"}

    dur = int((time.monotonic() - t0) * 1000)
    code = p.returncode
    stderr_tail = (p.stderr or "").strip().splitlines()
    stderr_tail = "\n".join(stderr_tail[-3:]) if stderr_tail else ""
    has_traceback = "Traceback (most recent call last)" in (p.stderr or "")

    if code == 0:
        status = "pass"
    elif code == 1 and not has_traceback:
        status = "fail"
    else:
        status = "error"
    return {"name": name, "status": status, "exit_code": code,
            "duration_ms": dur, "path": path, "detail": stderr_tail}


def main():
    ap = argparse.ArgumentParser(description="统一 gate 运行器：未执行即失败")
    ap.add_argument("--profile", default="default", help="policy.yml gates.profiles.<name>")
    ap.add_argument("--gates", help="逗号分隔 gate 名，覆盖 profile（用于局部验证）")
    ap.add_argument("--out", help="机器可读摘要 JSON 输出路径")
    ap.add_argument("--timeout", type=int, help="覆盖默认超时（秒）")
    args = ap.parse_args()

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

    search_dirs = resolve_search_dirs(policy)
    results = []
    for name in names:
        path = resolve_gate(name, search_dirs)
        if path is None:
            print(f"GATE_NOT_EXECUTED: {name}")
            results.append({"name": name, "status": "missing", "exit_code": None,
                            "duration_ms": 0, "path": None, "detail": "not found in any search_dir"})
            continue
        r = run_one(name, path, timeouts.get(name, default_timeout))
        results.append(r)
        tag = {"pass": "OK", "fail": "FAIL", "error": "GATE_ERRORED",
               "missing": "GATE_NOT_EXECUTED"}[r["status"]]
        print(f"{tag}: {name} (exit={r['exit_code']}, {r['duration_ms']}ms)")

    has_missing = any(r["status"] == "missing" for r in results)
    has_error = any(r["status"] == "error" for r in results)
    has_fail = any(r["status"] == "fail" for r in results)

    if has_missing:
        exit_code = 2
    elif has_error:
        exit_code = 3
    elif has_fail:
        exit_code = 1
    else:
        exit_code = 0

    summary = {"profile": args.profile, "gates": results, "exit_code": exit_code}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
    print(f"\nsummary: {sum(1 for r in results if r['status']=='pass')}/{len(results)} pass, exit={exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
