# CHARTER.md — LOOP 体系目标-需求-问题

> product-x 仓库是未来产品仓库的**样板**。本 CHARTER 定义样板要示范的 LOOP 体系目标，
> 未来真实产品仓库 fork 后可继承本 CHARTER 再按产品特性扩展。
> @2026-07-30 定稿，不再标草稿。

---

## G0: 跑通"继续→自动找活→impl→verify→merge"全闭环

> 单 AI 一句"继续"能识别 ready 卡并领、做完、验完、合完，全程零人工干预。
> product-x 样板必须完整示范这条链路。

### Needs

- N0.1: AI 加载 P-continue.md 后说"继续"能自动扫 repo/找 ready 卡/切角色干活
- N0.2: impl 角色能从 WAVE 卡中领卡、实现、commit、开 PR
- N0.3: verify 角色能盲一半验证、产 VERDICT（PASS/FAIL+客观证据）
- N0.4: VERDICT=PASS → PR 合并；FAIL → 建 F-0NN 客观复现 → 复现成功立即修
- N0.5: C 卡 done 自动触发 V 卡 ready（验证流转不停在 done 这一步）
- N0.6: conductor tick 自动回收僵尸、放行依赖、48h 静默

### Quantitative metrics

- Q0.1: 从"继续"到领卡 ≤1 分钟（wall clock）
- Q0.2: 从领卡到 done ≤30 分钟（trivial/standard 卡，wall clock）
- Q0.3: 闭环成功率 ≥80%（10 张卡中至少 8 张走通 impl→verify→merge）

---

## G1: 自治自愈（僵尸/依赖/48h 放行由 conductor tick 自动跑）

> 人类不做任何日常运维。conductor tick 每轮自动回收僵尸、放行阻塞、静默超期。

### Needs

- N1.1: conductor tick 在 cron 或 loop tick 上跑，非 dormant
- N1.2: 僵尸卡（超租约不心跳）自动退回 ready
- N1.3: 依赖卡 done 后下游自动 ready
- N1.4: 波次 PR 48h 无人类动作自动物化 trivial 子集

### Quantitative metrics

- Q1.1: 僵尸回收延迟 ≤30 分钟（从心跳停止到卡退回 ready）
- Q1.2: 依赖放行延迟 ≤1 轮 tick（从上游 done 到下游 ready）

---

## G2: product-x 样板可复用性

> product-x 不是真实产品，是未来产品仓库的样板。任何产品 fork 后能继承本 CHARTER + cards/ + prompts/ 体系。

### Needs

- N2.1: product-x 含完整的 contracts/ + verify.sh + tests/acceptance/ 示范
- N2.2: product-x 的 AGENTS.md、UPSTREAM.yaml、waves/ 格式可作为模板复制
- N2.3: WAVE-2 示范了从 trivial 到 verify.required=true 的全 tier 卡片
- N2.4: F-001/F-002 示范了首次发现协议的完整流转

### Quantitative metrics

- Q2.1: fork 后改 ≤5 处即可适配新产品（产品名、目标 G、CI 配置）

---

## G3: 可信度地基（本轮审查后新增 @2026-07-30）

> 绿灯必须真的代表"通过"。写门禁的自己必须过门禁。
> 依据：`docs/审查裁决-2026-07-30.md`（F-A / F-D / P1-1 / P1-2 全部坐实）。

### Needs

- N8.1: 控制面 loop 仓自身有 `pull_request` 门禁（此前 9 个 workflow 全是 schedule/dispatch，0 个 PR 触发）
- N8.2: 零假绿——不存在 `|| true`、`set +e` 吞退出码、探不到即 SKIP 且 exit 0 的模式；正当例外必须写明 `fake-green-ok: <理由>`
- N8.3: 任何 gate **未执行等价于失败**（不是"跳过并放行"）
- N8.4: 每个 required check 都有一条"故意让它红"的负向测试
- N8.5: verify 模型 ≠ impl 模型由 CI 强制，而非仅由文档声明
- N8.6: 工单只有一个真源（product-x issues），`cards/` 冻结

### Quantitative metrics

