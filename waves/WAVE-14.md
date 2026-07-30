# WAVE-14 — 闭环、度量与"端到端 ready"

> 前三个波次让系统**可信**，本波次让它**可用**：定期检查的产出能自动变成工单、波次能自动验收并通知、四个指标是真实数字、零覆盖模块被补上测试、接单入口收敛为一句话。

**依赖**：WAVE-11 + WAVE-12 全绿（否则"度量"度的是假数据）。R14-6 依赖本波次其余全部卡片。

**来源**：`docs/审查裁决-2026-07-30.md` 的 P3-A / P3-B / P3-C、P1-6、P2-12、P2-15。

**"端到端 ready"的定义**（本项目对该词的唯一口径，写死在此，后续验收以此为准）：
一个人类只需 ① 从模板建仓、② 填写 CHARTER.md、③ 配好凭证，
此后**不再需要任何人工介入**，系统即可自动完成：接单 → 实现 → 异构验证 → 门禁 → 合并 → 波次验收 → 通知 →
定期检查产出新工单 → 强模型验收产 claim → 独立复现 → 修复 → 指标回填 → 依赖升级 → 失败自愈。
其中任何一环需要人手动推一把，就不算 ready。

---

## 本波次的检查方法（Wave-level Gate）

**唯一的承重验收是一次真实的无人值守连续运行**：

1. 在 `product-probe`（WAVE-13 建立的探针仓）上启动系统，**连续 7 天零人工干预**。
2. 期间必须自然发生并被系统自动处理完毕的事件，逐项留证：
   - ≥3 张卡从 ready 走到 merged（含至少 1 张被 verify 打回后重做成功的）
   - ≥1 张由 lens 自动发现并开出的 Finding，其 finding_id 是**真实 issue 号**而非临时哈希
   - ≥1 条由强模型验收产出、经异构复现确认、并最终修复的 claim
   - ≥1 次波次自动验收 + 通知送达
   - ≥1 次依赖 bump PR 走完冷静期与 bench 重放
   - ≥1 次故障后的自动自愈（不论来源：canary / drift / 门禁红）
3. 期间**不得出现假绿**：`no-fake-green` 全程常绿。
4. 期间人工介入次数 = 0。若有介入，记录原因并转为新卡，7 天重新计时。
5. 结束时，`bench` 四指标均有真实数字且落在 CHARTER 的 Q 阈值内。

只有第 5 条达成且第 4 条为 0，才可宣布"端到端 ready"。

---

## 卡片

```json loop
{
  "schema": 1,
  "id": "R14-1",
  "objective": "lens 产出真正流入工单",
  "title": "audit 的 finding_id 改为真实 issue 号，缺脚本即红，lens 结果自动开单",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G1", "G3"],
  "paths": [".github/workflows/audit.yml", "conductor/findings.py"],
  "blocked_by": null,
  "acceptance": [
    "audit.yml 中缺脚本即 `continue` 的静默跳过（当前 104-106 行）改为：打印 LENS_NOT_EXECUTED 并使 job 红",
    "finding_id 当前是临时哈希（audit.yml:156-157），导致 tick.py:457-460 拿它做 `gh issue edit` 会指向不存在的 issue。改为：先创建真实 issue，再以其编号作为 finding_id 贯穿全流程",
    "新增 conductor/findings.py 统一 finding 的创建/查重/更新/关闭；同一 lens 同一位置的重复发现按指纹合并，不重复开单",
    "12 个 lens 脚本（实测为 12 个，非专家所称 13 个）逐一确认可执行；不可执行者要么补齐要么从 profile 中显式移除并记录理由，不允许『声明了但跑不了』",
    "lens 发现的问题以 Finding 形式进入与强模型 claim **相同**的下游流程（复现 → 确认 → 修复），确定性 lens 的 claim 默认 verdict 直接为 REPRODUCED（因其本身即确定性证据），但仍须走同一状态机",
    "现有 F-001/F-002/F-003 均为 verify agent 手写、非 lens 产出；本卡合并后新 Finding 中 lens 产出占比可观测"
  ],
  "verify": "人为在仓库植入一个 lens 必然报出的问题，确认自动开出真实 issue，且该 issue 号能被 tick.py 正确编辑"
}
```

