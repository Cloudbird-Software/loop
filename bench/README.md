# bench — holdout 重放包（第 8 环升级环配套）

> 公开仓库。承载升级环（`conductor/upgrade_ring.py`）做"指标不劣化才允许合并"判定所需的重放卡与基线。
> 接缝 E（评测）的契约见 OPC-v4 第 2.1 节。本目录是升级环激活门槛（≥10 张重放卡）的最小实现。

## 目录布局

```
bench/
├── README.md                  本文件，格式规范
├── replay.sh                  重放运行器（被 loopd/intents.yaml 的 bench.replay 意图调用）
├── metrics.py                 四指标采集与对比
├── baseline.json              基线四指标（当前 pin 下的健康值）
├── fixtures/
│   └── fake_feed.json         假 release feed（验收空跑用，含 TOO_YOUNG / REGRESSED / OK 三类候选）
└── replay/
    ├── R-001.json … R-005.json   首批：从 product-x 已合并的 5 张 trivial 卡历史合成
    └── R-006.json … R-010.json   补足合成样例到 10 张（升级环激活门槛）
```

## replay/*.json 格式（schema 1）

每张重放卡是一个独立 JSON 文件，字段一字不差：

```json
{
  "schema": 1,
  "id": "R-001",
  "source": {
    "repo": "product-x",
    "card_number": 18,
    "card_id": "C-2026W31-001",
    "merged_sha": "<product-x 上该卡合入 commit 的 7 位短 sha>"
  },
  "card_description": "一句话描述原卡做了什么（用于人类读报告，不参与判定）",
  "tier": "trivial",
  "paths": ["src/errors/**", "tests/unit/errors/**"],
  "acceptance": ["AC1: ...", "AC2: ..."],
  "expected_evidence": [
    {"kind": "test", "ref": "tests/unit/errors/test_envelope.py::test_basic", "must_pass": true},
    {"kind": "gate", "ref": "gate/build", "must_pass": true}
  ],
  "env_pin": {
    "loop_repo_sha": "<升级环运行时 loop 仓库的 pin>",
    "product_x_sha": "<重放时 product-x 的 pin>",
    "upstream_pins": {"PyYAML": "6.0.3"}
  },
  "baseline_metrics": {
    "first_ci_pass": true,
    "reopen_count": 0,
    "diff_lines": 42,
    "cost_yuan": 0.0
  }
}
```

字段语义：
- `id` — 重放卡唯一编号，`R-NNN`。
- `source` — 溯源到 product-x 上原卡（repo / issue number / card_id / merged_sha）。
- `card_description` — 人类可读，不参与机器判定。
- `tier` — 沿用原卡档位（trivial / standard / critical）。
- `paths` / `acceptance` — 原卡的 paths 与验收条件，重放时按此约束产出。
- `expected_evidence` — 重放期望产出的证据（测试用例 / gate 名），`must_pass=true` 的项必须通过。
- `env_pin` — 重放时的环境 pin（loop 仓库 sha、product-x sha、上游依赖 pin）。升级环在"升前 / 升后"两次重放用同一组卡，只换被升的那个 upstream pin。
- `baseline_metrics` — 该卡在当前 pin 下的基线四指标，用于"劣化超阈值"判定。

## 四指标（升级环判定用）

| 指标 | 含义 | 劣化判定 |
|---|---|---|
| `first_ci_pass_rate` | N 张卡首次 CI 通过的比例 | after < before − 阈值 → REGRESSED |
| `reopen_count` | N 张卡 reopen 次数总和 | after > before + 阈值 → REGRESSED |
| `avg_diff_lines` | N 张卡平均 diff 行数 | after > before × (1+阈值) → REGRESSED |
| `single_card_cost_yuan` | 单卡平均成本（元） | after > before × (1+阈值) → REGRESSED |

阈值默认（可被 `policy.upstream` 覆盖，本目录用 `bench/thresholds.json`，未提供时用代码默认）：
- `first_ci_pass_rate`: 下降 > 0.05（5 个百分点）
- `reopen_count`: 增加 > 1
- `avg_diff_lines`: 增加 > 20%
- `single_card_cost_yuan`: 增加 > 30%

任一指标劣化超阈值 → 该候选版本被 pin 回，报告写 `REGRESSED: <pkg> <metric> <delta>`。

## 与升级环的接口

`conductor/upgrade_ring.py` 调用本目录的方式：
1. `python bench/metrics.py --replay-dir bench/replay --mode baseline` → 产出 `bench/baseline.json`
2. 升级某包后：`python bench/metrics.py --replay-dir bench/replay --mode after --baseline bench/baseline.json`
   → 产出四指标对比表 + REGRESSED/OK 判定，退出码 0=不劣化 / 1=劣化

`bench/replay.sh` 是 loopd `bench.replay` 意图的入口，单次重放 N 张卡并打印每张的结果行：
`R-NNN <PASS|FAIL> <diff_lines> <reopen> <cost_yuan>`。

## 验收

`python conductor/upgrade_ring.py --dry-run --fake-feed bench/fixtures/fake_feed.json`
应演示一次"候选→冷静期→重放→劣化回退"全流程空跑，输出含 `TOO_YOUNG` / `REGRESSED` / `OK` 三类行。
