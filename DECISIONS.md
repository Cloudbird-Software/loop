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
