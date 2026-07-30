# test-change-approved 标签流程

> `gate_testown.py` 在检测到 PR 修改了 `tests/acceptance/**` 下的文件时，
> 要求 PR 必须携带 `test-change-approved` 标签，否则门禁红。

## 1. 为什么要这个门禁

`tests/acceptance/**` 是 CODEOWNERS 保护路径（owner = 人类）。
验收测试定义了"完成"的机器可判定标准——如果 agent 可以随意修改验收测试来让测试通过，
就等于让被验证者自己定义验证标准，整套验证体系失效。

此门禁确保：
- agent 修改 acceptance 测试 → 红灯
- 人类在 PR 上加 `test-change-approved` 标签 → 绿灯
- 标签的添加记录在 PR 历史中，可审计

## 2. 触发条件

当 PR 的 diff 包含以下任一路径的文件变更时，门禁激活：
- `tests/acceptance/**`（任何深度的子目录）

## 3. 通过条件

PR 必须携带 `test-change-approved` 标签。

## 4. 人类操作流程

### 4.1 正常审批流程（推荐）

1. 审阅 PR 中对 `tests/acceptance/**` 的修改
2. 确认修改原因：
   - 新增验收测试（新功能卡）→ 通常批准
   - 修正验收测试中的错误描述 → 审查后批准
   - 弱化断言（降低期望值/放宽条件）→ **通常拒绝**，除非有充分理由
3. 在 PR 页面：Labels → 输入 `test-change-approved` → 选中

### 4.2 批量操作

如果多个 PR 都需要此标签（如波次末批量调整验收测试）：
```bash
# 为指定 PR 添加标签
gh pr edit <PR_NUMBER> --add-label test-change-approved
```

### 4.3 拒绝场景

以下修改**不应**获得 `test-change-approved` 标签：
- 降低断言严格度（如 `assertEqual` → `assertTrue`）
- 删除失败的验收测试用例
- 修改验收测试以匹配实现 bug
- 将 `assert` 包裹在 `try/except` 中吞掉失败

## 5. 标签管理

- `test-change-approved` 是仓库级 label
- 首次使用前需创建：Settings → Labels → New label
  - Name: `test-change-approved`
  - Color: `#0E8A16`（绿色，表示已批准）
  - Description: `Human-approved changes to tests/acceptance/**`

## 6. 与 CODEOWNERS 的关系

CODEOWNERS 已经要求 `tests/acceptance/**` 的 PR 需要 Code Owner review。
此标签是额外的机器可判定门禁：
- CODEOWNERS review → 人类审阅代码（需要人工判断）
- `test-change-approved` label → 机器可验证的批准标志（gate 可自动检查）

两者互补：review 可能被 dismiss，但 label 不会自动移除。
