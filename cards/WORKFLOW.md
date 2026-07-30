# WORKFLOW.md — P4 闭环前的暂行工作流程

> **暂行流程继续生效** @2026-07-30 修订
>
> C-008 闭环已达成（一次），但仍有大量 V 卡未验证、F-002 未修。**暂行流程不停止**，直到：
> - 全部 V 卡 done 或 closed
> - F-002 修复并验证（建 C-015 修 ci.yml 加 merge_group）
> - gh 认证就绪，切回 loopd 正式体系
>
> **已知遗留（见 [F-002](./F-002.md)）**：product-x `ci.yml` 缺 `merge_group` 触发器，而 ruleset 启用了 `merge_queue`（ALLGREEN）规则。后果：任何走 merge queue 的 PR 会永久卡在 AWAITING_CHECKS。[C-015](./C-015.md) 已建卡修复（在 ci.yml `on:` 块加 `merge_group: { branches: [main] }`）。修复前 PR 合并需 admin break-glass。

## 0. 自动流转规则（核心，新增 @2026-07-30）

以下是暂行期的状态机推进规则，**每个 AI 会话都必须执行**：

### 0.1 C 卡 done → V 卡自动 ready
当 C-0NN 工作卡 `status: done`：
- 找到 `verify_target` 指向该 C 卡的 V-0NN 验证卡。
- 改 V 卡 `ready: false` → `ready: true`，评论"C 卡已 done，置 V 卡 ready"。
- 在 INDEX.md 的 V 表同步 ready 列。
- **执行者**：标 C 卡 done 的那个 AI（P-continue 第 5 节第 4 步）。或下一个进来的 AI（P-continue 第 1 节第 2 步 V 卡扫描）。

### 0.2 V 卡 FAIL → 建 F 卡
当 V-0NN 验证 `VERDICT=FAIL`：
- 新建 F-0NN（`first_seen: true`、`status: pending`、`ready: true`、evidence 客观可复现）。
- 不改原 C 卡状态（保持 done）。
- 在 INDEX.md 的 F 表登记。
- **执行者**：验证 AI（P-continue 第 7 节）。

### 0.3 F 卡复现成功 → 立即修
当 F-0NN 被下一个 AI 完整复现：
- 起修复卡 C-0NN（depends_on 含原 C 卡），在 INDEX.md 登记。
- F-0NN 标 done，评论"已复现，转 C-0NN 修复"。
- **立即领 C-0NN 动手修**，不要只建卡就走（P-continue 第 8 节第 2 步）。
- C-0NN done 后翻对应 V 卡 ready（若有，见 0.1）。
- **执行者**：复现 F 卡的那个 AI。

### 0.4 流转链全貌
```
C 卡 done → V 卡 ready:true → V 卡被领 → V 卡 PASS → V 卡 done（闭环）
                                   → V 卡 FAIL → F 卡建（ready:true）→ F 卡被领 → 复现成功 → C 修复卡建+立即修 → C done → V ready...（循环直到 PASS）
                                                                              → 复现失败 → 评论差异 → 下个 AI 仲裁
```

## 1. 角色定义（暂行期，单 AI 可切换角色）

| 角色 | 干什么 | 在本目录对应卡 |
|---|---|---|
| planner | 排工作卡 C-0NN，定义依赖与验收 | 排卡 + C-003（写 P3 提示词） |
| impl | 干工作卡 C-0NN，产出 commit/PR | C-001, C-002~C-012 |
| verify | 跑验证卡 V-0NN，产出 VERDICT；FAIL 时建 F-0NN | V-0NN, F-0NN |
| auditor | 扫 repo 产 Finding（暂行期暂不启用，等 C-002 完成 P2 提示词） | — |
| materializer | 物化 wave → Card issue（暂行期暂不启用，等 gh 认证 + [C-005](./C-005.md)） | — |

**暂行期允许**：单 AI 在一次会话内切换角色（先当 impl 做 C-001，再当 verify 跑 V-001）。loopd 正式体系禁止这么做（角色阀门 + ROLE_CREATE_MAP），届时切回。

## 2. AI 入口：我来了，该怎么找活

