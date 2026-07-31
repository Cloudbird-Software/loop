# AGENTS.md — product-x

本仓库是 LOOP 体系的参考实现样板仓库。

## 快速入口
- 章程（人类唯一可编辑真源）：CHARTER.md
- loop pin：LOOP.yml
- 外部依赖登记：UPSTREAM.yaml
- CI 薄壳：.github/workflows/loop-*.yml（只引用 loop reusable workflow，零本地逻辑）

## 红线
- 不复制 loop 机制文件（gates/lenses/conductor/loopd/prompts/settings）—— CHARTER N9
- 不在样板里塞真实产品逻辑 —— CHARTER N8
- 不自动修正 GitHub ruleset/secrets —— CHARTER N3

## 工作流程
见 loop 仓 prompts/P-continue.md（通过 loopd CAS 领卡推进状态机）。
