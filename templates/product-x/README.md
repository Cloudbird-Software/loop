# product-x — LOOP 体系参考实现样板仓库

> **product-x 不是真实产品**，它是 LOOP 体系的**样板仓**：
> 以最小、可复制的形态，示范"一个正确接入 loop 控制面的产品仓应该长什么样"。
> 真实产品仓库从本仓生成后，应当**整体替换 CHARTER.md 的 G/Q/U 段**（换成真实产品目标），
> 但**必须原样继承 N 段全部条目**（N 段是 LOOP 体系的红线，不随产品变化，CHARTER N9）。

---

## 目录结构（产品仓应该长什么样的活样例）

```
product-x/
├── CHARTER.md              # 唯一人类可编辑真源
├── LOOP.yml                # 对 loop 的 pin
├── UPSTREAM.yaml           # 外部依赖登记
├── README.md               # 本文件
├── AGENTS.md               # agent 上下文真源
├── .github/
│   ├── CODEOWNERS          # 敏感路径守卫
│   └── workflows/
│       ├── loop-ci.yml     # 薄壳：调用 loop/reusable-product-ci
│       ├── loop-gates.yml  # 薄壳：调用 loop/reusable-gates
│       └── loop-review.yml # 薄壳：调用 loop/reusable-review
├── .loop/
│   ├── CONTRACT.md         # 产品侧执行契约
│   ├── verify.sh           # 产品验证脚本
│   └── scripts/            # 产品侧脚本
├── contracts/              # schema / OpenAPI
├── waves/                  # 波次声明
└── tests/
    └── acceptance/         # 契约级测试
```

---

## 不留清单（CHARTER N9）

产品仓**不允许**持有下列 loop 机制文件的任何副本，只允许通过 `LOOP.yml` 的 pin +
`.github/workflows/loop-*.yml` 的 `uses:` 引用：

- `gates/` —— gate 实现由 loop 仓提供，复用 workflow 内 checkout loop 仓到 `.loop-control/`
- `lenses/`
- `conductor/`
- `loopd/`
- `prompts/`
- `settings/`

在产品仓里发现上述任何机制副本 → `gate/loop-conformance` 直接红（CHARTER Q7）。

CI 薄壳 `.github/workflows/loop-*.yml` 也**不允许加本地 run 步骤**——
只允许 `uses: Cloudbird-Software/loop/.github/workflows/reusable-*.yml@<sha>` 引用。
任何在薄壳里塞逻辑的改动 → CODEOWNERS 拦截 + `gate/loop-conformance` 红。

---

## 如何使用

1. 在 GitHub 上把本仓库设为 **template repository**
   （Settings → 勾选 "Template repository"）。
2. 用 **Use this template → Create a new repository** 生成新产品仓。
3. 改动 ≤5 处即可开工（CHARTER U1）：
   - 产品名（`LOOP.yml` 的 `product.name`、仓库本身的名字）
   - `CHARTER.md` 的 G/Q/U 段（换成真实产品目标；**N 段原样继承**）
   - `LOOP.yml` 的 `lenses.enabled`（按产品需要启用 lens 子集）
   - CI 的语言栈（`.github/workflows/loop-ci.yml` 的 `language` / `python-version` 等）
   - `.github/CODEOWNERS`（换成真实产品的 owner）
4. 把 `LOOP.yml` 的 `product.is_template` 改为 `false`。
5. 在 loop 仓的 `products.yml` 登记新产品仓（人类动作，AI 不得自行增删，CHARTER N10）。

---

## 相关章程

- **CHARTER N7**：不把模型的论断当作事实——强模型验收产物只是"待检验的输入"，
  非阻塞（`loop-review.yml` 的 `required: false`，CHARTER N9.7）。
- **CHARTER N9**：不在产品仓复制 loop 的机制文件——只允许 pin + reusable workflow 引用。

详见 `CHARTER.md`。

---

## 机制副本清零（R13-4）

本仓库**不持有**任何 loop 机制的本地副本。以下目录/文件已被删除或从未存在：

| 路径 | 状态 | 替代方案 |
|---|---|---|
| `gates/` | 已删除 | `.github/workflows/loop-gates.yml` → `loop/reusable-gates.yml` |
| `conductor/` | 已删除 | `loop/conductor/tick.py`（R11-6 可配置化） |
| `loopd/` | 已删除 | loop 侧 daemon 服务 |
| `prompts/` | 已删除 | loop 侧 `prompts/` 目录 |
| `settings/*.json` | 已删除 | loop 侧 `settings/` + `policy.yml` |
| `materialize.py` | 已删除 | loop 侧 `conductor/materialize.py` |

清理脚本：`scripts/purge-mechanism-copies.sh`（支持 `--dry-run`）
合规校验：`gate/loop-conformance` 检查 5 自动扫描，副本数必须 = 0
