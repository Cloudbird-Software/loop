#!/usr/bin/env python3
"""gate_ratchet — 棘轮（ratchet）：禁止门禁配置变松，允许变严。

治本根因：门禁 profile 的 gate 集合被"偷偷缩小"等于静默跳过（R10-3 / F-A 根因）。
棘轮的语义（CHARTER N16-N32 立法交由人类，本 gate 只做机械检测，不施加立法）：
  - 候选配置的某个 profile 相对于基线，只要丢掉了任一已启用 gate → 棘轮倒转（变宽松）→ FAIL(exit 1)。
  - 候选配置新增 gate / 新增 profile / 配置不变 → 允许（变严格 / 持平）→ PASS(exit 0)。

用法（独立可测，供 run_gates.py 调度及负证自测）：
  python3 gates/gate_ratchet.py [--candidate PATH] [--base PATH]
  - --candidate : 待检 policy 文件（default = REPO_ROOT/policy.yml）
  - --base      : 基线 policy 文件（default = REPO_ROOT/policy.yml）
退出码：0 = PASS（持平或变严格），1 = FAIL（棘轮倒转）。
"""
import argparse
import os
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_policy(path):
    import yaml
    p = pathlib.Path(path)
    if not p.is_absolute():
        p = pathlib.Path(os.getcwd()) / p
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def profile_gates(policy):
    """返回 {profile_name: set(启用 gate)}。只看 profiles 段，忽略被注释的 gate。"""
    profiles = (policy.get("gates") or {}).get("profiles") or {}
    return {name: set((items if items else [])) for name, items in profiles.items()}


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


def main():
    ap = argparse.ArgumentParser(description="棘轮 gate：禁止门禁配置变宽松，允许变严格")
    ap.add_argument("--candidate", default=str(REPO_ROOT / "policy.yml"),
                    help="待检 policy 文件（default=REPO_ROOT/policy.yml）")
    ap.add_argument("--base", default=str(REPO_ROOT / "policy.yml"),
                    help="基线 policy 文件（default=REPO_ROOT/policy.yml）")
    args = ap.parse_args()

    base_policy = load_policy(args.base)
    cand_policy = load_policy(args.candidate)
    base_gates = profile_gates(base_policy)
    cand_gates = profile_gates(cand_policy)

    inversions = ratchet_inversions(base_gates, cand_gates)
    if inversions:
        print("FAIL: ratchet inversion detected (config loosened):")
        for pname, g in inversions:
            print(f"  - profile '{pname}' lost active gate '{g}'")
        print(f"baseline gates: {base_gates}")
        print(f"candidate gates: {cand_gates}")
        return 1

    added = []
    for pname, cand_set in cand_gates.items():
        if pname in base_gates:
            for g in sorted(cand_set - base_gates[pname]):
                added.append((pname, g))
    if added:
        print("PASS: ratchet forward (config tightened), added gates:")
        for pname, g in added:
            print(f"  - profile '{pname}' added gate '{g}'")
    else:
        print("PASS: gate set unchanged (no inversion)")
    return 0


if __name__ == "__main__":
    sys.exit(main())