- Q3.1: 假绿数 = 0（`no-fake-green` job 常绿）
- Q3.2: required check 的负向测试覆盖率 = 100%
- Q3.3: 仓库内 settings/*.json 与线上 ruleset 逐字一致（`gate/settings-roundtrip`）

---

## G4: 强模型验收环（本轮讨论定案 @2026-07-30）

> 强模型可以自动验收，但它的输出只是"待检验的输入"，不是事实。
> 详见 `docs/强模型验收环.md`、`DECISIONS.md` ADR-004~006。

### Needs

- N9.1: 强模型验收全自动（Copilot CLI headless / Actions），零人工触发
- N9.2: 其唯一合法产物是 `.loop/schemas/claim.json` 定义的**可证伪断言**；不产 PASS/FAIL、不产散文
- N9.3: 缺 `repro`（可粘贴执行的命令）或缺 `falsifier` 的断言一律拒收
- N9.4: 任何 claim 必须被**异构模型独立复现**（三态：REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE）才能进入修复
- N9.5: 复现确认后，能确定性化的必须固化为 lens/checker，使系统对模型的信任依赖**单调下降**
- N9.6: 每个 reviewer_model 的 claim 精度被持续记分并回填 `ROUTING.yaml` 的 `metrics` 段
- N9.7: 强模型验收**永不做 required check**（模型不确定性不能卡合并线），但其自身失败必须红

### Quantitative metrics

- Q4.1: 进入修复的 claim 中，100% 有一条 `REPRODUCED` 记录
- Q4.2: 被拒收（缺 repro/falsifier/主观措辞）的 claim 比例可观测，且随提示词迭代下降
- Q4.3: 被固化为确定性 checker 的 claim 累计数 ≥ 每季度 3 条

---

## G5: 产品仓持续对齐（本轮讨论定案 @2026-07-30）

> 产品仓不持有 loop 机制的副本，只持有对 loop 的 pin 引用。
> 详见 `docs/产品仓对齐架构.md`、`DECISIONS.md` ADR-007~009。

### Needs

- N10.1: 产品仓有 `LOOP.yml` 钉住 `loop` 的 tag + 完整 40 位 SHA
- N10.2: 产品仓的 CI/gates/review 全部经 loop 的 reusable workflow 调用，本地零逻辑
- N10.3: `loop` 自身登记进各产品仓的 `UPSTREAM.yaml`，走第 8 环冷静期 + 重放 + 自动回退
- N10.4: `gate/loop-conformance` 校验 pin 新鲜度、必需文件、薄壳未被魔改、机制副本数为 0
- N10.5: `products.yml` 是产品仓注册表的唯一真源，fan-out 只开 PR 不直推

### Quantitative metrics

- Q5.1: 产品仓 `loop_version` 落后主干 ≤2 个 tag 且 ≤30 天
- Q5.2: 产品仓内 loop 机制文件副本数 = 0
- Q5.3: 由 template-sync 开出的 PR 与普通 PR 走完全相同的门禁（豁免数 = 0）

---

## Never Doing（N 段：绝不做）

- N3: 不让任何开源件接管跨卡调度
- N4: 不做无外部可观测收益的重构（纯"更优雅"不算理由）
- N5: 不自动修正 GitHub branch ruleset（检测漂移开 Incident，但永不自动修）
- N6: 不从非官方源安装任何依赖
- N7: 不在 product-x 样板里塞真实产品逻辑（样板只示范 LOOP 体系，不变成产品本身）
- N11: 不把假绿当作权宜之计——宁可流水线红着、波次停住，也不允许把失败伪装成成功
- N12: 不允许实现方自证——impl 不得给自己的卡产 VERDICT，评审模型不得给自己的 claim 做复现判定
- N13: 不把模型的论断当作事实——不可证伪的一律拒收，未被独立复现的不得触发任何代码改动
- N14: 不在产品仓复制 loop 的机制文件（gates/lenses/conductor/loopd/prompts/settings）
- N15: 不把高权限凭证放进仓库级 secret——能用 GITHUB_TOKEN 的绝不用 PAT，能用 App 的绝不用 PAT

---

<!-- ============================================================ -->
<!-- 机器可读索引：conductor/materialize.py 的 load_charter_ids()  -->
<!-- 用正则 ^([GNUQ]\d+)\s 逐行解析下列条目。卡片 charter 字段只能  -->
<!-- 引用此处出现的编号，否则 gate/charter-hash 直接红。            -->
<!-- 新增 G/N/Q 时必须同步登记于此。                                -->
<!-- ============================================================ -->

## 索引（machine-readable，勿删）

G0 跑通继续到合并的全闭环
G1 自治自愈
G2 product-x 样板可复用性
G3 可信度地基：零假绿、门禁真实、控制面自过门禁
G4 强模型验收环：可证伪断言 + 独立复现 + 固化为检查器
G5 产品仓持续对齐
N3 不让开源件接管跨卡调度
N4 不做无外部可观测收益的重构
N5 不自动修正 ruleset
N6 不从非官方源安装依赖
N7 不在样板里塞真实产品逻辑
N11 不把假绿当作权宜之计
N12 不允许实现方自证
N13 不把模型的论断当作事实
N14 不在产品仓复制 loop 机制文件
N15 不把高权限凭证放进仓库级 secret
Q0 闭环成功率与领卡时延
Q1 自治自愈时延
Q2 样板 fork 后改动点 ≤5
Q3 可信度：假绿为零且门禁有负向测试
Q4 强模型验收：claim 必先被复现
Q5 产品仓对齐：pin 新鲜且机制副本为零

