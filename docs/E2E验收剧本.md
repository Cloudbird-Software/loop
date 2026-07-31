# E2E 验收剧本 — 端到端 ready 的唯一承重验收

> 本文件是 WAVE-14 R14-6 的产物，也是本项目对「端到端 ready」一词的唯一可操作定义。
> 任何宣称「ready」的结论，必须以本剧本的一次完整执行记录为依据（见 `bench/e2e.json`）。

## 0. 前置与角色约束

- **执行角色**：本卡由 **verify 角色**执行，且执行者必须与本波次任何 impl 卡的执行者**异构**（CHARTER N12）。
  - 即：若 R14-1~R14-5 由模型 X 实现，则本卡由模型 Y 验收。
  - 人类只做最终签署，不参与判定、不参与修复。
- **被测对象**：`product-probe`（WAVE-13 建立的探针仓，从 product-x 模板新建，只填 CHARTER.md）。
- **观测窗口**：连续 **7 天 × 24 小时**，零人工干预。
- **唯一结论口径**（写死，后续验收以此为准）：
  一个人类只需 ① 从模板建仓、② 填写 CHARTER.md、③ 配好凭证，
  此后**不再需要任何人工介入**，系统即可自动完成：接单 → 实现 → 异构验证 → 门禁 → 合并 → 波次验收 → 通知 →
  定期检查产出新工单 → 强模型验收产 claim → 独立复现 → 修复 → 指标回填 → 依赖升级 → 失败自愈。
  其中任何一环需要人手动推一把，就不算 ready。

---

## 1. 五大承重验收项

### 项 1 — ≥3 张卡从 ready 走到 merged（含 ≥1 张 verify 打回后重做成功）

| 字段 | 值 |
|---|---|
| 执行命令 | 在 product-probe 上连续运行 7 天，观察 `gh pr list --state merged --search "created:>=<T0>"` |
| 判定标准 | merged 卡数 ≥3；其中 ≥1 张的 PR 历史含「verify 打回（requested_changes / REPRODUCED=false）→ 同卡重做 → 再 merged」轨迹 |
| 证据存放 | `bench/e2e.json` → `events.cards[]`，每条含 `card_id / pr_number / timeline: [claimed, ...merged] / had_rework: bool` |
| 机器可执行 | 是（`gh pr view <n> --json timeline,comments` 解析打回与重做） |

### 项 2 — ≥1 张由 lens 自动发现并开出的 Finding，finding_id 是真实 issue 号

| 字段 | 值 |
|---|---|
| 执行命令 | `gh issue list -R product-probe --label lens-finding --state all --json number,title,createdAt` |
| 判定标准 | ≥1 张 Finding issue 由 audit workflow 自动开出；其 `finding_id` 是真实 issue 编号（非临时哈希 `abs(hash)%1e6`） |
| 证据存放 | `bench/e2e.json` → `events.findings[]`，每条含 `issue_number / lens / fingerprint / created_by: "audit"` |
| 机器可执行 | 是（R14-1 已让 finding_id 落为真实 issue 号；校验 issue 编号 < 1e6 且 `gh issue view` 可达） |

### 项 3 — ≥1 条强模型验收产出、经异构复现确认、最终修复的 claim

| 字段 | 值 |
|---|---|
| 执行命令 | 遍历 `.loop/review/claims-*.json`，筛 `verdict=REPRODUCED` 且关联修复 PR |
| 判定标准 | ≥1 条 claim 满足：reviewer_model 产出 → 异构 reproducer 复现确认（verdict=REPRODUCED）→ 触发修复 → 修复 PR merged |
| 证据存放 | `bench/e2e.json` → `events.claims[]`，每条含 `claim_id / reviewer_model / reproducer_model(≠reviewer) / verdict / fix_pr_number` |
| 机器可执行 | 是（异构性校验：`reviewer_model != reproducer_model`，CHARTER N6） |

### 项 4 — ≥1 次波次自动验收 + 通知送达

| 字段 | 值 |
|---|---|
| 执行命令 | `python3 conductor/retro.py wave-acceptance <wave> --parent-issue <n>` |
| 判定标准 | 波次验收自动执行该 Wave 的『检查方法』；通过则自动关闭父 issue；通知送达（父 issue 上有 retro bot 评论） |
| 证据存放 | `bench/e2e.json` → `events.wave_acceptance[]`，含 `wave_id / status / parent_issue_closed: bool / notify_comment_id` |
| 机器可执行 | 是（R14-2 已实现 `run_wave_acceptance` + `notify`） |

### 项 5 — ≥1 次依赖 bump PR 走完冷静期与 bench 重放

| 字段 | 值 |
|---|---|
| 执行命令 | 观察升级环：`conductor/upgrade_ring.py` 对 loop pin 或外部依赖开 bump PR |
| 判定标准 | ≥1 次 bump PR：新 tag 过 `min_age_days` 冷静期 → 跑 bench 重放 → 四指标不劣化 → PR 可合并（或劣化被拒绝+开 Incident） |
| 证据存放 | `bench/e2e.json` → `events.bumps[]`，含 `pkg / old_pin / new_pin / age_days / bench_passed / pr_number / regressed: bool` |
| 机器可执行 | 是（R14-3 已让 upgrade_ring 前后各跑 bench + check_q_thresholds） |

### 项 6 — ≥1 次故障后的自动自愈

| 字段 | 值 |
|---|---|
| 执行命令 | 观察任一故障源（canary / drift / 门禁红 / 凭证过期）→ 系统自动恢复 |
| 判定标准 | ≥1 次故障被系统自动处理完毕（开 Incident → 自愈或回退 → Incident 关闭），无需人工介入 |
| 证据存放 | `bench/e2e.json` → `events.self_heals[]`，含 `source(canary/drift/gate/credential) / incident_issue / action_taken / resolved_without_human: bool` |
| 机器可执行 | 是（遍历 Incident issue 的生命周期） |

