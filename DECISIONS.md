# DECISIONS.md — Architecture Decision Records

## ADR-001: P1/P2/P3 提示词待 W2 前补齐

**日期:** 2026-07-29
**状态:** 待办

P1（实现工补充）、P2（审计工）、P3（规划工）的提示词目前为骨架占位。
需在 W2 开始前补齐完整内容，否则力工池无法正常领卡。
P4（验证工）已有新增段，但 v4 基础文本仍需补齐。
P5–P9 按各自波次（W3–W6）逐步补齐。

## ADR-002: waves/ 归 product-x；materializer 迁 product-x（D0 落实）

**日期:** 2026-07-29
**状态:** 已执行

D0 决策定案照执行：
- `waves/` 目录归 **product-x** 仓库（波次声明与代码同库）。
- `materializer.yml` + `conductor/materialize.py` 从 loop 仓**迁移到 product-x**。
  触发条件：push to product-x main, paths `waves/**`。
  token：改用 workflow 默认 `GITHUB_TOKEN`（product-x 仓库未配 conductor app secret；
  默认 token 对本仓 issues:write 足够，免额外 secret）。已实测：合入后 workflow
  成功物化 WAVE-1 的 5 张 Card issue（product-x #18–#22）。
- loop 仓侧：原 `.github/workflows/materializer.yml` 删除，留转发注释（见
  `.github/workflows/materializer.yml` 当前内容）。
- **charter 占位**：CHARTER 未立前，所有 W1 卡的 `charter` 字段映射到 `["G0"]`，
  待 CHARTER 写好后回填正式映射。
- **CODEOWNERS 限制**：product-x 的 `/AGENTS.md` 被 CODEOWNERS 锁给 @randypanding，
  W1 的 w1-agents 卡生成的 PR 需 code-owner 手动批；其余 4 张可自动合。

## ADR-003: 今晚六包并行开工（night/<包名> 分支）

**日期:** 2026-07-30
**状态:** 进行中

今晚控制面施工以六包并行分队推进。每包在各自 `night/<包名>` 分支工作、开 PR，
**绝不直接推 main、不自行合并**（合并是人类早上的事）。合并顺序：**A 先于 E**
（见 0.6 接口契约：A 只追加 UPSTREAM.yaml 的 opencode 条目，E 负责全量整理）。
冲突裁决：v5 定形态、v4 定内容，仍冲突按最简实现并记入假设清单。

