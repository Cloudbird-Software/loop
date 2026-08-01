# AGENTS.md — loop 控制面

> 本文件是进仓 AI 的**唯一入口**。一个从未见过本仓库的 AI，只读本文件 + `README.md`
> 就能领到一张卡并开始工作，不需要额外的人工口述。完整流程见 `prompts/P-continue.md`。

## 快速入口

- 章程（人类唯一可编辑真源）：`CHARTER.md`
- 控制面策略方向盘：`policy.yml`
- 异构模型路由表：`ROUTING.yaml`
- 沙盒守护进程规格：`loopd/SPEC.md`
- 凭证清单：`docs/密钥清单.md`
- 环境变量清单：`docs/环境变量清单.md`（新沙盒只需设 5 个变量）
- 人类操作手册（执行化）：`loop控制面建设-人类操作手册.md`
- 架构改造结论（为什么）：`loop架构改造最终结论与工程建议.md`

## 你的角色

会话开始时你不知道自己该当什么角色——角色由 `LOOP_ROLE` 与你领到的卡的 `role` 字段共同决定。
**一次会话只当一个角色**（CHARTER N12：不得在同会话内既 impl 又 verify）。

| 角色 | 吃什么卡 | 入口提示词 |
|---|---|---|
| `impl` | C-0NN 工作卡（trivial / standard / critical） | `prompts/P0.md` |
| `verify` | V-0NN 验证卡（仅 `verify.required=true` 且 `card.model != 自己`） | `prompts/P4.md` |
| `audit` | lens 分片巡检，产 Finding | `prompts/P2.md` |
| `planner` | 造 Wave PR（只改 `waves/**`） | `prompts/P3.md` |
| `reviewer` | 强模型验收环：产可证伪 claim（不产 PASS/FAIL） | `prompts/P1.md` |
| `reproducer` | 对 claim 做异构复现（三态：REPRODUCED / NOT_REPRODUCED / INCONCLUSIVE） | 见 `docs/强模型验收环.md` |
| `plan` | 波次规划卡 | `prompts/P3.md` |
| `lead` | 契约/共享路径卡 | `prompts/P-lead.md`（W1 创建） |
| `spec-test` | T 卡（测试先行） | `prompts/P-spec-test.md`（W1 创建） |
| `redteam` | 红队攻击卡 | `prompts/P-redteam.md`（W2 创建） |
| `mechanism` | 机制路径卡（meta profile） | `prompts/P-mechanism.md`（W1 创建） |
| `mech` | 机械性变更卡 | `prompts/P-mech.md`（W1 创建） |

`LOOP_ROLE` 可逗号组合（如 `plan,ops`）。`P-continue.md` 是"继续"入口，加载它即自动扫卡、领卡、推进状态机。

## 可改的路径（按角色）

- **impl**：仅卡 `paths` 字段列出的路径。不得越界改其他文件。
- **verify**：不改原工作卡代码。只产 VERDICT（`loopd verdict <file>`），FAIL 时建 F-0NN（`loopd finding`）。
- **audit**：`lenses/` 下新增/修正检查器；产 Finding 走 `loopd finding`。
- **planner**：仅 `waves/**`（造波次 PR，`loopd propose`）。
- **reviewer / reproducer**：仅产 `.loop/schemas/claim.json` / `reproduction.json` 对象，不改业务代码。

## 不可改的路径（CHARTER 红线 + 门禁守卫）

下列路径由 CODEOWNERS 或 `gate/paths` / `gate/charter` 守卫，**非授权角色改动直接红**：

- `CHARTER.md` 的 N 段（红线，不随产品变化）—— AI 不得改。
- `policy.yml` 的 gate 集合与 `review.required_check: false`（CHARTER N9.7：强模型验收永不做 required check）。
- `settings/*.json`（分支保护 ruleset 真源，CHARTER N5：不自动修正，只检测漂移开 Incident）。
- `.github/workflows/audit.yml`、`conductor/findings.py`、`conductor/retro.py`、`conductor/upgrade_ring.py`、
  `bench/metrics.py`、`loopd/loopd.py`、`conductor/loop_pin.py` —— 承重文件，改动须走对应卡片授权。
- `cards/`（已冻结只读归档，ADR-011）—— 不得手改，状态推进只走 `loopd`。
- `products.yml`（产品仓注册表，CHARTER N10：AI 不得自行增删）。
- `flags.yml`、`exceptions.yml`（即 `.loop/exceptions.yml`）、`UPSTREAM.yaml`。
- `rules/`（Semgrep 自研规则目录，W1 创建）、`pins/`（pin 白名单目录，W0 已创建）。
- `escalation.yml`（W2 创建）、`rubrics/`（W4 创建）。

## 必须遵守的红线（CHARTER N 段摘要）

- **N3** 不让任何开源件接管跨卡调度。
- **N4** 不做无外部可观测收益的重构（纯"更优雅"不算理由）。
- **N5** 不自动修正 GitHub branch ruleset（检测漂移开 Incident，但永不自动修）。
- **N6** 不从非官方源安装任何依赖。
- **N7** 不在 product-x 样板里塞真实产品逻辑。
- **N11** 不把假绿当作权宜之计——`|| true` / `set +e` 吞退出码 / `continue-on-error` / 探不到即 SKIP 且 exit 0 一律禁止；正当例外必须写明 `fake-green-ok: <理由>`。
- **N12** 不允许实现方自证——impl 不得给自己的卡产 VERDICT，评审模型不得给自己的 claim 做复现判定。
- **N13** 不把模型的论断当作事实——不可证伪的一律拒收，未被独立复现的不得触发任何代码改动。
- **N14** 不在产品仓复制 loop 的机制文件（gates/lenses/conductor/loopd/prompts/settings）。
- **N15** 不把高权限凭证放进仓库级 secret——能用 GITHUB_TOKEN 的绝不用 PAT，能用 App 的绝不用 PAT。

