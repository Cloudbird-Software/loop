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

## G6: 成熟度阶梯

> 链路成熟度 = 机器可查的运行证据，不是代码存在性。只有达到 OBSERVED 及以上的链路才允许被其他链路依赖。

### Needs

- N36.1: 链路成熟度标签必须由机器证据支撑（run id / URL / sha256），不由声明决定
- N36.2: 标签升级由 `gate_maturity_evidence` 强制；无 run 证据不得升级
- N36.3: 只有 OBSERVED 及以上的链路可被其他链路依赖

### Quantitative metrics

- Q6.1: 可被依赖的链路中，100% 达到 OBSERVED 及以上且有对应 run id

---

## G7: 卡 provenance

> 卡必须由系统身份创建，无卡 PR 只能触碰白名单琐碎路径。杜绝"人直建 issue 绕过机制"。

### Needs

- N37.1: 卡 issue 必须由 App 身份（CONDUCTOR_APP / materializer bot）创建
- N37.2: 无 `Card: #NNN` 的 PR 仅允许白名单琐碎路径（docs/assets/README），其余 fail-closed
- N37.3: 无卡代码 PR 物理不可合并

### Quantitative metrics

- Q7.1: 无卡改 `src/**` 的 PR 100% 被拦（fail-closed）

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

### 宪法层增补（W1-7 立法，手册附录 A 权威）

- N16: 产品仓 PR 不得修改 `.github/**`、`LOOP.yml`、`CODEOWNERS`、`contracts/**`、`db/migrations/**`、`.loop/**`、`flags.yml`、`exceptions.yml`、`UPSTREAM.yaml`
- N17: 凡跑在 agent 沙盒内的检查，必须有不依赖 agent 输入的 CI 孪生检查；沙盒内的那份只用于快速失败，不用于授权；孪生检查必须 fail-closed
- N18: 棘轮条款：所有阈值、required check 集合、评审数只能单向收紧
- N19: 判断型验证（LLM 评审）只有否决权，没有通过权；`done/verified` 只能由 CI 身份写入
- N20: 波次是规划标签，不是分支实体；禁止 `wave/*` 长命分支；PR 存活以小时计
- N21: 卡片 diff 上限按 tier 硬性执行，超限必须拆卡；本条款不设 EXC 通道
- N22: 测试的编写者与实现的编写者必须是不同 agent、不同 vendor；实现方对 `tests/**` 与 `holdout/**` 无写权限；holdout 对实现方不可见
- N23: 深层集成失败的默认动作是丢弃重做（respec），不是派 agent 去修
- N24: 禁止摆设门禁：任何 30 天零拦截的门禁必须被红队证明有效，否则删除
- N25: 不可逆动作（数据迁移、真实付款、对外发信、删除数据）必须人类批准
- N26: 所有例外必须具名、有 TTL（≤90 天）、有人类署名、有 ADR
- N27: 成本与用量数据不采信 agent 自述，只采信 gateway receipt
- N28: 诚实条款：链路成熟度标签必须有机器可查的证据支撑（run id/URL/sha256）；标签升级由 `gate_maturity_evidence` 强制
- N29: 双证条款：任何"完工/通过/有效"的声明必须同时提供正向证据与至少一条负向证据（该拦的被拦了）；只有正向证据的声明不予受理
- N30: 单一写者条款：状态权威只有一个写入身份（CONDUCTOR_APP）；任何其他身份写出的状态变更一律视为篡改并 quarantine
- N31: 持久化条款：任何需要跨运行累积的状态必须落在 loop-state 分支；禁止写入 `.gitignore` 覆盖的路径（`gate_persistence` 强制）
- N32: 第三方规则集许可证约束：Semgrep 官方规则不得 vendored 进可公开仓
- N33: 元层不可自证：`META_MUTABLE_PATHS` 白名单结构性排除一切评价器（`run_gates.py`、`bench/**`、`rubrics/**`、`holdout/**`、`policy.yml` 评分字段、`exceptions.yml`）
- N34: 评估三分与防污染：search/validation/holdout 三分，holdout 哈希封存；bench 内容出现在 `prompts/**`、`skills/**`、代码注释中 = eval-leak 红
- N35: 概念漂移看门狗：bench 指标涨而线上真实卡通过率不涨且超阈值 → Incident

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
G6 成熟度阶梯：只有 OBSERVED 及以上的链可被依赖
G7 卡 provenance：卡必须由 App 身份创建，无卡 PR 白名单制
N3 不让开源件接管跨卡调度
N4 不做无外部可观测收益的重构
N5 不自动修正 ruleset
N6 不从非官方源安装依赖
N7 不在样板里塞真实产品逻辑
<!-- 注：N8/N9/N10 无顶级"No Never Doing"条目——它们是 G3/G4/G5 目标段下的
     子条款前缀（N8.* / N9.* / N10.*，如 N8.1-N8.6、N9.1-N9.7、N10.1-N10.5）。
     编号从 N1.x 起每目标段内部连续；顶级连续从 N11 开始。 -->
N11 不把假绿当作权宜之计
N12 不允许实现方自证
N13 不把模型的论断当作事实
N14 不在产品仓复制 loop 机制文件
N15 不把高权限凭证放进仓库级 secret
N16 产品仓禁改机制/契约/门禁路径
N17 沙盒检查必有 CI 孪生且孪生 fail-closed
N18 棘轮：阈值/required check/评审数只许收紧
N19 判断型验证只有否决权，done/verified 仅 CI 身份可写
N20 波次是标签非分支，禁止 wave/* 长命分支
N21 卡 diff 上限按 tier 硬性执行且不设 EXC
N22 测试与实现异 agent 异 vendor，实现方对 tests/holdout 无写权
N23 深层失败默认 respec
N24 禁止摆设门禁：30 天零拦截须红队证明否则删除
N25 不可逆动作必须人类批准
N26 例外具名+TTL+人类署名+ADR
N27 成本只采信 gateway receipt
N28 诚实条款：成熟度标签须机器证据支撑
N29 双证：完工声明须正证+负证
N30 单一写者：状态权威仅 CONDUCTOR_APP，他写即篡改
N31 持久化：跨运行状态落 loop-state，禁写 gitignored 路径
N32 第三方规则集不得 vendored 进公开仓
N33 元层不可自证：评价器结构性排除于可写面
N34 评估三分与防污染：holdout 哈希封存，eval-leak 红
N35 概念漂移看门狗：bench 涨线上不涨超阈 → Incident
Q0 闭环成功率与领卡时延
Q1 自治自愈时延
Q2 样板 fork 后改动点 ≤5
Q3 可信度：假绿为零且门禁有负向测试
Q4 强模型验收：claim 必先被复现
Q5 产品仓对齐：pin 新鲜且机制副本为零
Q6 成熟度阶梯：只有 OBSERVED 及以上的链可被依赖（子项 Q6.1）
Q7 卡 provenance：无卡改 src/** 的 PR 100% 被拦（子项 Q7.1）