| 包 | 分支 | 职责（按 0.6 契约已知部分） | 独占 paths 概要 |
|---|---|---|---|
| A | `night/a` | 接缝 B 执行体（opencode）；按 D 的 VERDICT schema 实现 handler；UPSTREAM.yaml 追加 opencode 条目 | A 卡定义 |
| B | `night/b` | B 卡定义（见各包卡片） | B 卡定义 |
| C | `night/c` | C 卡定义（见各包卡片） | C 卡定义 |
| D | `night/d` | 建 VERDICT schema 文件（字段：head_sha / blind_phase_commit / artifact_digest / test_plan_version / acs[]，每项含 id/pass/evidence） | D 卡定义 |
| E | `night/e` | UPSTREAM.yaml 全量整理 | E 卡定义 |
| F | `night/f` | 杂项收口：接缝 A 路由器 + ROUTING.yaml、mcp.json、DECISIONS.md、product-x TEMPLATE.md + 生成层文件头 | seam_a/**、ROUTING.yaml、mcp.json、DECISIONS.md；product-x TEMPLATE.md + 文件头 |

> 各包详细任务与验收见各自卡片与 PR 正文；本表只记开工与分支归属，避免越界。
> 安全免责：org ruleset 启用、required checks 回填、安全测试等「启用类」动作不在今晚范围，
> 各包遇到一律跳过并记入「给人类的待办」。

### 假设清单统一格式（各包 PR/报告遵循）

为消除跨包依赖、便于人类早晨一次性裁决，今晚各包的 PR 正文与最终报告统一采用以下
假设清单格式。每条假设须可独立裁决、可追溯；只记「与权威文档（MANUAL v5 / OPC-v4 / 卡包）
有出入或未明确、且今晚按最小实现落地」的条目，权威文档已明确的不记。

    ### 假设清单（包 <X>，分支 night/<x>）
    - <AID>: <假设内容> | 影响范围 | 默认采用的最小实现 | 待人类裁决点

字段约定：
- `<AID>`：包内自增编号（A1/A2…、F1/F2…），跨包不重编号。
- `影响范围`：受影响的文件 / 接口 / 行为。
- `默认采用的最小实现`：今晚已按此落地，无需人类介入即可继续。
- `待人类裁决点`：若人类不认可，应改成什么（一句话）。

> 各包假设清单放在各自 PR 正文与最终报告里，不回写本文件
>（DECISIONS.md 由 F 包独占，只记跨包协调与 ADR）。

## 待办: CHARTER.md 仍缺失（0.6 契约）

**日期:** 2026-07-30
**状态:** 待办

截至 2026-07-30，product-x 仓库仍无 `CHARTER.md`（仅 AGENTS.md / README.md /
TEMPLATE.md / UPSTREAM.yaml）。按 0.6 接口契约与 ADR-002：CHARTER 未立前，所有卡的
`charter` 字段继续用 `["G0"]` 占位。待人类写好 CHARTER.md 后回填正式 G/N/Q 编号映射。
本条不阻塞今晚六包施工。

---

# 2026-07-30 审查后架构决策（ADR-004 ~ ADR-011）

> 背景：一位强模型专家提出 25 条指控，经独立复现裁定为 14 条 TRUE、8 条 PARTIAL、
> 3 条承重结论 FALSE，另有 1 条两人都漏掉（`settings/main-protection.json` 缺
> `required_status_checks`）。全部证据与逐条裁决见 `docs/审查裁决-2026-07-30.md`。
> 以下 ADR 是从这次经历中固化下来的架构决定。

## ADR-004: 强模型验收自动化，但其输出只是"待检验的输入"

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：强模型验收全自动执行（Copilot CLI headless / Actions，见 WAVE-12），
但它的唯一合法产物是符合 `.loop/schemas/claim.json` 的**可证伪断言数组**，
不是 PASS/FAIL，不是散文结论。

**理由**：本次审查中，专家 25 条里有 3 条承重结论不成立。若当时按"专家说了算"直接开修，
会有三条修错方向（其中"必须用高权限 PAT 破窗"甚至会诱导我们去动分支保护）。
把模型输出定性为"事实"是架构性错误；定性为"假设"才与其实际可靠性匹配。

**后果**：评审提示词必须显式禁止结论性措辞；缺 `repro` 或 `falsifier` 的断言在
入口即被 `conductor/claims.py` 拒收。代价是评审产出变"啰嗦"，收益是每条都可被机器检验。

## ADR-005: 任何 claim 必须被异构模型独立复现，才配触发代码改动

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：claim → `unconfirmed` 工单 → 异构沙盒复现（三态：REPRODUCED /
NOT_REPRODUCED / INCONCLUSIVE）→ 仅 REPRODUCED 才转 `ready` 进入修复。
`next_action` 由 conductor 依裁决表计算，沙盒模型只报观察、不做流程决策。
INCONCLUSIVE 触发多采样仲裁，仍不收敛则升级人类。

**理由**：这正是本次人工流程做过的事，且它抓出了 3 条假指控和 5 条细节错误。
把它自动化，就是把一次性的谨慎变成常设机制。三态而非二态，是因为环境差异导致的
"复现不出来"与"确实不存在"必须区分，否则会系统性地把环境敏感的真缺陷判死。

**后果**：修复链路变长（多一跳复现），但错误修复的成本远高于这一跳。

## ADR-006: 被确认的 claim 尽量固化为确定性检查器（信任单调下降）

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：同类 claim 累计被确认 ≥ `policy.yml` 的 `harden_after_confirms` 次后，
自动开固化卡，要求实现为 `lenses/` 下**不调用任何 LLM** 即可复现该缺陷的检查器。
已固化类别在后续评审中降权，避免强模型反复刷同一类问题消耗预算。

**理由**：系统对模型的信任应当**单调下降**而非累积依赖。本次审查中的假绿检测、
`GATE_NOT_EXECUTED` 检测、settings 往返一致，本来就都能确定性化——它们之所以靠人发现，
只是因为没人把它写成检查器。

**后果**：`lenses/` 会持续增长；需要为其建立误报率登记与退役机制。

## ADR-007: 产品仓持有 pin 而非副本

**日期:** 2026-07-30 **状态:** 已采纳，修订 ADR-002 关于产品仓形态的部分

**决定**：产品仓只保留四类东西——产品自己的 `CHARTER.md`、`LOOP.yml`（钉 loop 的
tag + 40 位 SHA）、薄壳 workflow（只 `uses:` loop 的 reusable workflow）、产品源码与测试。
`gates/` `lenses/` `conductor/` `loopd/` `prompts/` `settings/` 的副本一律为零（CHARTER N14）。

**理由**：本次审查坐实了副本的两种失效模式——product-x 的 `.loop/gates/` 里有可工作的
门禁实现却因 `ci.yml` 路径不匹配永不执行；两仓 `tick.py` 已分叉出 25 行实质差异。
副本必然分叉，分叉必然静默失效。

**后果**：产品仓 CI 依赖 loop 可用性；由 pin + 自动回退（ADR-009）兜底。

## ADR-008: 用 GitHub template repository 复制，不用 fork

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：新产品仓从 product-x **模板**创建（一次性播种、无上游 fork 关系、历史干净），
持续对齐靠 `LOOP.yml` pin + 第 8 环升级 + `products.yml` 扇出，不靠 fork 的上游同步。

**理由**：fork 会带来"上游合并"的语义，与"产品仓有自己的演化路径"冲突；
且 fork 关系会让 PR 默认指向上游，是持续的误操作源。

**后果**：需要 `gate/loop-conformance` 主动检查对齐（fork 的隐式关联被显式检查取代）。
需要人类在 GitHub Settings 勾选 Template repository（见 HUMAN-TODO）。

## ADR-009: `loop` 自身进入产品仓的 UPSTREAM 升级环

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：`Cloudbird-Software/loop` 登记进各产品仓的 `UPSTREAM.yaml`，与其他依赖一样
走第 8 环的冷静期 → bench 重放 → 不劣化才合并 → 失败自动回退。

**理由**：控制面本身就是产品仓最重的依赖。它享受与其他依赖不同的待遇（无冷静期、
无重放、无回退）没有正当理由。

**后果**：loop 发布节奏受冷静期约束；紧急修复需要显式的 hotfix 通道。

## ADR-010: 修订 ADR-002 —— loop 恢复自己的 waves/ 与物化器

**日期:** 2026-07-30 **状态:** 已采纳，部分推翻 ADR-002

**决定**：产品工单仍在产品仓（ADR-002 主体不变）；但 loop 恢复 `waves/` 与
`.github/workflows/materializer.yml`，只物化控制面自身的改造工单。
卡片 JSON 新增 `repo` 字段标明目标仓库，跨仓卡片在 loop 建单、在目标仓开 PR、反向链接。

**理由**：ADR-002 把物化器整体外迁后，控制面的改造工作无处落卡，只能靠人口述——
这正是 F-D（控制面零 CI）与 P1-6（接单入口不是一个固定提示词）的同源病根。

**后果**：两个物化器并存，必须靠 `repo` 字段与 `paths` 前缀避免歧义。

## ADR-011: 冻结 `cards/`，product-x issues 成为唯一工单真源

**日期:** 2026-07-30 **状态:** 已采纳

**决定**：`cards/` 转为只读归档，其 `status:` / `ready:` 字段不再具有权威性。
新工单一律走 product-x issues 的 `json loop` 块（带 CAS / lease / heartbeat）。
`P-continue.md` 中"AI 改 markdown 字段推进状态机"的指令删除。

**理由**：双真源已实测撞车（V-009 在 loop 侧 `done`，在 product-x #99 是 open/pending），
"中心化接单"的前提被打破。`cards/README.md` 与 `WORKFLOW.md` 本就把 `cards/` 标为暂行期，
设计意图即切到 issues，只是切换从未发生。

**后果**：历史卡片状态需一次性映射到 issue 号，无法映射者标 ORPHAN。

## ADR-012: 零假绿是红线，正当例外必须自证

**日期:** 2026-07-30 **状态:** 已采纳（CHARTER N11）

**决定**：`|| true`、`set +e` 吞退出码、`continue-on-error: true`、探测不到即 SKIP 且 exit 0，
四类模式在 CI 中一律禁止。确有正当理由的，必须在该行或前一行写
`fake-green-ok: <理由>`，由 `no-fake-green` 扫描器强制。

**理由**：本次审查坐实 6 处假绿。假绿比没有门禁更危险——没有门禁时人知道自己没有保护，
有假绿时人以为自己有保护。

**后果**：每一处例外都变成一条可被审计的书面承诺。

## ADR-013: 通知通道选 GitHub Issue（评论 / 开 Incident issue），不引入外部 webhook

**日期:** 2026-07-31 **状态:** 已采纳（R14-2）

**决定**：波次验收与 Incident 的通知通道落地为 **GitHub Issue**——
`conductor/retro.py::notify(event_type, payload, repo=None)` 实现三类事件的真实送达：
  - `wave_passed` / `wave_failed` / `needs_human` → `gh issue comment` 贴到 Wave 父 issue
    （passed 时另用 `gh issue close` 自动关闭父 issue）；
  - `incident` → `gh issue create` 开新 Incident issue（label: `incident`）。

不引入 Slack / 邮件 / 自建 webhook 等外部依赖；通道凭据复用 Actions 自带 `GITHUB_TOKEN`。

**理由**：本次架构以 GitHub Issues 为唯一工单真源（ADR-011），通知送达的目标本身就是 issue
（波次父 issue / Incident issue）。再架一层外部 webhook 等于在工单系统外建第二个通知真源，
既增加凭据面（需额外 secret），又让"通知是否送达"变得不可观测。走 `gh issue comment/create`
使"送达"等价于"issue 上多了一条评论/多了一张 issue"——可被既有审计与 no-fake-green 复检。

**后果**：
  - 通知是否真实送达 = gh 退出码是否为 0；失败不再静默（`|| echo skipped` 已移除）。
  - dry-run（`LOOP_NOTIFY_DRY_RUN=1` 或 `payload["dry_run"]`）只生成正文不调 gh，供本地与测试用。
  - 未来若需多通道（如 Slack 兜底），在 `notify` 内追加分支即可，不影响现有 Wave 调用方。
  - retro 的 LLM 归因部分未集成 LLM 调用，明确标注为 `human-verify`（schema:
    `llm-attribution-human-verify`，status: `needs_human`）并生成待办推给人类，不假实现、不静默挂起。

---

## ADR-014 — E2E 验收剧本就位，暂不宣告「端到端 ready」（R14-6）

**背景**：WAVE-14 R14-6 要求以一次 7 天零人工干预的连续运行作为「端到端 ready」的唯一承重验收。
本波次 impl 阶段已产出 `docs/E2E验收剧本.md`（5 大承重项 + 2 不变量 + 4 负向场景 + verify 操作手册）
与 `bench/e2e.json` 骨架（字段结构 + 空事件数组）。

**决定**：暂不宣告「端到端 ready」。理由：
1. 验收 #3「在 product-probe 上完成一次 7 天零人工干预的连续运行」尚未执行——这是物理时间约束，非代码缺口。
2. 验收 #5「执行者必须与本波次任何 impl 卡的执行者异构（CHARTER N12）」——本 impl 阶段由同一会话产出，真实 7 天运行须由异构 verify 角色执行并签署。

**阻塞项**：
- 需异构 verify 角色在 product-probe 上执行 `docs/E2E验收剧本.md` 第 6 节，7 天后填充 `bench/e2e.json`。
- 四指标达标 + 人工介入=0 两条件同时满足后，方可在本 ADR 追加「ready」签署。

**后果**：
- 机制层（R14-1~R14-5）已就位：lens→真实工单、波次自动验收+通知、四指标可回放、零覆盖补测试、单一接单入口。
- 「ready」一词在本项目内严格保留给 ADR-014 的最终签署，不得在其他场合提前使用。
