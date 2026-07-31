# LOOP 控制面

> 让 AI 软件工厂从「能被使唤」变成「能自己跑」。

LOOP 是一个 GitHub 原生、以 issue/PR 为单源的 AI 软件工厂控制面。它把「继续」这句话自动转化为：找 ready 卡 → 实现 → 异构验证 → 门禁 → 合并 → 验收 → 通知 → 度量 → 升级。

## 这是什么 / 不是什么

**这是：**
- 一个运行在 GitHub Actions + Python 标准库上的控制面。
- 一套可复用的产品仓模板（见 `product-x/`）。
- 以 `CHARTER.md` 为唯一目标-需求-问题定义，以 `waves/` 为交付节奏。

**这不是：**
- 一个通用 CI/CD 框架。
- 一个需要外部数据库/SaaS 的系统。
- 一个保证模型永远正确的系统（模型输出只是待检验的输入）。

## 目录地图

```
loop/
├── .github/workflows/    # loop 自身 CI/gates/review + 调度型 workflow
├── bench/                # 四指标与 CHARTER Q 指标计算
├── cards/                # 已冻结的历史卡片存档（真源在 issues）
├── conductor/            # 核心编排：tick、retro、upgrade_ring、findings 等
├── docs/                 # 设计文档与验收剧本
├── gates/                # PR 门禁实现
├── lenses/               # audit 用 lens 脚本
├── loopd/                # 沙盒守护进程
├── policies/             # 策略配置
├── prompts/              # AI 提示词
├── product-x/            # 产品仓样板
├── seam_a/               # 模型路由
├── settings/             # ruleset 模板
├── tests/                # 测试
└── waves/                # 波次定义与验收标准
```

## 从零到接单的最短路径

1. **按 `templates/product-x/` 创建新产品仓**（或 fork `product-x`），并设为 Template Repository。
2. **配置凭证**：
   - GitHub token（`GH_TOKEN` / `GITHUB_TOKEN`）
   - 可选：`COPILOT_GITHUB_TOKEN`（强模型验收）
   - 可选：`LLM_GATEWAY_KEY`（promptfoo rubric）
   完整清单见 [`docs/环境变量清单.md`](docs/环境变量清单.md)。
3. **填写 `CHARTER.md`**：定义你的目标 G / Needs / Q 指标；人类审定后改 `last-human-edit` 日期。
4. **启动沙盒**：
   - 在 Trae 创建沙盒，填入最小环境变量集（`LOOP_ORG` / `LOOP_REPO` / `LOOP_WS` / `LOOP_ROLE` / `GH_TOKEN`）。
   - 启动命令执行 `loopd/bootstrap.sh`（校验 sha256 → 安装 gh/mise/jq → 部署 loopd → clone 产品仓 → 预热工具）。
   - 后台并行任务拉起 `loopd --daemon`、supervisor、心跳与日志采集。
5. **对 AI 说一句话**：
   > "继续"

AI 会加载 `prompts/P-continue.md`，扫描 open ready 卡，自动领卡、实现、开 PR、过门禁、合并。

更详细的沙盒配置与旧版点火记录见 [`docs/archive/点火测试剧本.md`](docs/archive/点火测试剧本.md) 与 [`docs/archive/Trae沙盒填写卡.md`](docs/archive/Trae沙盒填写卡.md)。

## 四份核心设计文档

- [`docs/强模型验收环.md`](docs/强模型验收环.md) — 模型输出如何变成可证伪断言
- [`docs/产品仓对齐架构.md`](docs/产品仓对齐架构.md) — loop 与 product 的边界
- [`docs/盲一半协议.md`](docs/盲一半协议.md) — impl / verify 异构约束
- [`docs/审查裁决-2026-07-30.md`](docs/审查裁决-2026-07-30.md) — 架构决策来源

## 机器人入口

如果你是进入本仓库的 AI，请先读 [`AGENTS.md`](AGENTS.md)。
