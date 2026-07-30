# cards/ — 暂行工作卡仓库

> 本目录是 **P4 闭环跑通之前** 的暂行卡存储。等 [C-008](./C-008.md) 跑通 impl→verify→VERDICT→merge 全闭环后，切回 loopd 正式体系（CAS 领卡 + GitHub issue 物化）。

## AI 入口判定（任何 AI 来这里先读这段）

1. 读 [INDEX.md](./INDEX.md) 找一张 `ready: true` 且 `status: pending` 的卡。
2. 读 [WORKFLOW.md](./WORKFLOW.md) 第 2 节确认自己该当哪个角色。
3. 若是工作卡（C-0NN）：先看 `depends_on`，全部 `status: done` 才能动手；任一未完成则**不要开始**，在卡底评论说明"等 C-0XX 完成"。
4. 若是验证卡（V-0NN）：先确认 `verify_target` 指向的工作卡 `status: done`；未完成则不要开始。
5. 若是 Finding 卡（F-0NN）：必须先完整复现（见 [WORKFLOW.md](./WORKFLOW.md) 第 4 节"首次发现协议"）。

## 卡片类型

| 前缀 | 类型 | type 字段 | 创建者角色 |
|---|---|---|---|
| C-0NN | 工作卡 | Card | planner（暂行期：本目录手工建立） |
| V-0NN | 验证卡 | Verify | verify（暂行期：本目录手工建立） |
| F-0NN | 首次发现 | Finding | verify AI（暂行期：验证失败时由验证 AI 新建） |

## 字段约定（对齐 [materialize.py](../conductor/materialize.py) 四校验）

```yaml
id: C-0NN              # 必填，唯一
title:                  # 必填，一句话标题
type: Card | Verify | Finding   # 必填
role: impl | verify | planner | auditor | materializer | incident  # 必填
tier: trivial | standard | critical   # 必填，critical 触发更严门禁
charter: ["G0"]        # 必填，CHARTER.md 未立前用 G0 占位
paths: [path1, path2]  # 必填，工作范围；两两不交叉（materialize 校验）
acceptance:            # 必填，≥1 条，客观可验
  - 条目1
  - 条目2
depends_on: [C-0XX]    # 可选，前置卡 id 列表
ready: true | false    # 必填，depends_on 全 done 时为 true
status: pending | in_progress | done | blocked   # 必填
verify_target: C-0NN   # 仅 Verify 卡，指向被验证的工作卡
linked_work: [C-0NN, V-0NN]  # 仅 Finding 卡，关联原工作卡+验证卡
first_seen: true       # 仅 Finding 卡，固定为 true
evidence:              # 仅 Finding 卡，客观复现步骤
  - 步骤1
  - 步骤2
```

## 状态推进规则（暂行期，靠 AI 改 markdown 字段）

- 领卡：`status: pending` → `in_progress`，在卡底评论"领卡 @沙盒ID @时间"。
- 完成：`status: in_progress` → `done`，在卡底评论"完成 @commit"，列出 acceptance 自检结果。
- 阻塞：`status: in_progress` → `blocked`，在卡底评论说明阻塞原因 + 等 C-0XX。
- `ready` 字段：依赖卡全部 done 后，下一个进来的 AI 把 `ready: false` → `ready: true`，并在卡底评论"依赖满足，置 ready"。

## 与 loopd 正式体系的差异（暂行期）

| 维度 | 暂行期（本目录） | loopd 正式 |
|---|---|---|
| 卡存储 | 本地 markdown | GitHub issue（materializer 物化） |
| 领卡/状态推进 | AI 改 markdown 字段 | loopd CAS 领卡 + 租约 |
| 角色阀门 | 验证 AI 临时拥 Finding 创建权 | auditor 才能建 Finding |
| 僵尸回收 | 靠人工看评论 | loopd reaper + conductor tick |
| 切换时机 | [C-008](./C-008.md) 跑通闭环后 | — |
