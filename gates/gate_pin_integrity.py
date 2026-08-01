#!/usr/bin/env python3
"""gate_pin_integrity — 供应链 pin/profile 完整性检查（W1-8）。

对目标 `.github/workflows/*.yml` 的每个 step：
  1. 一致性：当 step 同时给出 `uses:`（SHA pin）与 `with: loop-sha` 时，
     两者必须指向同一 SHA（防供应链 pin 与非祖先/伪造 SHA 错配）。
  2. 祖先：`with: loop-sha` 指向的 SHA 必须是当前 HEAD 的祖先
     （用 `git merge-base --is-ancestor <sha> HEAD` 判定，防伪造/非祖先 pin）。

默认 exit 0；发现不一致或非祖先 → 打印原因 exit 1（禁止 fail-open）。
无 uses/loop-sha 可扫 → 打印说明视为 PASS（非负证场景）。

提供可测接口：
  - extract_shas(uses)
  - check_sha_vs_loop_sha(uses, loop_sha) -> (ok, reason)
  - is_ancestor(sha) -> bool
  - check_workflow_file(path) -> (ok, reasons, scanned)
"""
import os
import re
import subprocess
import sys

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")

WORKFLOW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows")


def extract_shas(uses):
    """从 `uses: org/repo@<ref>` 提取 40 位完整 SHA；ref 非 SHA（tag/branch）时返回 None。"""
    if not uses or not isinstance(uses, str) or "@" not in uses:
        return None
    ref = uses.rsplit("@", 1)[1].split("#")[0].strip()
    if SHA_RE.fullmatch(ref):
        return ref.lower()
    return None


def check_sha_vs_loop_sha(uses, loop_sha):
    """一致性：uses 的 SHA pin 与 with: loop-sha 必须一致。返回 (ok, reason)。"""
    if loop_sha is None:
        return True, "no loop-sha present (not a pin-integrity target)"
    loop_sha = str(loop_sha).strip().lower()
    if not SHA_RE.fullmatch(loop_sha):
        return False, f"FAIL: with.loop-sha is not a full 40-hex SHA: {loop_sha!r}"
    uses_sha = extract_shas(uses)
    if uses_sha is None:
        # uses 未提供可比对 SHA（如 tag/branch 或缺失），无法做一致性判定，
        # 交由祖先校验兜底（loop-sha 必须是祖先）。不算 fail-open 的正证命中。
        return True, f"uses has no 40-hex SHA pin ({uses!r}); ancestor check still applies"
    if uses_sha != loop_sha:
        return False, f"FAIL: uses SHA {uses_sha} != with.loop-sha {loop_sha}"
    return True, f"uses SHA {uses_sha} == loop-sha {loop_sha}"


def is_ancestor(sha):
    """with: loop-sha 的 SHA 是否为当前 HEAD 的祖先（`git merge-base --is-ancestor`）。"""
    if not sha or not SHA_RE.fullmatch(str(sha).strip()):
        return False
    try:
        p = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(sha).strip(), "HEAD"],
            capture_output=True, text=True,
        )
        return p.returncode == 0
    except Exception:
        return False


def check_workflow_file(path):
    """检查单个 workflow 文件。返回 (ok, reasons, scanned_steps)。"""
    reasons = []
    scanned = 0
    if not os.path.exists(path):
        return True, ["no workflow file to scan (missing): %s" % path], 0
    try:
        import yaml
        data = yaml.safe_load(open(path, encoding="utf-8"))
        jobs = (data or {}).get("jobs") or {}
    except Exception as e:
        return False, [f"FAIL: cannot parse {path}: {e}"], 0

    for job_name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            with_map = step.get("with") or {}
            loop_sha = with_map.get("loop-sha")
            if loop_sha is None and not uses:
                continue
            scanned += 1
            if loop_sha is None:
                # 只有 uses、没有 loop-sha：属于非 pin-integrity 目标，直接放行
                reasons.append(f"step in job {job_name!r} has uses but no loop-sha; skipped")
                continue
            ok1, r1 = check_sha_vs_loop_sha(uses, loop_sha)
            ok2 = True
            r2 = ""
            if not is_ancestor(loop_sha):
                ok2 = False
                r2 = f"FAIL: loop-sha {loop_sha} is NOT an ancestor of HEAD"
            if not (ok1 and ok2):
                reasons.append(f"[{path}] job {job_name!r}: {r1} | {r2}")
    return (len(reasons) == 0), reasons, scanned


def main():
    ok = True
    total_scanned = 0
    all_reasons = []
    for name in sorted(os.listdir(WORKFLOW_DIR)):
        if not name.endswith((".yml", ".yaml")):
            continue
        step_ok, reasons, scanned = check_workflow_file(os.path.join(WORKFLOW_DIR, name))
        total_scanned += scanned
        if not step_ok:
            ok = False
            all_reasons.extend(reasons)
    if total_scanned == 0:
        print("PASS: no uses/loop-sha pin-integrity targets found in .github/workflows")
    elif ok:
        print(f"OK: {total_scanned} pin-integrity step(s) scanned, all consistent & ancestors")
    else:
        all_reasons = [r for r in all_reasons if r.startswith("FAIL")]
        print("\n".join(all_reasons))
        sys.exit(1)


if __name__ == "__main__":
    main()