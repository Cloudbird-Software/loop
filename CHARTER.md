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

## Never Doing（N 段：绝不做）

- N3: 不让任何开源件接管跨卡调度
- N4: 不做无外部可观测收益的重构（纯"更优雅"不算理由）
- N5: 不自动修正 GitHub branch ruleset（检测漂移开 Incident，但永不自动修）
- N6: 不从非官方源安装任何依赖
- N7: 不在 product-x 样板里塞真实产品逻辑（样板只示范 LOOP 体系，不变成产品本身）
