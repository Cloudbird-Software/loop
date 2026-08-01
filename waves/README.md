# waves/ —— 控制面自身的工单来源

> 本目录是 **loop 仓自己的** 波次卡片。合并到 `main` 后，
> `.github/workflows/materializer.yml` 会自动物化为 GitHub issue
> （milestone + 父 Wave issue + 每张卡一个 Card issue）。

## 为什么 loop 也有 waves/

`DECISIONS.md` 的 **ADR-002** 曾把物化器整体迁往 product-x，理由是"工单只应存在于产品仓"。
**ADR-010** 修订了这一点：产品工单仍在产品仓，但控制面自身的改造工作必须也能落卡，
否则只能靠人口述——这正是 F-D（控制面零 CI）与 P1-6（接单入口不是一句固定提示词）的同源病根。

## 卡片格式

每个 `WAVE-<数字>.md` 文件：

- 标题行 `# WAVE-<数字> — <名称>`，波次 ID 由正则 `WAVE[-_]?\d+` 提取，**必须是纯数字**。
- 第一行 `> ` 引用块作为波次摘要。
- 一节"本波次的检查方法（Wave-level Gate）"——波次关闭前必须逐条粘贴真实输出。
- 若干 ` ```json loop ` 围栏块，每块一张卡。

## 卡片字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `schema` | 是 | 固定 `1` |
| `id` | 是 | 形如 `R10-1`，全局唯一 |
| `objective` | 是 | 短目标，进 issue 标题 |
| `title` | 否 | 完整标题；缺省时用 `objective` 派生 |
| `repo` | 否 | `loop` 或 `product-x`，标明**目标仓库**；缺省默认为 `loop`（仅跨仓卡需显式声明） |
| `tier` | 是 | `trivial` / `standard` / `critical`；命中敏感路径会被 `auto_tier` 强制提升为 `critical` |
| `role` | 是 | `impl` / `verify` / `planner` / … |
| `charter` | 是 | 只能引用 `CHARTER.md` 末尾"机器可读索引"里出现的编号 |
| `paths` | 是 | 该卡可改的路径。**全目录内两两不得交叉**（物化器强制） |
| `acceptance` | 是 | ≥1 条，且必须可被客观检验 |
| `blocked_by` | 否 | 依赖的卡 id |
| `verify` | 否 | 验证方法，写给 verify 角色看 |
| `human_action` | 否 | 该卡涉及的人类动作，须与 `HUMAN-TODO.md` 对应 |

## 跨仓卡片怎么走

`"repo": "product-x"` 的卡在 **loop 建单**，领卡 agent 在 **product-x 开 PR**，
PR 正文反向链接回 loop 的 issue。其 `paths` 一律加 `product-x/` 前缀，
既保证与 loop 侧路径不交叉，也让"这张卡动的是哪个仓"一眼可辨。

## 本地校验（提交前请跑）

```bash
python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("mz", "conductor/materialize.py")
mz = importlib.util.module_from_spec(spec); spec.loader.exec_module(mz)
cards, metas = mz.extract_cards("waves")
errs, valid = mz.validate(cards, mz.load_charter_ids())
print(f"cards={len(cards)} valid={len(valid)}")
for e in errs: print("  ✗", e)
PY
```

`pr-ci.yml` 的 `schemas` job 会在每个 PR 上跑同样的校验。

## 当前波次

| 波次 | 名称 | 卡数 | 前置 |
|---|---|---|---|
| WAVE-10 | 止血：让绿灯重新代表"通过" | 6 | 无 |
| WAVE-11 | 门禁真实化与供应链卫生 | 8 | WAVE-10 |
| WAVE-12 | 强模型验收环 | 7 | WAVE-10 |
| WAVE-13 | 产品仓对齐 | 6 | WAVE-10、R11-1、R11-6 |
| WAVE-14 | 闭环、度量与"端到端 ready" | 6 | WAVE-11、WAVE-12 |

**合计 33 张卡。** WAVE-11 与 WAVE-12 可完全并行；WAVE-13 依赖 R11-1/R11-6 两张卡而非整个 WAVE-11。

背景与逐条证据见 `docs/审查裁决-2026-07-30.md`；
架构依据见 `docs/强模型验收环.md` 与 `docs/产品仓对齐架构.md`；
人类必做事项见 `HUMAN-TODO.md`。
