# STATE-OF-THE-SYSTEM

> loop 控制面系统状态真源（living doc）。本文件描述 `conductor/state_of_system.py`
> 所报告的可观测状态，以及控制面各条 **chain**（链）的健康度。所有结论必须可由
> `python3 conductor/state_of_system.py --verify` 复现；探不到的字段标 `unknown`，
> 不假绿（CHARTER G3 / N11）。

## 生成方式

运行：

```bash
python3 conductor/state_of_system.py --verify     # AC-1：产出报告即 exit 0
python3 conductor/state_of_system.py              # 同上，打印完整状态报告
```

`state_of_system.py` 采集以下可观测事实（best-effort，不可达即 `unknown`）：

- `policy.yml`：`freeze.all`、`gates.profiles.default` 数量
- `products.yml`：注册产品仓列表
- `.loop/liveness.yml`：cron 期望周期登记数（ticks）
- `gates/`：实际存在的 gate 文件
- `gh` 可达性 + open issues 计数（gh 不可达即 `unknown`）

## chain 健康度总览

控制面由多条 chain 串联而成；任一 chain 断裂都会让「诚实化」失效。下表是各 chain
的状态条目（living，由 `state_of_system.py` 报告的字段推导）：

| chain | 状态来源 | 健康判定 |
|---|---|---|
| gate chain | `gates/` 目录 + `policy.yml gates.profiles.default` | gate 文件齐全且 profile 未偷偷缩小集合 → 绿；缺 gate 即红 |
| CI chain | `gh run list`（best-effort） | 最近 N 次 run 全 success → 绿；连败 → 红 |
| card chain | `gh issue list` open cards（best-effort） | 卡片状态机推进无僵尸 → 绿；lease 过期堆积 → 红 |
| liveness chain | `.loop/liveness.yml` ticks + `gh run list` | 各 workflow 在期望周期内有 run → 绿；超期 → 红 |
| verify chain | `gates/gate_verdict.py` + `gate_heterogeneity.py` | standard/critical 卡有异构 VERDICT → 绿；自证/缺 VERDICT → 红 |
| evidence chain | `gates/gate_maturity_evidence.py` | 标签升级有真实 run 证据 → 绿；无证据 → `NO_RUN_EVIDENCE` → 红 |

## gate chain 状态

gate chain 是 PR 合并前的最后一道防线。`policy.yml gates.profiles.default` 声明了
loop 仓全集 gate（charter / diffsize / license / minage / paths / testown / upstream /
verdict / lockdiff / heterogeneity / smoke）。`run_gates.py` 按 profile 执行，**任何 gate
未执行等价于失败**（F-A 治本：门禁静默 SKIP 即红）。

`gate_maturity_evidence.py`（W0-1 新增）属于 evidence chain：标签/claim 升级到「成熟」
必须有真实 CI run 证据 backing。无证据时返回 `NO_RUN_EVIDENCE` 错误码并 FAIL（exit 1）。
该 gate 目前未加入 `default` profile（W0 阶段），其行为由 WAVE-00 负证 N1 验证：

```bash
python3 gates/gate_maturity_evidence.py            # 默认无证据 → FAIL exit 1, NO_RUN_EVIDENCE
EVIDENCE_RUN_ID=12345 python3 gates/gate_maturity_evidence.py   # 有证据 → PASS exit 0
```

## CI chain 状态

CI chain 由 `.github/workflows/` 下的若干 workflow 组成（conductor / audit / canary /
scribe / drift / nightly-rubric / policy / upgrade / template-sync）。`conductor/tick.py`
的 `liveness_check` 与每日 digest 检测 CI chain 是否在期望周期内连续绿。

`state_of_system.py` 通过 `gh run list` best-effort 采集；gh 不可达时报告 `unknown`
（不编造 run 结果）。CI chain 连败会触发 Incident issue。

## card chain 状态

card chain 是「wave → 卡片 → impl → verify → 合并」的状态机流。`conductor/tick.py`
负责僵尸回收 / 升档 / 依赖放行 / 路径租约兜底 / tier 判定，保证 card chain 不堆积
僵尸、不越界改路径。`state_of_system.py` 报告 open issues 计数（gh 可达时），用于
粗略反映 card chain 当前负载。

## liveness chain 状态

liveness chain 由 `.loop/liveness.yml` 登记的 9 条 cron 期望周期构成（W0-2）。每个
workflow 的 `expect_hours` 是契约：超过即由 tick 开 Incident。`state_of_system.py`
读取并报告 ticks 登记数；当 `ticks_count` 与预期不符（应为 9）时，liveness chain
本身即处于退化态。

## verify chain 状态

verify chain 强制 impl 与 verify 模型异构（CHARTER N12 / N8.5）。`gate_heterogeneity.py`
校验 ROUTING.yaml 中 impl 与 verify 的 provider 且 model 均不相同；`gate_verdict.py`
校验 standard/critical 卡必须有 VERDICT 评论且 head_sha 匹配。verify chain 断裂 =
实现方自证 = 红线。

## evidence chain 状态

evidence chain 是 W0-1 的核心：**标签/claim 升级必须有真实 CI run 证据**。在引入
`gate_maturity_evidence.py` 之前，标签可被无证据升级（placebo-gate 病链）。现在
evidence chain 通过 `NO_RUN_EVIDENCE` 错误码把「无 run 证据」从静默状态变成显式 FAIL。

证据来源（按优先级）：
1. `EVIDENCE_RUN_ID` 环境变量非空
2. `EVIDENCE_FILE` 指向的文件存在且非空
3. 默认 marker `.loop/evidence/run-evidence.json` 存在且非空
4. 以上都无 → `NO_RUN_EVIDENCE` → FAIL

## 诚实化原则（G3 / N11）

本文件与 `state_of_system.py` 共同遵守：

- 探不到的字段标 `unknown`，绝不假绿。
- 不用 `|| true` / `set +e` / `continue-on-error` / 吞退出码。
- best-effort 采集失败时降级为 `unknown`，不编造数字或 run 结果。
- 所有 chain 状态条目必须可由 `state_of_system.py --verify` 复现。
