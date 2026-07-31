# WAVE-14 端到端验收剧本

> 对应 [`waves/WAVE-14.md`](../waves/WAVE-14.md) 的“本波次的检查方法”。
> 目标：验证一个人类在配置完成后，系统能否 7 天零人工干预地跑通“接单 → 实现 → 异构验证 → 门禁 → 合并 → 验收 → 通知 → 度量 → 升级 → 自愈”全闭环。

## 验收环境

- **探针仓**：`product-probe`（WAVE-13 建立的复制仓）。
- **运行时长**：连续 7 天，任何人工介入都导致重新计时。
- **真源文件**：[`bench/e2e.json`](../bench/e2e.json) 记录本次运行的全部事件与指标基线。
- **证据目录**：探针仓 `.loop/evidence/e2e/`（运行中自动生成）。

## 预检（开始前必须全绿）

```bash
# 1. 探针仓存在且为 Template Repository 复制
gh repo view Cloudbird-Software/product-probe --json name,defaultBranchRef,isTemplate

# 2. loop 控制面自身 CI 全绿（main 分支最新 commit）
gh run list -R Cloudbird-Software/loop --branch main --limit 5

# 3. 探针仓已登记进 products.yml
grep product-probe products.yml

# 4. 必要 secrets 已配置（不输出值，只看存在性）
gh secret list -R Cloudbird-Software/product-probe
```

## 1. 卡从 ready 走到 merged（≥3 张，含 1 张 verify 打回后重做成功）

### 执行命令

```bash
# 在探针仓持续观察卡状态
gh issue list -R Cloudbird-Software/product-probe --label card --state open --json number,title,labels,updatedAt

# 统计 7 天内 merged PR 数（合并后由 scribe.yml 写入 journal）
gh pr list -R Cloudbird-Software/product-probe --state merged --search "merged:>=$(date -d '7 days ago' +%Y-%m-%d)" --limit 100 --json number,title,mergedAt,headRefName
```

### 判定标准

- ≥3 张 PR 被合并到 `main`。
- 其中至少 1 张的 comments 里含 `VERDICT FAIL → 建 F-0NN`，后续同卡或新卡 `VERDICT PASS` 后合并。

### 负向场景

- **门禁被绕过**：`no-fake-green` 变红 → 自动开 Incident，不计入成功卡。
- **模型直接合并没有 verify**：`gate_heterogeneity` 检查 `verifier_model != impl_model` 会红。

### 证据

- 探针仓 merged PR 列表截图或 JSON 导出 → `.loop/evidence/e2e/merged_prs.json`。
- 每张卡的 issue 状态变更时间线 → `.loop/evidence/e2e/card_transitions.json`。

## 2. lens 自动发现开出真实 Finding（finding_id 为真实 issue 号）

### 执行命令

```bash
# 触发 audit（或等待 nightly audit）
gh workflow run audit.yml -R Cloudbird-Software/loop -f product=product-probe

# 查看新开的 finding issue
gh issue list -R Cloudbird-Software/product-probe --label finding --state open --json number,title,body,labels
```

### 判定标准

- 存在至少 1 个 `label:finding` 的 issue。
- 该 issue body 的 ````json loop```` 块里 `finding_id` 等于 issue number 本身。
- 非临时哈希。

### 负向场景

- **lens 脚本缺失**：`audit.yml` 会 `LENS_NOT_EXECUTED` 失败，不会静默跳过。
- **重复发现**：同一 fingerprint 不会重复开 issue，只会追加 comment。

### 证据

- finding issue URL + body 中 `finding_id` 字段 → `.loop/evidence/e2e/lens_finding.json`。

## 3. 强模型 claim → 异构复现 → 修复

### 执行命令

```bash
# 触发 review workflow（开发期间可选，若未启用则手动植入一条 claim 验证流程）
gh workflow run review.yml -R Cloudbird-Software/loop -f product=product-probe

# 查看 claim 与 reproduction 记录
gh issue list -R Cloudbird-Software/product-probe --label claim --state all --json number,title,labels
```

### 判定标准

- ≥1 条由 reviewer 产出的 claim 被记录为 issue（`label:claim`）。
- 该 claim 经 reproducer（与 reviewer 不同模型）判定为 `REPRODUCED`。
- 修复 PR 合并后，claim issue 关闭。

### 负向场景

- **claim 未被复现**：`state:unconfirmed` 的 claim 不能被 impl 领取；若被强行路由，`claim_intake.assert_reproduced` 会抛 `CLAIM_NOT_REPRODUCED`。
- **复现者是自己**：异构校验由 CI 强制，verifier_model == impl_model 会红。

### 证据

- claim issue 的全 comments → `.loop/evidence/e2e/claim_reproduced.json`。
- 关联修复 PR 号 → `bench/e2e.json` 的 `events[].linked_pr`。

