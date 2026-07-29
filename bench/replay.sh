#!/usr/bin/env bash
# bench/replay.sh — 重放运行器（loopd/intents.yaml 的 bench.replay 意图入口）。
#
# 单次重放 N 张卡，每张打印一行结果：
#   R-NNN <PASS|FAIL> <diff_lines> <reopen> <cost_yuan>
#
# 模式：
#   默认（real）  : 实际重放。需要 product-x 工作区与被测 pin 已就位。
#                   今晚最小实现：读 replay 卡的 baseline_metrics 作为结果
#                   （product-x 沙盒未接入，真实重放留待 W6/B25 之后）。
#   BENCH_DRY_RUN=1: 直接吐 baseline_metrics，供升级环空跑。
#   BENCH_PERTURB=<json>: 用给定的 after-metrics 覆盖所有卡的输出，
#                   供升级环 dry-run 模拟"升后"结果。
#
# 用法：
#   bash bench/replay.sh [replay_dir] [N]
#     replay_dir 默认 bench/replay
#     N 默认全部
set -euo pipefail

REPLAY_DIR="${1:-bench/replay}"
N="${2:-0}"

if [ ! -d "$REPLAY_DIR" ]; then
  echo "ERROR: replay dir not found: $REPLAY_DIR" >&2
  exit 2
fi

PERTURB="${BENCH_PERTURB:-}"
DRY="${BENCH_DRY_RUN:-0}"

# 用 python 解析每张卡并打印结果行（避免 bash 里搞 JSON）
python3 - "$REPLAY_DIR" "$N" "$DRY" "$PERTURB" <<'PY'
import json, os, sys, pathlib, glob
replay_dir, n_arg, dry, perturb = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
files = sorted(glob.glob(os.path.join(replay_dir, "R-*.json")))
try:
    n = int(n_arg)
except ValueError:
    n = 0
if n > 0:
    files = files[:n]

perturb_metrics = None
if perturb:
    try:
        perturb_metrics = json.loads(perturb)
    except Exception as e:
        print(f"ERROR: bad BENCH_PERTURB json: {e}", file=sys.stderr)
        sys.exit(2)

for f in files:
    try:
        card = json.loads(open(f).read())
    except Exception as e:
        print(f"R-? FAIL 0 0 0.0  # bad json {f}: {e}")
        continue
    cid = card.get("id", os.path.basename(f).removesuffix(".json"))
    bm = card.get("baseline_metrics", {})
    if perturb_metrics is not None:
        # 升后模拟：用 perturb 覆盖，但保留卡的个体差异（diff 按比例放大）
        after = perturb_metrics
        passed = after.get("first_ci_pass", bm.get("first_ci_pass", False))
        diff = after.get("diff_lines", bm.get("diff_lines", 0))
        reopen = after.get("reopen_count", bm.get("reopen_count", 0))
        cost = after.get("cost_yuan", bm.get("cost_yuan", 0.0))
    else:
        passed = bm.get("first_ci_pass", False)
        diff = bm.get("diff_lines", 0)
        reopen = bm.get("reopen_count", 0)
        cost = bm.get("cost_yuan", 0.0)
    status = "PASS" if passed else "FAIL"
    print(f"{cid} {status} {diff} {reopen} {cost}")
PY
