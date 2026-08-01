#!/usr/bin/env python3
"""gates/gate_maturity_evidence.py — 成熟度证据门禁（W0-1）。

gate 契约（与 run_gates.py 对齐）：子进程运行，exit 0=pass，exit 1=fail，
exit >1=error。

校验对象：标签 / claim 升级到「成熟」必须有真实 CI run 证据 backing。
无 run 证据时 → FAIL 并打印 NO_RUN_EVIDENCE 错误码（WAVE-00 负证 N1）。

证据来源（按优先级，任一命中即视为有 run 证据）：
  1. 环境变量 EVIDENCE_RUN_ID 非空 → 视为有 run 证据（run id 即证据）
  2. 环境变量 EVIDENCE_FILE 指向的文件存在且非空 → 视为有 run 证据
  3. 默认 marker 文件 .loop/evidence/run-evidence.json 存在且非空 → 视为有 run 证据
  4. 以上都无 → NO_RUN_EVIDENCE → FAIL (exit 1)

确定性 + 可离线测试：不硬依赖网络；env var 与本地 marker 文件均可控。
默认调用（无 env / 无 marker）即「无 run 证据」场景 → FAIL（AC-2 负证）。
"""
import os
import sys

# 错误码常量（W0-1 AC-2 要求）：无 run 证据时 gate 返回此码。
NO_RUN_EVIDENCE = "NO_RUN_EVIDENCE"

# 默认证据 marker 文件路径（相对仓根；可被 EVIDENCE_FILE 覆盖）。
DEFAULT_EVIDENCE_FILE = os.path.join(".loop", "evidence", "run-evidence.json")


def _repo_root():
    """gate 由 run_gates.py 以 cwd=目标仓根 执行（见 gate_smoke.py 注释），
    故用 os.getcwd() 作为作用仓根，与 gate_smoke / gate_settings_roundtrip 一致。"""
    return os.getcwd()


def _evidence_file_path():
    """解析证据 marker 文件路径：EVIDENCE_FILE > 默认。"""
    env_file = os.environ.get("EVIDENCE_FILE", "").strip()
    if env_file:
        return env_file
    return os.path.join(_repo_root(), DEFAULT_EVIDENCE_FILE)


def _has_env_run_id():
    """EVIDENCE_RUN_ID 非空即视为有 run 证据。"""
    rid = os.environ.get("EVIDENCE_RUN_ID", "").strip()
    return bool(rid)


def _has_marker_file():
    """marker 文件存在且非空即视为有 run 证据。"""
    path = _evidence_file_path()
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def check_evidence():
    """检查是否存在 run 证据。返回 (has_evidence, detail)。

    has_evidence=True → PASS（exit 0）；False → NO_RUN_EVIDENCE → FAIL（exit 1）。
    """
    if _has_env_run_id():
        rid = os.environ.get("EVIDENCE_RUN_ID", "").strip()
        return True, f"evidence: EVIDENCE_RUN_ID={rid}"
    if _has_marker_file():
        return True, f"evidence: marker file {_evidence_file_path()}"
    return False, (
        "no run evidence found (no EVIDENCE_RUN_ID env, "
        "no EVIDENCE_FILE env, no default marker at "
        f"{_evidence_file_path()})"
    )


def main():
    """gate 入口：有 run 证据 → exit 0；无 → NO_RUN_EVIDENCE → exit 1。"""
    has, detail = check_evidence()
    if has:
        print(f"OK: {detail}")
        sys.exit(0)
    # 无 run 证据 → FAIL（exit 1），打印 NO_RUN_EVIDENCE 错误码（N1 负证）。
    print(f"FAIL: {NO_RUN_EVIDENCE} — {detail}")
    sys.exit(1)


if __name__ == "__main__":
    main()