## 提示词入口（prompts/P-*.md）

| 文件 | 用途 |
|---|---|
| `prompts/P-continue.md` | **自治入口**——"继续"触发：找活 → 领卡 → 干活 → 交卡 → 翻 V 卡 ready |
| `prompts/P0.md` | impl 工人 |
| `prompts/P1.md` | impl 补充 / reviewer |
| `prompts/P2.md` | auditor（lens 巡检） |
| `prompts/P3.md` | planner（排卡造波次） |
| `prompts/P4.md` | verify（盲一半协议 + VERDICT） |
| `prompts/P5.md` … `P12.md` | 其余角色与场景（按需读） |

领卡后**先读该卡 `role` 对应的提示词**，再动手。

## 过渡期说明（W0-W3）

当前处于 W0-W3 过渡期，卡片载体和状态存储与最终态不同：

- **卡片载体**：卡片以 `waves/WAVE-XX.md` 中的 ` ```json loop ` 块为载体，由
  materializer（`conductor/materialize.py`）物化到 GitHub Issue。
- **状态存储**（W0-W1）：卡的权威状态在 loop 仓的 `waves/WAVE-XX.md` json loop
  块中（含 `state`/`lease_until`/`heartbeat_at`/`attempt`/`model` 字段）。
- **状态存储**（W2+）：权威状态迁移到 `loop-state` orphan 分支（git ref CAS），
  GitHub Issue 是投影镜像。
- **命令可用性**：loopd CLI 尚在修复中（BROKEN-01），W0 期间 agent 可回退到
  gh/git 手动推进（见 P-continue.md 第 10 节）。

权威参考文档：
- `loop控制面建设-人类操作手册.md`（执行化：做什么、怎么做）
- `loop架构改造最终结论与工程建议.md`（结论与为什么）
- 两文档冲突时以人类操作手册为准。

## 如何领一张卡

```bash
loopd next      # CAS 原子领卡：state ready→in_progress + 设租约 + 切 agent/<card_id> 分支 + 落 .loop/CARD.md
```

领到后读 `.loop/CARD.md` 的 `paths` / `acceptance` / `role` / `blocked_by`，按对应提示词逐条满足 `acceptance`。
**不得手改 `cards/` 归档文件推进状态**——状态机只走 `loopd`（`next` / `save` / `done` / `drop` / `verdict` / `finding` / `retire`）。

依赖检查（硬规则）：领卡前先确认该卡 `blocked_by` 的每张卡 `status:done`；任一未 done 则不要领，评论"等 C-0XX 完成"后回 `loopd next` 找下一张。

## 如何提交

1. 每完成一个可验证小步：`loopd save "<msg>"`（add + commit + push，首次 push 自动开 draft PR）。
2. 逐条跑 `acceptance` 自检，记 PASS + 客观证据（命令输出 / 文件路径+行号 / commit）。
3. 全 PASS：`loopd done <card_id>`（终验 + PR 转 ready + 贴报告 + CAS 置 `in_review`）。
4. 若是 C-0NN 工作卡（硬步骤）：找到 `verify_target` 指向本卡的 V-0NN，`loopd` 置其 `state:ready=true`——不翻 ready，验证环就断了。
5. 分支命名由 `loopd` 按 `LOOP_BRANCH_PREFIX/<card_id>` 自动切（默认 `loop/card/<card_id>`，沙盒常配 `agent/<card_id>`）。
6. PR 走 `.github/workflows/pr-ci.yml` + `reusable-gates.yml` 门禁。门禁未执行等价于失败（CHARTER N8.3）；假绿直接红（N11）。
7. verify 异构强制（CHARTER N8.5）：verify 模型 ≠ impl 模型由 CI 强制，非仅文档声明。

## 硬禁止（违反即本卡作废）

1. 不在 `blocked_by` 未满足时动手。
2. 不主观判断——所有结论必须有客观证据。
3. 不跳过 `acceptance` 自检就 `done`。
4. 不改不属于你 role 的卡（角色阀门：impl 不造 Finding，verify 不改原工作卡代码）。
5. 不在 verify FAIL 时强行合并或强行 PASS。
6. 不问用户问题、不等用户回复——有疑问按 `acceptance` 字面最小实现，把疑问写进评论留给下个 AI。
7. 不自己造卡塞进队列（造卡是 planner 的活），除非处理 F-0NN 建修复卡或 verify 建 F-0NN。
8. 不手改 `cards/` 归档文件（已冻结，R10-5）；不手改 `waves/WAVE-XX.md` 中已被
   materializer 物化的 `json loop` 卡块（状态推进只走 loopd 或 intent 通道）；
   不直接在 GitHub Issue 上修改 `json loop` 块的状态字段。
9. 不在同会话内既 impl 又 verify（N12）。