## 4. 波次自动验收 + 通知送达

### 执行命令

```bash
# 手动触发 nightly-rubric
gh workflow run nightly-rubric.yml -R Cloudbird-Software/loop

# 查看 WAVE-14 父 issue 是否被自动关闭
gh issue view 88 -R Cloudbird-Software/loop --json state,comments
```

### 判定标准

- `wave_acceptance.py --wave WAVE-14` 输出 `passed=true`。
- 通知以 comment 形式出现在 WAVE-14 父 issue 或新建的 `[Notify]` issue 中。
- 全部通过且 human_verify ≤1/3 时，WAVE-14 父 issue 自动关闭。

### 负向场景

- **human_verify 过多**：>1/3 时验收失败，自动生成人类待办清单 comment，不关闭 issue。
- **验收项未实现**：对应检查项 `ok=false`，通知中列出未通过项。

### 证据

- `.loop/retro/wave_acceptance.json`（workflow 产物）。
- WAVE-14 issue 的 comments → `.loop/evidence/e2e/wave_notification.json`。

## 5. 依赖 bump PR 走完冷静期 + bench 重放

### 执行命令

```bash
# 查看待处理的 bump PR
gh pr list -R Cloudbird-Software/product-probe --search "bump" --state open --json number,title,labels

# 检查 bench 重放结果（PR checks 中的 bench-compare job）
gh run view -R Cloudbird-Software/product-probe <run-id> --log
```

### 判定标准

- ≥1 条 bump PR 在 `min_age_days` 冷静期后自动创建。
- 合并前 bench/metrics.py `compare` 不劣化。
- 劣化时 PR 被阻止合并并开 Incident。

### 负向场景

- **冷静期未过**：`gate_minage` 红，PR 不能合并。
- **重放劣化**：`bench/metrics.py compare` 返回 `REGRESSED`，workflow 失败。

### 证据

- bump PR 的 checks 日志 → `.loop/evidence/e2e/bump_bench.json`。

## 6. 故障后自动自愈（canary / drift / 门禁红）

### 执行命令

```bash
# 触发 canary
gh workflow run canary.yml -R Cloudbird-Software/loop

# 查看 Incident issue
gh issue list -R Cloudbird-Software/loop --label incident --state all --json number,title,labels,createdAt
```

### 判定标准

- 期间至少发生 1 次异常并被系统自动处理（开 Incident / 重试 / 自愈关闭）。
- 人工介入次数 = 0。

### 负向场景

- **自愈失败**：Incident 持续 open > 阈值，通知升级给 `LOOP_HUMAN`。
- **假绿**：`no-fake-green` 扫描发现 `|| true` 等吞错模式。

### 证据

- Incident issue 全生命周期 → `.loop/evidence/e2e/incident_lifecycle.json`。

## 7. bench 四指标与 CHARTER Q 指标落在阈值内

### 执行命令

```bash
# 在探针仓运行 bench charter
python bench/metrics.py charter --evidence-dir .loop/evidence/e2e --out bench/e2e-charter.json

# 对比基线
python bench/metrics.py compare --baseline bench/baseline.json --after-json bench/e2e.json
```

### 判定标准

- `bench/e2e.json` 中四指标不劣于 `bench/baseline.json`。
- `bench/e2e-charter.json` 中所有带 threshold 的 Q 指标 `ok=true`。

### 负向场景

- **指标未达阈值**：wave acceptance 失败，开 Incident。

### 证据

- `bench/e2e.json`
- `bench/e2e-charter.json`

## 8. 7 天无人值守总判定

### 通过条件（缺一不可）

1. 人工介入次数 = 0。
2. 第 1–7 节全部满足。
3. `no-fake-green` 全程常绿。
4. `bench/e2e.json` 已提交为基线。

### 未通过处理

- 逐条记录阻塞项，转成新卡。
- 修复后 7 天重新计时。
- 结论写入 [`DECISIONS.md`](../DECISIONS.md)：宣告“端到端 ready”或列出阻塞项。

## 附录：证据文件清单

| 文件 | 说明 |
|---|---|
| `bench/e2e.json` | 总事件时间线与四指标基线 |
| `.loop/evidence/e2e/merged_prs.json` | 7 天内合并的 PR |
| `.loop/evidence/e2e/card_transitions.json` | 卡状态变更时间线 |
| `.loop/evidence/e2e/lens_finding.json` | lens 产出的 finding |
| `.loop/evidence/e2e/claim_reproduced.json` | claim 复现与修复记录 |
| `.loop/evidence/e2e/wave_notification.json` | 波次验收通知 |
| `.loop/evidence/e2e/bump_bench.json` | 依赖 bump bench 结果 |
| `.loop/evidence/e2e/incident_lifecycle.json` | Incident 生命周期 |
| `bench/e2e-charter.json` | CHARTER Q 指标计算结果 |
