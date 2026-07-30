# HUMAN-TODO —— 只有你能做的事

> 本文件只列**AI 无法代做**的事项。凡是能自动化的，都已经进了 `waves/WAVE-1*.md`。
> 每一条都写明：为什么必须是你、不做会怎样、做完怎么验证。
> 完成一条就把 `[ ]` 改成 `[x]` 并填上日期——`gate/loop-conformance` 与波次验收会读这个文件。

---

## A. 阻塞级（不做，WAVE-13 无法验收，产品仓无法端到端 ready）

### [ ] A1. 审定并签署 product-x 的 CHARTER.md

**文件**：`templates/product-x/CHARTER.md`（AI 已代拟全文），落地后为 `product-x/CHARTER.md`

**为什么必须是你**：章程是整个系统里唯一不可由 AI 终局裁定的文件。它定义"什么算成功"
与"绝不做什么"。如果 AI 既定义目标又评判达成，整套验收就是自证。我按你在两轮对话中
表达的意图代拟了 P/U/G1-G4/Q1-Q8/N1-N10，但**每一条你都必须亲自过一遍**。

**具体动作**：逐条读，改到你认可为止，然后把文件末尾的
`last-human-edit: PENDING` 改成真实日期（如 `last-human-edit: 2026-07-31`）。

**不做会怎样**：`gate/loop-conformance` 的检查 3 会持续报红——这是**刻意设计**，
不是 bug。没有签署过的章程的产品仓不该被认为是就绪的。

**验证**：`python3 gates/gate_conformance.py --repo product-x` 的检查 3 转绿。

**我特别希望你重点看的三条**（我代拟时做了判断，但你可能有不同意见）：
- N7「不在样板里塞真实产品逻辑」——这决定了 product-x 永远是样板而非产品。
- Q2「样板复制后改动点 ≤5」——这个数字是我定的，你可能想更严或更松。
- GRIPE BOX 的处置承诺——我写的是"每周必须清空"，这是对你的约束，不是对 AI 的。

### [ ] A2. 把 product-x 设为 GitHub Template Repository

**动作**：product-x → Settings → General → 勾选 `Template repository`。

**为什么必须是你**：需要仓库 admin 权限，且这是产品形态决策（ADR-008：用模板不用 fork）。

**不做会怎样**：新产品仓只能靠 fork 或手工复制，会带来 fork 的上游语义与误 PR 问题，
且 WAVE-13 的"真做一次复制"验收无法执行。

**验证**：仓库首页出现 `Use this template` 按钮。

### [x] A3. 验证机制决定：VERDICT-on-PR + ci.yml verify job（不再需要 API key）

**决定（2026-07-30，用户裁定）**：验证不通过 API 路由执行。API LLM 只能输出文本，
无法运行命令/测试，不能执行真实验证。验证机制改为：
verifier 沙盒领 V 卡 → 跑命令 → 在 PR 上贴结构化 VERDICT 评论 →
ci.yml 的 verify job（required check）解析 VERDICT，断言 pass + verifier≠impl + head_sha 匹配。
异构约束在 CI 层强制，不依赖 loopd 过滤。

**影响**：`DEEPSEEK_API_KEY` 不再是阻塞项。ROUTING.yaml 的 verify 路由保留供可选的静态文本
预审，但不是验证主体。实施该方案的 ci.yml verify job 改造是 R11-2 的开发任务。

**验证**：R11-2 完成后，一次真实 verify 的 PR 评论中有 `json verdict` 块且 ci.yml verify job 据此判绿。

### [x] A4. Copilot CLI 暂缓——改为 GitHub Action 调用（开发期间不启用）

**决定（2026-07-30，用户裁定）**：Copilot CLI 的 token 暂不开通。强模型验收环改为通过
GitHub Action 调用 copilot。等 WAVE-12 推进到建立该 Action 时再自然开启。
开发期间不跑强模型验收，不影响其他波次。

**已落地的变更**：
- `ROUTING.yaml` review 路由标注开发期间暂不启用
- `docs/强模型验收环.md` 顶部加了开发期间状态说明
- `UPSTREAM.yaml` copilot 条目标注暂不启用

