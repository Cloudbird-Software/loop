# WAVE-12 — 强模型验收环：把"模型说的话"降级为"待检验的输入"

> 强模型验收全自动化，但它的产物只是**可证伪的断言**。断言必须被异构模型独立复现才配触发修复；被确认的断言必须尽量固化为确定性检查器，让系统对模型的信任**单调下降**。

**依赖**：WAVE-10 必须全绿（否则复现沙盒跑出的"红/绿"本身不可信）；R12-1 是本波次其余全部卡片的硬前置。
R12-2 / R12-3 / R12-5 可在 R12-1 完成后并行；R12-4 依赖 R12-1+R12-3；R12-6 依赖 R12-5；R12-7 依赖 R12-4+R12-5。

**设计依据**：`docs/强模型验收环.md`、`DECISIONS.md` ADR-004 ~ ADR-006、`.loop/schemas/claim.json`、`.loop/schemas/reproduction.json`。

**本波次为何存在**：本次审查本身就是它的原型。一位强模型专家提了 25 条指控，独立复现后 14 条坐实、8 条实质成立但细节有误、**3 条承重结论不成立**，另有 1 条两人都漏掉。如果当时按"专家说了算"直接开修，会有三条修错方向。这个概率不是偶然，它是把模型输出当事实的必然代价。

---

## 本波次的检查方法（Wave-level Gate）

1. **拒收有效**：投喂一份故意缺 `repro` 的 claim 与一份含"代码不够优雅"这类不可证伪措辞的 claim，
   `conductor/claims.py` 必须双双拒收并给出具体缺失字段。
2. **复现是硬前置**：构造一条已通过 schema 的 claim，直接尝试让它进入修复流；
   系统必须拒绝，日志含 `CLAIM_NOT_REPRODUCED`。
3. **异构强制**：让同一 model 既产 claim 又做复现，`gate/heterogeneity` 必须红。
4. **三态可用**：人为构造一条环境相关的 claim，复现结果必须能落到 `INCONCLUSIVE`，
   并触发仲裁（多采样），而不是被迫二选一。
5. **信任单调下降**：本波次结束时，`lenses/` 下由 claim 固化而来的确定性检查器数量 ≥3，
   且其中至少一条能在无任何 LLM 参与的情况下复现出本次审查中的一条真实缺陷
   （推荐：`no-fake-green` 与 `GATE_NOT_EXECUTED` 检测——它们正是 F-A/P1-1 的确定性化）。
6. **精度可观测**：`ROUTING.yaml` 中 review 相关 route 的 `metrics` 不再为空，
   含 `claims_total` / `claims_reproduced` / `precision` 三个真实数字。
7. **不卡合并线**：确认 review 相关 check **不在** required checks 列表中（对应 N9.7）。

---

## 卡片

