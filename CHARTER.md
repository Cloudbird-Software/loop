# CHARTER.md — 一人软件公司目标-需求-问题

> 草稿，待用户确认 @2026-07-30
> 以下 G/N/Q 由 planner 起草，需用户拍板后移除"草稿"标记。

---

## G0: 跑通"继续→自动找活→impl→verify→merge"全闭环

> 单 AI 一句"继续"能识别 ready 卡并领、做完、验完、合完，全程零人工干预。

### Needs

- N0.1: AI 加载 P-continue.md 后说"继续"能自动扫 repo/找 ready 卡/切角色干活
- N0.2: impl 角色能从 WAVE 卡中领卡、实现、commit、开 PR
- N0.3: verify 角色能盲一半验证、产 VERDICT（PASS/FAIL+客观证据）
- N0.4: VERDICT=PASS → PR 自动合并；FAIL → 建 F-0NN 客观复现
- N0.5: conductor tick 自动回收僵尸、放行依赖、48h 静默

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

## Never Doing（N 段：绝不做）

- N2: 不让任何开源件接管跨卡调度
- N3: 不做无外部可观测收益的重构（纯"更优雅"不算理由）
- N4: 不自动修正 GitHub branch ruleset（检测漂移开 Incident，但永不自动修）
- N5: 不让 agent 直接执行 git/删除类命令（loopd 正式体系；暂行期沙盒已改可绕过）
- N6: 不从非官方源安装任何依赖

---

## 待用户确认的开放问题

1. Q0.1/Q0.2 的量化指标（≤1 分钟 / ≤30 分钟）是否接受？还是想调？
2. 是否要加 G2（如 SLA / 可用性目标 / 安全目标）？
3. Q0.2 的"≤30 分钟"是 wall clock 还是 AI 会话时长？
4. N5（不让 agent 直接执行 git）在暂行期已因沙盒修改而暂存，正式体系恢复后是否重新启用？
