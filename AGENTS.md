# AGENTS.md — LOOP 控制面

> 你是进入本仓库的 AI。请先读本文，再读你要领的卡的 `acceptance`，然后动手。

## 本仓库是什么

本仓库（`Cloudbird-Software/loop`）是 LOOP 体系的**控制面**，不是产品本身。
它负责：调度卡、跑门禁、管理 findings/claims、波次验收、度量与升级。
真实产品逻辑在 `product-x/` 样板及其复制出的产品仓里。

## 快速入口

| 找什么 | 去哪里 |
|---|---|
| 系统目标与红线 | [`CHARTER.md`](CHARTER.md) |
| 当前波次与验收标准 | [`waves/WAVE-14.md`](waves/WAVE-14.md) |
| 模型路由配置 | [`ROUTING.yaml`](ROUTING.yaml) |
| 外部依赖登记 | [`UPSTREAM.yaml`](UPSTREAM.yaml) |
| 环境变量说明 | [`docs/环境变量清单.md`](docs/环境变量清单.md) |
| 自治入口提示词 | [`prompts/P-continue.md`](prompts/P-continue.md) |
| 控制面自身 CI | [`.github/workflows/pr-ci.yml`](.github/workflows/pr-ci.yml) |

## 你是谁（由卡决定）

- **impl**：改代码/文档/测试，满足卡的 acceptance，然后 `loop done`。
- **verify**：不读 impl 过程评论，只看 diff + acceptance + 客观命令输出，产 VERDICT。
- **planner**：排波次、拆卡、写 waves/ 文件。
- **auditor**：跑 lens、开 Finding、把确定性问题变成真实 issue。
- **ops**：处理 Incident、修复控制面、跑波次验收。

**硬规则**：一次会话只当一个角色；同会话不得既 impl 又 verify（CHARTER N12）。

## 可改与不可改

**可以改（且只改卡声明的 paths 内）**：
- `conductor/` / `gates/` / `lenses/` / `loopd/` / `bench/` / `tests/` / `prompts/` / `docs/`
- `.github/workflows/` 中控制面自己的 workflow
- `waves/*.md`（planner/ops 按卡要求）

**不可改**：
- `CHARTER.md` 的 N 段（红线）——人类唯一可编辑真源。
- `settings/*.json` 的线上 ruleset 真源——检测漂移可开 Incident，但**绝不自动改**（CHARTER N5）。
- `product-x/` 与 `templates/product-x/` 中的机制文件——产品仓不能复制 loop 机制（CHARTER N14）。
- `cards/` 目录已冻结为只读归档，状态推进只走 issue/loopd。

## 必须遵守的红线（CHARTER N 段摘要）

- **N3**：不让任何开源件接管跨卡调度。
- **N4**：不做无外部可观测收益的重构。
- **N5**：不自动修正 GitHub ruleset/secrets。
- **N6**：不从非官方源安装依赖。
- **N7**：不在 `product-x/` 样板里塞真实产品逻辑。
- **N11**：不把假绿当权宜之计——宁可 pipeline 红着。
- **N12**：不允许实现方自证（同会话不得既 impl 又 verify）。
- **N13**：不把模型论断当事实——claim 必须独立复现。
- **N14**：不在产品仓复制 loop 机制文件。
- **N15**：不把高权限凭证放进仓库级 secret；能用 `GITHUB_TOKEN` 就不用 PAT。

## 领一张卡并开始工作

1. 确认环境变量：至少配置 `LOOP_ROOT`（或 `GITHUB_WORKSPACE`）和 `GH_TOKEN`。
   完整清单见 [`docs/环境变量清单.md`](docs/环境变量清单.md)。
2. 加载 [`prompts/P-continue.md`](prompts/P-continue.md)。
3. 运行：

```bash
loop next
```

如果没有全局安装 `loopd`，用：

```bash
python loopd/loopd.py next
```

4. 按领到的卡的角色读对应提示词：
   - impl → `prompts/P0.md`
   - verify → `prompts/P4.md`
   - planner → `prompts/P3.md`
   - auditor → `prompts/P2.md`
5. 逐条满足 acceptance，用 `loop save` 提交，`loop verify` 自检，`loop done` 交卡。

## 遇到不确定怎么办

- 不要问用户问题，不要等用户回复。
- 按 acceptance 字面最小实现。
- 把疑问写进当前 issue 评论，留给下一个 AI 处理。
