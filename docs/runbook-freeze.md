# Kill Switch 全局冻结 Runbook（W3-6）

> 状态：已冻结归档。本 runbook 描述**唯一的机器冻结机制**：`policy.yml → freeze.all`。
> 决策 M1/F3 已把旧的独立 `MERGE_FROZEN` 机制合并移除——**不存在第二套冻结机制**，
> 全链只消费 `freeze.all` 一个开关（详见 `loop架构改造最终结论与工程建议.md`）。
>
> 读者：运行 loop 控制面的人类操作员。执行本手册各项操作时，除非特别说明，
> 一律使用仓库现有机理：`loopd` CLI + 手工编辑 `policy.yml` + `loop-state` 分支 CAS。

---

## 关键事实（先读这块再动手）

- **唯一写者**：`conductor/tick.py` 的 escalate 步是 `freeze.all` 的**唯一代码写者**
  （`_set_freeze_all(True/False)`），链上其他任何组件只读 `freeze.all`，不得写。
- **状态真源**：卡片权威状态在 `loop-state` 分支（Orphan 分支，git ref CAS），
  GitHub Issue 只是投影镜像。read: 看 caller SHA / 提 PR；write: 走 CAS（读 base_sha → 写 ref）。
- **卡操作一律走 `loopd`**：`next / save / done / drop / verdict / finding / retire`。
  不得手改 `cards/` 归档或 `waves/` 已物化的 json loop 卡块。
- **ring**：`policy.yml → rings.ring0: [impl]`（W3-1 落盘，只读）。

下面每一节都可独立执行。

---

## 冻结（Freeze）

**目标**：立即暂停全链一切写操作（README / docs 写步骤、卡片状态推进、dispatch 调度）。

### 触发方式（三选一）

1. **自动（推荐常态）**：tick.py escalate 步读到 `escalation.yml` 触发 critical → 自动置
   `freeze.all=true` 并开 Incident。无需人工干预。
2. **手工改 `policy.yml`**：
   ```yaml
   freeze:
     all: true
     chains: []
   ```
   改完提交即可；下游消费方（conductor.yml freeze guard、本仓 `docs/runbook-freeze.md`
   对应的 `.github/workflows/freeze-yaml-check.yml`、tick 进程内守卫）在下一次运行即生效。
3. **CI 手动演示**：触发 `freeze-yaml-check.yml` 的 `workflow_dispatch`，self-check
   会先把 `freeze.all` 置 `true` 跑一套 freeze 路径，再恢复 `false`（见「解冻恢复」）。

### 冻结后行为（AC-4 期望）

- `conductor/tick.py`：进入 `FROZEN: policy.freeze.all=true, skipping tick writes` 分支，
  退出码 0、打印 `FROZEN`、不执行任何写 step。
- 评估门禁对 README/docs 的写 step 被 `if:` 守卫 skip，并打 `FROZEN` 标记。
- `loop-state` 分支 commit 数**不变**（`delta == 0`）。验证：
  ```bash
  # 记录冻结前 loop-state commit 数
  BEFORE=$(git rev-list --count origin/loop-state 2>/dev/null || 0)
  # … 跑全链 …
  AFTER=$(git rev-list --count origin/loop-state 2>/dev/null || 0)
  test "$BEFORE" -eq "$AFTER"       # 冻结期必须为真，否则说明仍有写操作
  ```

---

## 回滚 pin（Rollback Pins）

**目标**：把连续失败的 pin 依赖（rollout ring 里被 pin 住的版本/提交）回滚到上一个稳定点。

> pin 白名单目录 `pins/`（W0 已创建）。回滚指：把某链/某 ring 的 pin 指回更早的稳定 commit。

1. 先查当前 pin 指向：
   ```bash
   ls pins/
   git show origin/loop-state --stat | head                          # 看最近状态变更
   ```
2. 找到要回滚到的稳定 commit（通常取 Incident 前的最后一次 `loop-state` 绿 commit）：
   ```bash
   STABLE=$(git rev-parse origin/loop-state~1)                       # 依实际情况选
   ```
3. 手工编辑对应 `pins/*.yml`（或按设计回滚链的 pin ref），把 `ref:` 指到 `$STABLE`。
4. 通过 `loopd` 提交并写回状态真源（由 CAS 保证并发安全）：
   ```bash
   loopd save "rollback pins to $STABLE (kill-switch recovery)"
   ```
5. **验证**：`git diff` 确认 pin 已回指；运行一次 tick（若已解冻）确认无新失败。

> ⚠️ 若某 pin 在冻结前已写成导致环停的坏值，回滚顺序**必须先于解冻**：先回滚 pin，
> 再解冻，避免解冻后立刻被坏 pin 再度卡死。

---

## 全部打回 ready（Reset Cards back to Ready）

**目标**：把冻结时处于 `in_progress` / `in_review` / `leased` 等中间的卡全部打回
`state: ready`，让链路在解冻后可被重新调度。

> 状态机只走 `loopd`，**不得手改** `cards/` 归档或 `waves/` 已物化的 json loop 卡块。
> 若 `loop-state` 分支存疑，回退到 gh/git 手动推进（见 `prompts/P-continue.md` 第 10 节）。

