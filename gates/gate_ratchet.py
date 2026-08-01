#!/usr/bin/env python3
"""gate_ratchet — 棘轮（ratchet）：禁止门禁配置变松，允许变严。

治本根因：门禁 profile 的 gate 集合被"偷偷缩小"等于静默跳过（R10-3 / F-A 根因）。
棘轮的语义（CHARTER N16-N32 立法交由人类，本 gate 只做机械检测，不施加立法）：
  - 候选配置的某个 profile 相对于基线，只要丢掉了任一已启用 gate → 棘轮倒转（变宽松）→ FAIL(exit 1)。
  - 候选配置新增 gate / 新增 profile / 配置不变 → 允许（变严格 / 持平）→ PASS(exit 0)。

基线（baseline）解析：run_gates.py 以 `cmd=[python, path]` 调度本 gate 时**不传任何参数**
（见 run_gates.py run_one 第 70 行）。若 --base 也默认指向工作区 policy.yml，本 gate 会对同一份
文件"自比对"而永远 PASS，无法拦截检索集合变松（Copilot review on #225 指出的退化）。因此：
  --base 未显式指定时，优先从 git merge-base 的已入库 policy.yml 解析为基线；无 git 上下文再回退
  工作区 policy.yml（此时为 no-op，打印 NOTICE，不误红也不静默拦）。
这使其在 PR/merge_group 的真实调度路径上，把工作区(候选)与上次合并的基线做比对，从而拦截变松。

确定性输出：所有 profile/gate 比较与打印均按排序后的 list 呈现，避免 set 无序导致的日志噪音。

类型校验：profile 必须是 gate 名字符串的 list；误写成字符串/dict 时显式 FAIL（报错串），
禁止用 set() 静默把字符串拆字符 / 把 dict 当 key 集，造成棘轮结果错误与漏报。

用法（独立可测，供 run_gates.py 调度及负证自测）：
  python3 gates/gate_ratchet.py [--candidate PATH] [--base PATH]
  - --candidate : 待检 policy 文件（default = REPO_ROOT/policy.yml，即工作区/候选）
  - --base      : 基线 policy 文件（default = git merge-base 的 policy.yml；无 git 回退工作区）
退出码：0 = PASS（持平或变严格），1 = FAIL（棘轮倒转或 policy 结构非法）。
"""
import argparse
import os
import pathlib
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_policy(path):
    import yaml
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = pathlib.Path(os.getcwd()) / p
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _git(*args, cwd=None):
    """在 REPO_ROOT 内跑 git，任何异常/非零返回 None。"""
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=20,
            cwd=str(cwd or REPO_ROOT),
        )
    except Exception:
        return None


def resolve_baseline(prefer_base):
    """返回 (基线 policy 文件路径, 基线标识字符串)。

    优先级：
      1. --base 显式指定 → 直接用（标识 = 该路径）。
      2. git 上下文可用 → 从 merge-base 的已入库 policy.yml 提取到临时文件（标识 = 基线 sha）。
      3. 无 git/merge-base → 回退工作区 policy.yml（no-op，标识 = 'self'）。
    """
    if prefer_base:
        return prefer_base, prefer_base
    base_ref = os.environ.get("LOOP_CI_BASE") or "origin/main"
    mb = _git("merge-base", base_ref, "HEAD")
    if mb and mb.returncode == 0 and mb.stdout.strip():
        sha = mb.stdout.strip().splitlines()[0]
        show = _git("show", f"{sha}:policy.yml")
        if show and show.returncode == 0:
            tmp = pathlib.Path(os.environ.get("TMPDIR") or "/tmp") / \
                f"gate_ratchet_baseline_{sha}.yml"
            tmp.write_text(show.stdout, encoding="utf-8")
            return str(tmp), sha
    print("NOTICE: no git merge-base baseline available; "
          "comparing policy.yml against itself (no-op)", file=sys.stderr)
    return str(REPO_ROOT / "policy.yml"), "self"


def profile_gates(policy):
    """返回 {profile_name: set(启用 gate)}。只看 profiles 段。

    类型契约：profile 值为 gate 名字符串的 list（可为空/None）。若值为字符串或 dict 等非
    list-of-str，抛 ValueError —— 上层显式 FAIL，禁止 set() 静默错比。
    """
    profiles = (policy.get("gates") or {}).get("profiles") or {}
    result = {}
    for name, items in profiles.items():
        if items is None:
            result[name] = set()
        elif isinstance(items, list) and all(isinstance(x, str) for x in items):
            result[name] = set(items)
        else:
            raise ValueError(
                f"profile '{name}' must be a list of gate-name strings, "
                f"got {type(items).__name__}: {items!r}"
            )
    return result


def ratchet_inversions(base_gates, cand_gates):
    """返回 [(profile, removed_gate)...] 表示候选从基线丢失的 gate（棘轮倒转点）。

    只比较基线(需要保护的下限)与候选都存在的 profile：候选只是在该 profile 内丢掉
    任一已启用 gate 才视为倒转。缺失的 profile 不当作倒转（可能是分段拆分或部分
    快照，不属 default 门禁集合的静默缩小，R10-3 针对的是集合内删除）。"""
    inversions = []
    for pname, base_set in base_gates.items():
        if pname not in cand_gates:
            continue
        for g in sorted(base_set - cand_gates[pname]):
            inversions.append((pname, g))
    return inversions


def fmt(profile_gates):
    """把 {name:set} 规范成排序后 {name:[sorted gates]}，保证输出可复现。"""
    return {pname: sorted(gates) for pname, gates in sorted(profile_gates.items())}


def main():
    ap = argparse.ArgumentParser(description="棘轮 gate：禁止门禁配置变宽松，允许变严格")
    ap.add_argument("--candidate", default=str(REPO_ROOT / "policy.yml"),
                    help="待检 policy 文件（default=REPO_ROOT/policy.yml）")
    ap.add_argument("--base", default=None,
                    help="基线 policy 文件（default=git merge-base 的 policy.yml）")
    args = ap.parse_args()

    base_path, base_id = resolve_baseline(args.base)
    base_policy = load_policy(base_path)
    cand_policy = load_policy(args.candidate)

    try:
        base_gates = profile_gates(base_policy)
        cand_gates = profile_gates(cand_policy)
    except ValueError as e:
        print(f"FAIL: malformed gates.profiles: {e}")
        return 1

    inversions = ratchet_inversions(base_gates, cand_gates)
    if inversions:
        print("FAIL: ratchet inversion detected (config loosened):")
        for pname, g in inversions:
            print(f"  - profile '{pname}' lost active gate '{g}'")
        print(f"baseline gates ({base_id}): {fmt(base_gates)}")
        print(f"candidate gates ({args.candidate}): {fmt(cand_gates)}")
        return 1

    added = []
    for pname, cand_set in cand_gates.items():
        if pname in base_gates:
            for g in sorted(cand_set - base_gates[pname]):
                added.append((pname, g))
    if added:
        print(f"PASS: ratchet forward (config tightened), baseline={base_id}, added gates:")
        for pname, g in added:
            print(f"  - profile '{pname}' added gate '{g}'")
    else:
        print(f"PASS: gate set unchanged (no inversion), baseline={base_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())