```json loop
{
  "schema": 1,
  "id": "R12-1",
  "objective": "claim / reproduction 校验器",
  "title": "实现 conductor/claims.py —— 断言的收发口与拒收规则",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4", "N13"],
  "paths": ["conductor/claims.py", "tests/test_claims.py"],
  "blocked_by": null,
  "acceptance": [
    "依 .loop/schemas/claim.json 与 .loop/schemas/reproduction.json 实现校验；缺 repro.cmd / repro.expected / falsifier / predicted_observation / severity / confidence 任一项即拒收，并返回结构化的缺失原因",
    "语义拒收：对主观词表（优雅/清晰/更好/建议重构/最佳实践 等，词表放 policy.yml 可配）命中且无可执行 repro 的 claim 一律拒收",
    "claim id 强制 `^CL-\\d{3}$`，同一评审轮内唯一；提供 next_id 分配",
    "提供 CLI：`python3 conductor/claims.py validate <file>` / `ingest <file>`，退出码 0/1 明确",
    "tests/test_claims.py 覆盖：合法 claim、缺 repro、缺 falsifier、主观措辞、id 冲突、confidence 越界、reproduction 三态各一，共 ≥10 个用例",
    "校验器**不判断 claim 是否为真**，只判断它是否『有资格被检验』。任何试图在此处引入真值判断的实现直接拒收"
  ],
  "verify": "reviewer 用本次审查真实产生的 25 条指控中的 5 条（含 3 条被证伪的）逐一投喂，确认校验器能接收它们（它们确实可证伪），并确认那 3 条被证伪的 claim 在复现阶段而非校验阶段被拒——校验器不该越权"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-2",
  "objective": "强模型验收 workflow",
  "title": "review.yml：Copilot CLI headless 自动验收，只产 claim，永不做 required check",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G4", "N13"],
  "paths": [".github/workflows/review.yml", "prompts/P11.md"],
  "blocked_by": "R12-1",
  "acceptance": [
    "新增 prompts/P11.md（评审角色提示词）：明确唯一输出是符合 claim.json 的 JSON 数组；显式禁止输出 PASS/FAIL、禁止输出散文结论、禁止建议性措辞；每条 claim 必须自带可粘贴执行的 repro 与 falsifier",
    "新增 .github/workflows/review.yml：以 seam-B executor 形式调用 Copilot CLI headless（`copilot -p`/`--no-tty`，工具权限用 --allow-tool/--deny-tool 收紧到只读），provider 由 ROUTING.yaml 的 review/accept route 决定，**不得把 copilot 硬编码进 workflow 逻辑**——换 provider 只应改 ROUTING.yaml",
    "输出经 conductor/claims.py 校验后才落盘；校验失败时 job 红（评审本身失败必须红，见 N9.7 后半句）",
    "该 job 明确不在 required checks 中；workflow 顶部注释写明理由：模型不确定性不得卡合并线",
    "预算护栏：读 policy.yml 的 review.max_reviews_per_day / min_confidence，超限则跳过并打印明确的 BUDGET_EXCEEDED（非静默）",
    "凭证使用 COPILOT_GITHUB_TOKEN，权限最小化并登记进 docs/密钥清单.md（与 R11-4 协作）",
    "@github/copilot 已在 UPSTREAM.yaml 登记且钉 ≥1.0.43（低于此版本存在两个已知 RCE 公告）"
  ],
  "verify": "在一个已知含缺陷的分支上跑一次，确认产出的是 claim 数组而非结论；再把 ROUTING.yaml 的 review/accept 换成另一 provider，确认 workflow 无需修改即可工作"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-3",
  "objective": "reviewer / reproducer 角色阀门",
  "title": "materialize.py 单向阀门扩展：新增 reviewer 与 reproducer 角色及其可创建对象",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4", "N12"],
  "paths": ["conductor/materialize.py"],
  "blocked_by": "R12-1",
  "acceptance": [
    "ROLE_CREATE_MAP 新增 `reviewer`（只能创建 Claim 对象，不能创建 Card / Wave / Milestone / Incident）与 `reproducer`（只能创建 Reproduction 记录与对已确认 claim 的 Finding）",
    "新增对象类型 Claim / Reproduction，与既有 Card / Wave / Incident 并列，各有独立的创建权限",
    "任何角色都不得对自己产出的对象做下一步判定：同一 (model, session_id) 既是 claim 作者又是 reproducer 时直接拒绝并打印 SELF_ADJUDICATION_REFUSED",
    "为新增阀门补测试（测试文件由 R12-1 的 tests/test_claims.py 承载，本卡不新增测试文件以免路径冲突；在该文件中追加用例）",
    "materialize.py 的既有四项校验与 paths 两两不交叉逻辑不得被削弱，回归测试必须覆盖"
  ],
  "verify": "尝试以 reviewer 角色创建 Card，必须被拒；尝试自证，必须被拒"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-4",
  "objective": "claim 物化为待复现工单",
  "title": "conductor/claim_intake.py —— claim 落为 unconfirmed 状态的 F 卡，绝不直接进修复",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4", "N13"],
  "paths": ["conductor/claim_intake.py"],
  "blocked_by": "R12-3",
  "acceptance": [
    "把校验通过的 claim 物化为 product-x issue，携带 `json loop` 块，`state: unconfirmed`，标签 `claim`",
    "unconfirmed 状态的工单**不可被 impl 角色领取**——tick/loopd 的领卡查询必须排除它；本卡需在 PR 描述中给出该排除生效的实证（尝试领取并被拒的日志）",
    "只有当该工单挂上一条 verdict 为 REPRODUCED 的 reproduction 记录后，才由 conductor 自动流转为 `ready`；NOT_REPRODUCED 则自动关闭并注明；INCONCLUSIVE 进入仲裁队列",
    "复用既有『首次发现协议』的 F 卡格式与 finding.json schema，不另起炉灶（loopd.py:456 的 _validate_finding 与 :674 的 _validate_verdict 必须被真正调用——当前生效的 P-continue 暂行流绕过了它们，本卡需修复这条绕过）",
    "澄清记录：专家称『没有任何代码校验 finding/verdict』**不成立**，校验代码一直存在，真实问题是生效流不走 loopd 网关。本卡按真实成因修复"
  ],
  "verify": "构造一条 claim 走完 intake，确认工单为 unconfirmed 且 impl 领不到；再补一条 REPRODUCED 记录，确认自动转 ready"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-5",
  "objective": "独立复现沙盒",
  "title": "conductor/reproduce.py + P12 提示词 —— 异构模型三态复现与仲裁",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4", "N12", "N13"],
  "paths": ["conductor/reproduce.py", "prompts/P12.md"],
  "blocked_by": "R12-1",
  "acceptance": [
    "新增 prompts/P12.md：复现者只被给到 claim 的 repro 与 predicted_observation，**不被给到** claim 的结论措辞与 severity（避免锚定）；输出必须是 reproduction.json 结构",
    "reproduce.py 在干净沙盒中执行 repro.cmd，记录真实 exit_code 与 stdout 摘要，与 predicted_observation 比对后由**模型**给出 REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE 三态判定 + diff_note",
    "`next_action` 字段由 conductor 依据裁决表计算，**不由沙盒模型填写**——模型只报观察，不做流程决策",
    "INCONCLUSIVE 触发仲裁：按 policy.yml 的 arbitration_samples（默认 3）多次采样，多数决；仍不收敛则升级为人类待办并打 `needs-human` 标签",
    "复现者 provider 由 ROUTING.yaml 的 review/reproduce route 决定，且被 gate/heterogeneity 强制与 claim 作者不同",
    "沙盒必须无写权限访问生产仓库；repro.cmd 的执行环境、超时、资源上限写进 policy.yml"
  ],
  "verify": "用本次审查中被证伪的三条（『必须用 PAT 破窗』『68 处 utcnow』『.loop/gates/ 为空』）作为回归集投喂，系统必须全部判为 NOT_REPRODUCED —— 这是本卡的验收基准，因为它们已有人工复现结论作为标准答案"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-6",
  "objective": "确认的断言固化为确定性检查器",
  "title": "conductor/harden.py —— 让系统对模型的信任单调下降",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4"],
  "paths": ["conductor/harden.py", "lenses/README.md"],
  "blocked_by": "R12-5",
  "acceptance": [
    "对被 REPRODUCED 且同类累计确认次数 ≥ policy.yml 的 harden_after_confirms（默认 2）的 claim，自动开一张『固化卡』，要求把该类问题实现为 lenses/ 下的确定性检查器",
    "固化卡的验收强制包含：新检查器能在**不调用任何 LLM** 的情况下重现该缺陷",
    "lenses/README.md 建立检查器登记表：来源 claim id、固化日期、覆盖的缺陷类别、误报率",
    "已被固化的缺陷类别在后续评审中降权：同类 claim 若确定性检查器已常绿，则该 claim 的 confidence 自动打折并在 intake 时标注 `already_hardened`，避免强模型反复刷同一类问题消耗预算",
    "本卡交付时必须自带 ≥3 条真实固化案例，推荐直接固化本次审查已坐实的：假绿模式扫描、GATE_NOT_EXECUTED 检测、settings 与线上 ruleset 往返一致"
  ],
  "verify": "关闭 LLM 通道后单跑这 3 条检查器，确认能独立复现出对应缺陷"
}
```

