#!/usr/bin/env python3
"""gate_semgrep — Semgrep 自研规则扫描门禁（W1-6）。

扫描制品：本仓自研规则集 rules/loop（W1 自研守卫）。目标（target）默认 = 当前
工作区根目录（run_gates.py 以 `--root` 指定的作用仓作为 cwd 启动本 gate，见
gate_smoke.py 的同款 REPO_ROOT=os.getcwd() 约定）；也接受显式传路径（单文件/目录），
便于局部验证与负证自测。import 此模块不会执行扫描（仅 __main__ 触发）。

调用路径（优先真实 semgrep）：
  semgrep scan --config <rules/loop> --error --metrics off <target>
  - --error   : 扫描结果（含 find code smokes）作为 gate 成败依据。
  - --metrics off : 不上报 Semgrep Cloud/匿名遥测，纯本地无服务扫描。
  - 退出码语义（semgrep --error）：0=无命中；1=命中违规；>1=执行错误。

semgrep 不可用（未安装/不可执行）时的兜底：内置轻量检测，至少覆盖
  - silent-swallow      ：subprocess.run/call/Popen 未校验 returncode（无 check）
  - subprocess-shell-true：subprocess.run/call/Popen(shell=True) / os.system
命中即 FAIL，禁止 fail-open。兜底可独立于真实 semgrep 工作。

退出码契约（与 run_gates.py 对齐，0=PASS / 1=FAIL / 2|3=GATE_ERRORED）：
  0  PASS：未发现规则违规。
  1  FAIL：发现规则违规（真实 semgrep --error 命中，或兜底命中）。
  2  ERROR：gate 运行环境错误（semgrep 崩溃且兜底无法定位语义工件）。
  3  ERROR：内部错误（如 rules 目录缺失 / 兜底异常），非违规导致的失败。
"""
import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO_ROOT = os.getcwd()
RULES_DIR = os.path.join(REPO_ROOT, "rules", "loop")

_SWALLOW_RE = re.compile(r"subprocess\.(run|call|Popen)\(")
_SHELL_TRUE_RE = re.compile(
    r"subprocess\.(run|call|Popen)\([^)]*shell\s*=\s*True", re.IGNORECASE
)
_OS_SYSTEM_RE = re.compile(r"os\.system\(")


def _iter_python_files(path):
    """遍历 target 下的 .py 文件（单文件亦支持）。"""
    p = pathlib.Path(path)
    if p.is_file():
        if p.suffix == ".py":
            yield p
        return
    if p.is_dir():
        for f in sorted(p.rglob("*.py")):
            yield f


def run_semgrep(target):
    """调用真实 semgrep。返回 exit_code 语义：0=无违规, 1=有违规, 2=不可用/执行错误。
    找不到 semgrep 直接返回 None，由上层走兜底。"""
    semgrep = shutil.which("semgrep")
    if not semgrep:
        return None
    cmd = [semgrep, "scan", "--config", RULES_DIR, "--error", "--metrics", "off", str(target)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:  # 兜底保护：禁止因 semgrep 崩溃而 fail-open
        print(f"FAIL-OPEN-PROTECTED: semgrep crashed while scanning: {e}", file=sys.stderr)
        return 2
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode == 0:
        return 0
    if proc.returncode == 1:
        return 1
    print(f"FAIL-OPEN-PROTECTED: semgrep exit={proc.returncode} (execution error)", file=sys.stderr)
    return 2


def run_fallback(target):
    """内置轻量兜底检测，返回 [(rule_id, file, lineno, source)]。至少覆盖
    silent-swallow 与 subprocess-shell-true，命中即代表违规。"""
    findings = []
    for f in _iter_python_files(target):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _SHELL_TRUE_RE.search(line) or _OS_SYSTEM_RE.search(line):
                findings.append(("subprocess-shell-true", f, lineno, line.strip()))
            elif _SWALLOW_RE.search(line) and not re.search(r"check\s*=", line):
                findings.append(("silent-swallow", f, lineno, line.strip()))
    return findings


def main():
    ap = argparse.ArgumentParser(description="Semgrep 自研规则门禁 gate（W1-6）")
    ap.add_argument("target", nargs="?", default=".",
                    help="扫描目标（默认当前工作区根；可单文件/目录用于负证自测）")
    args = ap.parse_args()

    if not os.path.isdir(RULES_DIR):
        print(f"ERROR: rules dir not found: {RULES_DIR}", file=sys.stderr)
        return 3

    code = run_semgrep(args.target)
    if code is not None:
        return code

    # semgrep 不可用 → 兜底（禁止 fail-open）
    print("NOTICE: semgrep not installed; using built-in lightweight fallback",
          file=sys.stderr)
    findings = run_fallback(args.target)
    if findings:
        print("FAIL: fallback detected rule violations (no fail-open):")
        for rid, f, lineno, src in findings:
            print(f"  - {rid}: {f}:{lineno}: {src}")
        return 1
    print(f"PASS: no rule violations (fallback) in {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())