**不做会怎样**：WAVE-12 的强模型验收环在 Action 建好前不运行。这**不阻塞**其他波次——
评审环按设计永不做 required check（CHARTER N9.7）。

---

## B. 安全级（不做，系统能跑但有实质风险）

### [x] B1. 重新导出线上 ruleset 并核对 `settings/main-protection.json`

**已完成（2026-07-30）**：通过 `gh api` 拉取 product-x 线上 ruleset (id=19949520) 全量 JSON，
写回 `settings/main-protection.json`（补回缺失的 `required_status_checks` 规则，含 6 个 check：
lint/test/verify/contract/paths-lease/verdict-binding）。

同时**新增** `settings/loop-main-protection.json`，记录 loop 仓自己的 ruleset (id=20052299)，
让 `drift_check.py` 同时监控两个仓的 ruleset 漂移。

本地验证：`python3 conductor/drift_check.py` → "No drift detected. All settings match live rulesets."
已关闭 drift Incident #55。

**残余风险**（R10-4 承接）：`policy.yml` 的 apply 路径仍是 `echo TODO`。一旦实现 apply，
必须确保它从 `settings/*.json` **完整**应用（包括 required_status_checks），而不是删掉它。
R10-4 的验收要求：`gate_settings_roundtrip.py` 还未实现，需 R10-4 创建。

### [ ] B2. 密钥降权与轮换

**动作**（细节见 R11-4 产出的 `docs/密钥清单.md`）：
1. `LOOP_CANARY_TOKEN`：确认其权限范围，凡 `GITHUB_TOKEN` 能胜任之处一律替换。
2. 为全部凭证设定轮换周期并执行首次轮换（当前全仓 grep 不到任何轮换策略）。
3. 复用情况收敛：`LLM_GATEWAY_KEY` 当前同时服务 strongest provider 的 2 条 plan 路由
   与 nightly-rubric workflow，建议拆分以便独立吊销。

**澄清（避免你被误导）**：专家称 canary "用 admin PAT 绕过分支保护" —— 这是**假的**。
`canary-chain.sh:76-79` 明确拒绝 `--admin`，改走 GraphQL `enqueuePullRequest` 进 merge queue；
线上 ruleset 的 `bypass_actors` 是空数组，任何 token 都绕不过。
真实风险只是"高权限 PAT 存为 repo secret"这一密钥卫生问题。我已把 `canary.yml` 里那条
过时注释改成事实。

### [x] B3. 授予 loop 仓所需的 secret 访问

**已完成**：drift.yml 最近两次运行（2026-07-30 14:07 / 09:29）均 `success`，
说明 loop 仓已能访问 `POLICY_R_APP_ID` / `POLICY_R_APP_KEY`。
drift 检测正常工作（#55 Incident 即由它自动开出，现已因 drift 修复而关闭）。

---

## C. 接线级（WAVE-10/11 合并后才需要做）

### [x] C1. 为 loop 仓设置 required checks

**已完成（2026-07-30）**：通过 GitHub REST API 创建了 loop 仓的 main-protection ruleset
（id=20052299，enforcement=active）。包含 6 条规则：

- `deletion` / `non_fast_forward` / `required_linear_history`
- `pull_request`（0 required reviews，允许 merge/squash/rebase）
- `required_status_checks`：`test` / `lint` / `no-fake-green` / `actions-pinned` / `schemas`
  五个 check，`strict_required_status_checks_policy=true`，`bypass_actors=[]`
- `merge_queue`（SQUASH / ALLGREEN）

**关键经验**：GitHub UI 添加 required check 时，下拉框**只显示历史运行过的 check**。
由于 pr-ci.yml 从未在 PR 上跑过，UI 里搜不到这些 check 名。**解决方法是用 REST API
直接创建 ruleset**——API 的 `required_status_checks.context` 接受任意字符串，
不需要历史运行记录。命令示例：

```bash
gh api --method POST repos/<org>/<repo>/rulesets --input <ruleset.json>
```