---

## 2. 全程不得假绿

| 字段 | 值 |
|---|---|
| 执行命令 | `bash lenses/no-fake-green.sh` 全程常绿 |
| 判定标准 | 7 天内 `no-fake-green` check 从未红；无 `|| true` / `set +e` / `continue-on-error` / `EXIT=0` 假绿模式 |
| 证据存放 | `bench/e2e.json` → `invariants.no_fake_green_always_green: true` + 每日采样 |
| 机器可执行 | 是 |

---

## 3. 人工介入次数 = 0

| 字段 | 值 |
|---|---|
| 执行命令 | 人工介入记数（git push by human / 手动 gh issue close / 手动 rerun workflow by human） |
| 判定标准 | 7 天内人工介入次数 = 0。若有介入，逐次记录原因并转为新卡，7 天重新计时 |
| 证据存放 | `bench/e2e.json` → `invariants.human_interventions: 0`（若 >0，`intervention_log[]` 列出每次原因） |
| 机器可执行 | 部分（git push 作者与 commit author 可机器区分；手动 rerun 需观察 workflow trigger actor） |

---

## 4. 结束时四指标达标

| 字段 | 值 |
|---|---|
| 执行命令 | `python3 bench/metrics.py compute-q --evidence-dir evidence --check` |
| 判定标准 | bench 四指标（Q0~Q5）均有真实数字且落在 CHARTER 的 Q 阈值内 |
| 证据存放 | `bench/e2e.json` → `final_metrics.{Q0..Q5}`，每项含 `value/target/status` |
| 机器可执行 | 是（R14-3 已实现 `compute_q_metrics` + `check_q_thresholds`） |

> **唯一 ready 宣告口径**：只有第 4 条（四指标达标）达成且第 3 条（人工介入=0）为 0，才可宣布「端到端 ready」。

---

## 5. 负向场景（必须覆盖，验证自愈或告警而非静默）

### 5.1 门禁被绕过

| 场景 | 在 product-probe 的一个 PR 中塞入 `|| true` 假绿模式 |
|---|---|
| 预期行为 | `no-fake-green` lens / gate 红，PR 被阻塞；自动开 Incident；不得合并 |
| 自愈/告警 | 阻塞 + Incident，无需人工 |
| 证据 | `bench/e2e.json → negative.gate_bypass.blocked=true` |

### 5.2 模型说谎

| 场景 | 强模型产出一个虚构的 claim（无可执行 repro / 主观词命中） |
|---|---|
| 预期行为 | claim 被 `claim_intake` 拒收（主观词表 R12-1 / 无 repro R12-7）；不得触发任何代码改动（CHARTER N9.4） |
| 自愈/告警 | 自动拒收 + 记入 routing_metrics 降权样本；无修复 PR 产生 |
| 证据 | `bench/e2e.json → negative.model_lying.rejected=true` |

### 5.3 依赖升级把系统搞挂

| 场景 | 一个依赖 bump PR 的 bench 重放显示四指标劣化超阈值 |
|---|---|
| 预期行为 | upgrade_ring 自动 `pin_back`（拒绝合并）+ 开 Incident；bump PR 被自动关闭或保持开但不合并 |
| 自愈/告警 | 自动回退 + Incident |
| 证据 | `bench/e2e.json → negative.bump_regressed.rolled_back=true` |

### 5.4 凭证过期

| 场景 | `CONDUCTOR_APP_KEY` 或 `GH_TOKEN` 过期，跨仓写操作失败 |
|---|---|
| 预期行为 | template-sync / upgrade_ring 的 gh 调用失败 → 开 Incident（非静默 `|| echo skipped`）；通知送达「需要人类介入」 |
| 自愈/告警 | 无法自愈（凭证只能人类更新）→ 必须**告警**并记为「需要人类介入」事件（不计入 ready 的「零人工」） |
| 证据 | `bench/e2e.json → negative.credential_expired.incident_opened=true / needs_human=true` |

---

## 6. 执行流程（verify 角色操作手册）

1. **建 probe**：从 product-x 模板新建 `product-probe`，只填 CHARTER.md（last-human-edit 改真实日期），配好凭证（≤5 个环境变量，见 `docs/环境变量清单.md`）。
2. **启动系统**：`loopd` 在 product-probe 上常驻；audit / nightly-rubric / upgrade / template-sync workflow 启用。
3. **计时 T0**：记录开始时间，此后 7 天不触碰。
4. **每日采样**：verify 角色每日跑一次采样脚本（只读，不写）：
   ```
   gh pr list -R product-probe --state merged --json number,title,mergedAt
   gh issue list -R product-probe --label lens-finding --state all --json number
   bash lenses/no-fake-green.sh
   python3 bench/metrics.py compute-q --evidence-dir evidence --check
   ```
   结果追加到 `bench/e2e.json → daily_samples[]`。
5. **T0+7d 结束**：汇总 6 类事件 + 2 条不变量 + 四指标，写入 `bench/e2e.json`。
6. **结论**：若四指标达标且人工介入=0 → 在 `DECISIONS.md` 宣告「端到端 ready」；否则列出阻塞项转新卡。

---

## 7. 证据基线

`bench/e2e.json` 是本次运行的唯一基线，结构见该文件。后续回归以此为对照。

> **当前状态**：本剧本已就绪，`bench/e2e.json` 为骨架（字段结构 + 空事件数组）。
> 真实 7 天运行的填充需由 verify 角色（异构执行者）在 product-probe 上执行本剧本第 6 节后完成。
> 在该次运行完成并签署前，不得宣告「端到端 ready」。
