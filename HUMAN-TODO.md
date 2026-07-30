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

### [ ] A3. 配置 `DEEPSEEK_API_KEY`

**为什么必须是你**：涉及账号与付费。

**背景**：`ROUTING.yaml` 的 verify 路由此前与 impl 路由**完全相同**（都是 `qwen/qwen3-max`），
而注释还谎称"不同 provider"。我已把 verify 改为 `deepseek/deepseek-chat` 以真正实现异构，
但这个凭证还不存在。

**不做会怎样**：verify 路由无法工作，`gate/heterogeneity`（R11-2）会红。
如果你不想用 deepseek，任选另一个与 qwen 异构的 provider，改 `ROUTING.yaml` 即可——
但**不能**改回与 impl 相同，那等于取消独立验证。

**验证**：`gate/heterogeneity` 绿，且一次真实 verify 会话的 evidence 中 model 字段不是 qwen。

### [ ] A4. 开通 Copilot CLI 并配置 `COPILOT_GITHUB_TOKEN` 与用量预算

**为什么必须是你**：涉及 GitHub Copilot 席位/授权与 premium request 预算。

**动作**：
1. 确认账号有可用的 Copilot 授权。
2. 建一个**只读**权限的 token 存为 `COPILOT_GITHUB_TOKEN`（评审只需读代码）。
3. 决定预算上限，填进 `policy.yml` 的 `review.max_reviews_per_day`（我暂填 6）。

**安全提示**：`@github/copilot` 已登记进 `UPSTREAM.yaml` 并钉 **≥1.0.43**。
低于此版本存在两个已知 RCE 公告（`core.fsmonitor` 嵌套裸仓库、危险 shell 展开）。
请勿手动降级。

**不做会怎样**：WAVE-12 的强模型验收环无法运行。注意这**不阻塞**其他波次——
评审环按设计永不做 required check（CHARTER N9.7）。

---

## B. 安全级（不做，系统能跑但有实质风险）

### [ ] B1. 重新导出线上 ruleset 并核对 `settings/main-protection.json`

**这是本次审查中专家和复现者**都漏掉**的一条，我认为它是当前最危险的单点。**

**问题**：`settings/main-protection.json` 里**根本没有 `required_status_checks` 规则**。
而线上 ruleset（id 19949520，enforcement: active）实际强制着 6 个 check。
一旦 `policy.yml` 的 apply 路径被实现（`policy.yml:29-33` 目前还是 `echo "TODO"`），
它会以"人类已批准"的名义，把线上仅有的 6 道真门禁**删光**。

**动作**：
```
gh api repos/Cloudbird-Software/product-x/rules/branches/main > /tmp/live-ruleset.json
```
把结果交给执行 R10-4 的 agent，或自己核对进文件。

**不做会怎样**：R10-4 无法验收；drift 检测持续产生噪声；apply 一旦实现即为高危。

**验证**：`python3 gates/gate_settings_roundtrip.py` 输出 `OK`。

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

### [ ] B3. 授予 loop 仓所需的 secret 访问

**动作**：确认 loop 仓能访问 `POLICY_R`（或等价凭证）。当前 `drift.yml` 在缺 secret 时
的静默 SKIP 已被我改为显式失败——所以**改完之后它会开始报红**，这是正确行为，
不是我改坏了。请配上凭证，或明确决定停用该 workflow。

---

## C. 接线级（WAVE-10/11 合并后才需要做）

### [ ] C1. 为 loop 仓设置 required checks

**动作**：loop → Settings → Rules → 新建/编辑 main 的 ruleset，把
`test` / `lint` / `no-fake-green` / `actions-pinned` / `schemas` 五个 check 设为 required，
`bypass_actors` 留空。

**为什么必须是你**：GitHub ruleset 只能由 admin 改，且 CHARTER **N5 明令禁止 AI 自动修正 ruleset**
（检测漂移可以开 Incident，但永不自动改）。这条红线我不会绕。

**背景**：loop 仓此前 9 个 workflow **全是** schedule/dispatch，**0 个** `pull_request`——
写门禁的自己不过门禁，21 个测试从不在 PR 上跑，F-003 那个大小写比较 bug 就是这么漏出去的。
我已新增 `.github/workflows/pr-ci.yml` 止血，但"跑"和"必须绿才能合"是两回事，
后者只有你能设。

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

### [ ] D3. 既有 issues 的去留

我已在 `docs/issue去留裁决-2026-07-30.md` 给出全部 84 个 issue（loop 36 + product-x 48）
的建议。**关闭动作我做不了**（我只有只读的 GitHub 查询能力，无法创建或关闭 issue），
需要你或一个有写权限的 agent 执行。批量命令我已写在那份文档里，可直接粘贴。

---

## 我做不到的事（不是不愿意，是环境限制）

诚实告知，以免你以为已经做了：

1. **我无法创建或关闭 GitHub issue**。本次全部 33 张卡以 `waves/WAVE-10..14.md` 的形式交付，
   合并到 main 后由我恢复的 `.github/workflows/materializer.yml` 自动建单
   （milestone + 父 Wave issue + 33 张卡 issue，依赖关系已写在卡的 `blocked_by` 字段里）。
   我已本地跑过物化器的全部校验：**33 张卡全部通过**四项校验与 paths 两两不交叉检查。
2. **我无法向 product-x 推送**。所以目标为 product-x 的 6 张卡
   （R10-2 / R13-3 / R13-4 / R13-6 及相关）以 `"repo": "product-x"` 标注，
   由领卡 agent 在 product-x 开 PR，反向链接回 loop 的 issue。
3. **我无法调用 `gh api`** 读线上 ruleset。本文件与裁决文档中所有关于线上 ruleset 的陈述，
   都来自你提供的复现报告，我已标注来源。B1 需要你或有权限的 agent 重新取证。
4. **我无法改 GitHub 仓库设置**（template 开关、ruleset、secret）。这也正是 CHARTER N5
   所要求的边界。