**关于 CHARTER N5**：N5 禁止的是**自动化**修正 ruleset（检测漂移→自动改）。
本次是用户**一次性显式授权**的人工等价操作（用户提供 admin token 并指示"你能做就你做"），
不违反 N5 的精神。N5 的防线——"不许把 apply 路径接成自动闭环"——仍然有效，
`policy.yml` 的 apply 仍是 `echo TODO`。

### [ ] C2. product-x 的 required check 名单同步

**时机**：R13-3 把薄壳 workflow 跑通、准备删除旧 `ci.yml` 时。

**动作**：确保新 job 名与 required 名单同时更新。**顺序很重要**：
先加新 check 为 required 并等它上报一次绿，再删旧 check —— 反过来会造成
PR 永久卡在 AWAITING_CHECKS。

### [ ] C3. 维护 `products.yml`

**约定**：每新建一个产品仓，**必须**在 loop 的 `products.yml` 登记，否则
template-sync 扇不到它，且定时任务会把它当"影子产品仓"开 Incident 告警。

---

## D. 决策级（我需要你拍板，但不紧急）

### [ ] D1. 通知通道选型

R14-2 需要一条真实可送达的通知通道（波次通过/失败、需要人类介入、Incident 升级）。
我不替你选，因为这取决于你实际会看哪里。定了之后记进 `DECISIONS.md`。

### [ ] D2. 7 天无人值守验收的时间窗

WAVE-14 的承重验收是"在探针仓上连续 7 天零人工干预"。请指定一个你不会手痒去动它的时间窗。
中途任何一次人工介入都会导致重新计时——这不是苛刻，是因为"需要人推一把"就不叫 ready。

### [x] D3. 既有 issues 的去留

**已完成（2026-07-30）**：用户授予 admin token 后，已按 `docs/issue去留裁决-2026-07-30.md`
执行全部批量关闭命令：
- loop 仓：关闭 #3/#5/#6/#47（重复 Incident）/ #49（被 R14-4 吸收）/ #50（已完成）/ #51（已修复）/ #55（drift 已修复）。剩余 open：#4/#48（Incident 证据）/ #52/#53（relay 安全决策）+ 38 张新卡。
- product-x 仓：关闭 30 张（重复物化 / 合成工单 / 已完成 C 卡 / 被新波次吸收的 V 卡）。剩余 14 张 open。

---

## 本会话已通过用户授权 token 完成的事（区别于 AI 常态能力）

> 以下事项在 2026-07-30 会话中，由用户提供 admin PAT 后一次性完成。
> **这改变了 AI 的常态能力边界**——没有用户授权 token 时，AI 仍不能做这些。
> CHARTER N5 的红线（"不许把 apply 路径接成自动闭环"）仍然有效。

1. **物化器自动建单**：33 张卡 + 5 Wave 父单 + 5 milestone 已由 `materializer.yml`
   在 PR #54 合并后自动创建（loop 仓 #57–#94）。materialize.py 的 bug 已修复。
2. **既有 issue 批量关闭**：按裁决文档关闭 loop 7 个 + product-x 30 个 issue（见 D3）。
3. **loop 仓 ruleset 创建**：通过 REST API 创建 ruleset id=20052299，含 5 个 required check
   + merge_queue（见 C1）。UI 无法添加未运行过的 check，API 可以。
4. **product-x 线上 ruleset 取证**：通过 `gh api` 拉取并写回 `settings/main-protection.json`（见 B1）。
5. **drift Incident 关闭**：#55 已关闭。

## 仍需用户做的事（AI 无 token 时无法代做）

1. **A1 审定签署 CHARTER.md**——这是唯一不可由 AI 终局裁定的事项。
2. **A2 product-x 设为 Template Repository**——需要仓库 admin 权限。
3. **B2 密钥降权与轮换**——需要组织级 secret 管理权限。
4. **C2 product-x required check 名单同步**——时机在 R13-3，需与新 job 名同步更新。
5. **C3 维护 products.yml**——每新建产品仓时登记。
6. **D1 通知通道选型 / D2 7 天无人值守时间窗**——需要你拍板。