```json loop
{
  "schema": 1,
  "id": "R14-2",
  "objective": "波次自动验收与通知",
  "title": "retro 从 stub_pending 变成真实的波次验收 + 通知送达",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G0", "G1"],
  "paths": ["conductor/retro.py", ".github/workflows/nightly-rubric.yml"],
  "blocked_by": "R11-7",
  "acceptance": [
    "nightly-rubric.yml 中 retro-friday job 的 `client_payload[status]=stub_pending` 替换为真实验收结果（澄清：该 stub 位于 workflow 第 99 行，不在 retro.py 源码中——专家归属略偏，实质结论成立）",
    "波次验收自动执行该 Wave 文件中声明的『本波次的检查方法』：每一条都要有机器可执行的对应实现或明确标注为 human-verify；全部通过才自动关闭 Wave 父 issue",
    "human-verify 项不得超过该波次检查项的 1/3，且必须自动生成待办清单推给人类，而不是静默挂起",
    "通知通道落地（至少一条真实可送达的通道，具体选型记入 DECISIONS.md）：波次通过/失败、需要人类介入、Incident 升级三类事件必须送达",
    "恢复 promptfoo 真实调用（R11-7 已提供配置），移除 `EXIT=0` 的假绿",
    "验收报告归档进 evidence，含每条检查项的命令与真实输出"
  ],
  "verify": "构造一个必然不通过的波次，确认它不会被自动关闭且通知送达；再让它通过，确认自动关闭"
}
```

```json loop
{
  "schema": 1,
  "id": "R14-3",
  "objective": "四指标真实回填与 bench 重放",
  "title": "bench/metrics.py + 升级环重放：让 CHARTER 的 Q 指标成为真实数字",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G1", "G0"],
  "paths": ["bench/metrics.py", "conductor/upgrade_ring.py"],
  "blocked_by": null,
  "acceptance": [
    "bench/metrics.py 从 evidence 计算 CHARTER 中全部 Q 指标（含新增的 Q3/Q4/Q5），输出机器可读的时间序列",
    "指标计算必须可回放：给定同一份 evidence，任意时刻重算得到相同数字",
    "upgrade_ring.py 在任何依赖 bump（含 loop 自身 pin 的 bump）前后各跑一次 bench，劣化超阈值则拒绝合并并开 Incident",
    "与 R12-7 的 experiment 维度共用同一张度量表：任意 A/B 实验的效果可用同一套指标横向比较——这是本架构对『未来继续研究提效方法』保持兼容的关键",
    "指标看板产出为仓库内的静态文件（每次运行覆盖写），不引入外部依赖",
    "Q 指标未达阈值时不静默：开 Incident 并在波次验收中体现"
  ],
  "verify": "回放两次确认数字一致；人为制造一次劣化，确认 bump 被拒绝"
}
```