1. 盘点当前所有非 `ready`/`done` 的卡：
   ```bash
   gh api "repos/${{github.repository}}/git/matching-refs/heads/loop-state" | \
     python3 -m json.tool          # 或直接用 loopd list
   loopd next                        # （等价探测：能否领到卡）
   ```
2. 对每张中间卡调 `loopd` 回到 ready：
   ```bash
   loopd drop <card_id> || loopd save "<card_id> state→ready (kill-switch reset)"
   ```
   > 具体用 `drop`（放弃）还是 `save`（改 state），以该卡当前状态与 `loopd` 子命令语义为准；
   > 目标是最终所有中间卡 `state: ready`，且（若适用）其 `verify_target` 卡 `state: ready=true`。
3. 校验没有卡残留在非终态：
   ```bash
   # 断言：无 in_progress / in_review / leased
   gh api ...loop-state | python3 -c '
     import json,sys
     d=json.load(sys.stdin); ...'  # 见「导出状态」节的解析，断言全部终态/ready
   ```
4. **F-0NN 处理**：若冻结间产生了阻塞卡，先 `loopd finding` 归档，再打回 ready。

---

## 导出状态（Export State）

**目标**：把 `loop-state` 真源导成可读/可审计的 JSON，供 Incident 复盘与「全部打回」盘点用。

环真源在 `loop-state` 分支，导出有两种方式：

1. **读分支文件**（只读、不改状态）：
   ```bash
   git fetch origin loop-state
   git show origin/loop-state:loop-state.json > exported-state-$(date +%F).json   # 视实际文件名
   ```
   若分支内有多个状态文件，逐一导出并 `grep` 关键字段：
   ```bash
   git ls-tree -r --name-only origin/loop-state
   ```
2. **结构化汇总**：用 `loopd` / gh 把卡块抽成表格：
   ```bash
   gh api "repos/${{github.repository}}/issues?state=all" --paginate | \
     python3 -m json.tool > exported-issues.json
   ```

> ⚠️ 导出是**只读**操作，始终允许（即使 `freeze.all=true`）。导出的状态集应能被
> 「全部打回 ready」一节直接消费（幂等）。

---

## 解冻恢复（Unfreeze / Recovery）

**目标**：恢复全链写操作，让下游卡能继续被调度与消费（AC-5：`freeze.all=false` 后写操作恢复、
日志无 `FROZEN` 残留、`delta>0` 恢复）。

### 解冻前提（先做，再解冻）

- [ ] 「回滚 pin」已把坏 pin 回指稳定点。
- [ ] 「全部打回 ready」已把中间卡清零。
- [ ] （如需要）Incident 已关闭或已明确冻结原因已消除。

### 解冻步骤

1. 人工把 `policy.yml` 置回 false（**手工覆盖是唯一允许绕过 W3-TK 的口子**，须留痕说明理由）：
   ```yaml
   freeze:
     all: false
     chains: []
   ```
   ```bash
   git add policy.yml && git commit -m "unfreeze: freeze.all=false (kill-switch recovery)"
   ```
2. 提交后跑一次 tick / 触发 `freeze-yaml-check.yml` 的 workflow_dispatch：
   - 期望：日志出现正常 tick 流程、**无** `FROZEN` 字样。
3. 恢复验证（AC-5）：
   ```bash
   BEFORE=$(git rev-list --count origin/loop-state)
   python3 conductor/tick.py        # 或该链对应的消费方
   AFTER=$(git rev-list --count origin/loop-state)
   test "$AFTER" -gt "$BEFORE"      # 写操作恢复，delta>0
   # 无 FROZEN 残留：
   ! grep -q "FROZEN" run.log 2>/dev/null
   ```
4. 确认下游卡可直接消费：
   ```bash
   loopd next        # 应能领到一张 ready 卡
   ```

### 可选：kill switch 演练自检

`.github/workflows/freeze-yaml-check.yml` 的 `self-check` job 在 `workflow_dispatch` 下会：
置 true → 断言无写 + FROZEN + loop-state delta==0 → 置 false → 断言写恢复 + 无 FROZEN。
可直接复制其 shell 步骤到本地验证解冻闭环。

---

## 附加：冻结机制唯一性（AC-6）

| 项 | 说明 |
|---|---|
| 唯一机器冻结开关 | `policy.yml → freeze.all` |
| 唯一写者 | `conductor/tick.py` escalate 步（`_set_freeze_all`） |
| 手工覆盖 | 人类编辑 `policy.yml` 并留痕（解冻时允许） |
| 旧 `MERGE_FROZEN` | **已移除（M1/F3）**，全链不存在，本仓库代码层无残留 |
| 消费方 | conductor.yml freeze guard、`freeze-yaml-check.yml`、tick 进程内守卫、各 gate 写 README/docs 前的 `if:` 守卫 |

> 若在扫描中出现 `MERGE_FROZEN`，只可能是遗留引用，应按唯一机制迁移到 `freeze.all`。