```json loop
{
  "schema": 1,
  "id": "R12-7",
  "objective": "模型精度记分与实验维度",
  "title": "把 claim 精度回填 ROUTING.metrics，并引入可 A/B 的 experiment 维度",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G4", "G1"],
  "paths": ["ROUTING.yaml", "seam_a/router.py", "conductor/routing_metrics.py"],
  "blocked_by": "R12-5",
  "acceptance": [
    "新增 conductor/routing_metrics.py：按 (route, provider, model) 聚合 claims_total / claims_reproduced / claims_refuted / precision / cost，回填 ROUTING.yaml 的 metrics 段（当前 6 条 route 的 metrics 全为空，且全仓无任何回填代码）",
    "router.py 从『只读』变为『读+写』：路由决策时读 metrics，precision 低于 policy.yml 的 precision_floor（默认 0.5）的 model 在 review 域自动降权或停用，并开 Incident 告知",
    "ROUTING.yaml 每条 route 新增可选 `experiment` 字段（如 `{name, variant, traffic_share}`），使未来任意新方法（新提示词、新模型、新工具链）都能以 A/B 形式接入而**无需改动调度骨架**——这是本架构对未来研究保持兼容的承重设计",
    "experiment 的结果指标与 bench 四指标共用同一张度量表（与 R14-3 协作，本卡只定义 schema 与写入路径）",
    "metrics 回填必须是幂等且可回放的：从 evidence 重跑一次应得到相同数字",
    "为避免路由自我强化偏置，降权决策需要最小样本量（写进 policy.yml，默认 10），样本不足时不降权且明确打印 INSUFFICIENT_SAMPLES"
  ],
  "verify": "灌入两批模拟 claim（一批高精度、一批低精度），确认 metrics 数字正确且低精度 model 被降权；再回放一次确认幂等"
}
```