```
1. 读 INDEX.md → 找 ready:true & status:pending 的卡
2. 多张可选时，按优先级：
   a. F-0NN（首次发现）优先于 V-0NN 优先于 C-0NN
   b. 同类按 tier：critical > standard > trivial
   c. 同 tier 按 INDEX.md 顺序（依赖链上游优先）
3. 领卡前再读一遍该卡的 depends_on 卡，逐一确认 status:done
   - 任一未 done → 不领，在卡底评论"等 C-0XX"，去找下一张
4. 领卡：改 status:pending→in_progress，卡底评论"领卡 @沙盒ID @时间"
5. 干活 → 完成：改 status:in_progress→done，评论"完成 @commit"+acceptance 自检
```

## 3. 验证卡 V-0NN 执行规则

**前提**：`verify_target` 指向的工作卡 `status: done`。未 done 不要开始验证。

**执行**：
1. 拉工作卡对应分支 / commit。
2. 逐条跑 `acceptance`，每条记 PASS/FAIL + 客观证据（命令输出、文件路径、行号）。
3. 全 PASS → VERDICT=PASS，改 status:done，评论"VERDICT PASS @commit + 证据清单"。
4. 任一 FAIL → VERDICT=FAIL，**不要**改原工作卡状态（保持 done 等待复现判定），按第 4 节建 F-0NN。

## 4. 首次发现协议（核心规则）

当 V-0NN 验证 FAIL，验证 AI **必须**：

1. **不修改原工作卡 C-0NN**（保持 done，让 F-0NN 来承接问题）。
2. **新建 F-0NN 卡**（Finding 类型，`first_seen: true`），字段：
   - `linked_work: [C-0NN, V-0NN]`（关联原工作卡 + 触发验证卡）
   - `evidence:` 必须是**客观可复现**步骤，每条含：
     - 复现命令（精确到可粘贴执行）
     - 期望输出
     - 实际输出
     - 环境（沙盒 ID、commit SHA、时间、OS/工具版本）
   - `acceptance:` = "问题被完整复现 OR 差异被客观记录"
   - `status: pending`，`ready: true`
3. 在原 V-0NN 卡底评论"VERDICT FAIL → 建 F-0NN，待复现判定"。

**禁止**：F-0NN 的 evidence 里出现"我觉得""可能""似乎"等主观判断。要么是可粘贴复现的客观步骤，要么不要写。

## 5. 后续 AI 处理 F-0NN 的规则

第二个 AI 来处理 F-0NN 时，**必须先完整复现**：

1. 按 `evidence` 步骤逐条在自己沙盒里跑。
2. **能完整复现**（每条证据都能重现实际输出）→ 问题确认真实，按修复流程处理：
   - 起新工作卡 C-0NN（depends_on 包含原 C-0NN），标题注明"修复 F-0NN 复现的问题"
   - 改 F-0NN status:done，评论"已复现 @commit，转 C-0NN 修复"
3. **不能完整复现**（部分步骤重现不出来，或输出与记录不符）→ **不要修复**：
   - 在 F-0NN 卡底评论"差异：步骤 X 在我的沙盒输出 Y，与 evidence 记录的 Z 不符 @沙盒ID @commit @时间"
   - **不改 F-0NN 状态**（保持 pending，等下一个 AI 仲裁）
4. 后续第三个、第四个 AI 来时，**必须先读 F-0NN 的全部评论历史**：
   - 已有 N 个 AI 复现成功 + 0 个复现失败 → 修复
   - 已有 N 个复现失败 + 0 个复现成功 → 可能是环境差异，再读一遍 evidence 找环境变量差异，仍无法复现则评论"建议升级为环境依赖问题，转 planner 重新评估"
   - 既有成功又有失败 → 评论自己的复现结果，凑齐 ≥3 个样本后由 planner 仲裁

## 6. 阻塞与升级

- 卡 `blocked` 超过 2 个 AI 会话无人解 → 在卡底评论"升级：超期阻塞"，由 planner 重新评估依赖或拆卡。
- F-0NN 超过 3 个 AI 仍无法收敛（既无法完整复现也无法排除）→ 评论"升级：转环境差异调查"，由 planner 决定是否拆为多卡（按沙盒环境分）。

## 7. 暂行期与 loopd 正式体系的切换信号

满足以下**全部**条件后，本暂行流程停用，切回 loopd：
- [C-008](./C-008.md) 跑通一次完整 impl→verify→VERDICT=PASS→merge 闭环
- gh 认证就绪（可物化 issue）
- [C-006](./C-006.md) conductor tick 在 cron 上跑

切换时由 planner 在本文件顶部加"已停用，切回 loopd @日期"，并把所有未完成卡迁入 materializer wave。