```json loop
{
  "schema": 1,
  "id": "R14-4",
  "objective": "零覆盖模块补测试",
  "title": "为 6 个零测试覆盖的模块（实测 1922 行）建立最小可信测试",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3"],
  "paths": ["tests/test_zero_coverage.py", "loopd/loopd.py"],
  "blocked_by": null,
  "acceptance": [
    "为当前在 tests/ 与 seam_a/ 中零引用的 6 个模块（合计实测 1922 行，其中 loopd.py 约 1027 行）建立测试；优先覆盖 CAS 领卡、lease/heartbeat、_validate_finding、_validate_verdict 这些承重路径",
    "覆盖率不追求数字指标，追求『每条承重路径都有一个会失败的测试』：每个新测试必须先被证明能在对应逻辑被破坏时变红（在 PR 描述中给出破坏实验记录）",
    "loopd.py 中若为可测性做必要的小重构（提取纯函数、注入依赖），必须是行为等价的，且在 PR 描述中逐处说明——不得借机做无外部收益的重构（CHARTER N4）",
    "pytest -q 全绿；同时把当前 68 条 DeprecationWarning 收敛（澄清：静态 utcnow 调用点实测 28 处，其中 21 处在 test_B_pkg.py；『68』是运行时告警次数被误当成源码调用点数）",
    "loop 的 pr-ci.yml test job 增加 `-W error::DeprecationWarning` 或等价的告警预算门槛，防止回潮"
  ],
  "verify": "reviewer 随机挑 3 个新测试，各破坏一次对应逻辑，确认测试变红"
}
```

```json loop
{
  "schema": 1,
  "id": "R14-5",
  "objective": "单一接单入口",
  "title": "loop 根目录补 README.md 与 AGENTS.md，把 30 个环境变量收敛为一句话启动",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G0", "G2"],
  "paths": ["README.md", "AGENTS.md", "docs/环境变量清单.md"],
  "blocked_by": null,
  "acceptance": [
    "新增 README.md：loop 是什么、不是什么、目录地图、从零到接单的最短路径、以及本次架构的四份设计文档索引",
    "新增 AGENTS.md：进仓 AI 的唯一入口。内容含角色、可改与不可改的路径、必须遵守的 CHARTER 红线、提示词入口（prompts/P-*.md）、以及『如何领一张卡』的一句话命令",
    "新增 docs/环境变量清单.md：逐条登记实测的 30 个 LOOP_* 环境变量，标注 必填/选填、默认值、由谁提供、影响面；把其中可由配置文件推导的收敛掉，目标是新沙盒只需设置 ≤5 个变量",
    "Trae沙盒填写卡.md 与 bootstrap.sh 的必需步骤收敛进 README 的『最短路径』一节；原文件移入 docs/archive/ 保留",
    "验收标准是可操作的：一个从未见过本仓库的 AI，只读 AGENTS.md 就能领到一张卡并开始工作，不需要额外的人工口述",
    "product-x 侧已有 README.md 与 AGENTS.md，本卡产出需与之保持结构一致（控制面与产品仓的入口体验统一）"
  ],
  "verify": "找一个全新会话的 agent，只给它 AGENTS.md 的链接，观察它能否独立领卡开工；不能则本卡不通过"
}
```

```json loop
{
  "schema": 1,
  "id": "R14-6",
  "objective": "端到端 ready 验收",
  "title": "E2E 验收剧本 + 7 天无人值守连续运行",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "verify",
  "charter": ["G0", "G1", "G3", "G4", "G5"],
  "paths": ["docs/E2E验收剧本.md", "bench/e2e.json"],
  "blocked_by": "R14-2",
  "acceptance": [
    "docs/E2E验收剧本.md 逐条写明本波次『检查方法』中的 5 大项、每项的执行命令、判定标准、以及证据存放位置",
    "剧本必须包含负向场景：门禁被绕过时会怎样、模型说谎时会怎样、依赖升级把系统搞挂时会怎样、凭证过期时会怎样——每种都要有预期的自愈或告警行为",
    "在 product-probe 上完成一次 7 天零人工干预的连续运行，全部事件留证（见本波次检查方法第 2 条的 6 类事件）",
    "bench/e2e.json 记录该次运行的全部指标与事件时间线，作为后续回归的基线",
    "人工介入次数为 0；若非 0，逐次记录原因并转为新卡，7 天重新计时",
    "结论写入 DECISIONS.md：正式宣告『端到端 ready』或列出阻塞项"
  ],
  "verify": "本卡由 verify 角色执行，且执行者必须与本波次任何 impl 卡的执行者异构（CHARTER N12）。人类只做最终签署，不参与判定"
}
```
