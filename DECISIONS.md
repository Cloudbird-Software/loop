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
