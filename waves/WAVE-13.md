# WAVE-13 — 产品仓对齐：让复制出去的仓库自动跟上最新实践

> 产品仓不持有 loop 机制的副本，只持有一个**对 loop 的 pin 引用**。升级靠既有的第 8 环（冷静期 + 重放 + 自动回退），对齐靠 `gate/loop-conformance` 强制。

**依赖**：WAVE-10 全绿 + R11-1（gates.yml 可复用）+ R11-6（tick.py 收归单一实现）。
R13-1 是 R13-2/R13-3 的前置；R13-4 依赖 R13-3；R13-5/R13-6 可与 R13-3 并行。

**设计依据**：`docs/产品仓对齐架构.md`、`templates/product-x/CHARTER.md`、`templates/product-x/LOOP.yml`、`products.yml`、`DECISIONS.md` ADR-007 ~ ADR-009。

**回答用户的原问题**：product-x 里应当留下的只有四类东西——① 产品自己的 CHARTER.md（唯一必须人类改的文件）；② `LOOP.yml`（钉住 loop 的 tag + 40 位 SHA）；③ 几个薄壳 workflow（只做 `uses: Cloudbird-Software/loop/.github/workflows/reusable-*.yml@<sha>`）；④ 产品自己的源码与测试。**不留**：gates / lenses / conductor / loopd / prompts / settings 的任何副本。复制方式用 GitHub **template repository**（一次性播种、无 fork 关系、历史干净），而不是 fork。

---

## 本波次的检查方法（Wave-level Gate）

1. **真做一次复制**：从 product-x 模板新建一个一次性仓库 `product-probe`，
   除填 CHARTER.md 外**不做任何改动**，push 一个空 PR。要求：CI 全绿，全部门禁真实执行（日志可见每道 gate 的 exit=0），
   `gate/loop-conformance` 绿。改动点计数必须 ≤5（对应 CHARTER Q2）。
2. **副本为零**：在 `product-probe` 与 `product-x` 上跑 `gate/loop-conformance`，
   报告的机制文件副本数均为 0。
3. **pin 生效**：把 `LOOP.yml` 的 `loop.sha` 改成一个旧 SHA，`gate/loop-conformance` 必须红并给出落后 tag 数与天数。
4. **薄壳未被魔改**：在 `product-probe` 中给薄壳 workflow 加一行本地逻辑，`gate/loop-conformance` 必须红。
5. **升级链路真跑**：在 loop 打一个新 tag，观察第 8 环在 `product-probe` 上自动开出 bump PR（**只开 PR，不直推**），
   且该 PR 走完全相同的门禁、无任何豁免。
6. **回退可用**：故意让新 tag 的 reusable workflow 失败，确认自动回退到上一个 pin 并开 Incident。
7. 实验结束后删除 `product-probe`。

---

## 卡片

```json loop
{
  "schema": 1,
  "id": "R13-1",
  "objective": "loop 侧 reusable workflows",
  "title": "把产品仓需要的 CI / gates / review 全部实现为 loop 的 workflow_call 复用工作流",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G5", "N14"],
  "paths": [
    ".github/workflows/reusable-product-ci.yml",
    ".github/workflows/reusable-gates.yml",
    ".github/workflows/reusable-review.yml"
  ],
  "blocked_by": "R11-1",
  "acceptance": [
    "三个 workflow 均为 `on: workflow_call`，输入参数化（profile / lenses / gate 集合 / 语言栈 / 是否启用 review），无任何产品特定逻辑",
    "reusable-gates.yml 内部只调用 gates/run_gates.py，保持『未执行即失败』语义；产品仓无法通过传参把某道 gate 关成 SKIP —— 只能通过 policy.yml 的 profile 显式声明，且关闭动作会被记录进 evidence",
    "reusable-product-ci.yml 覆盖 lint / test / build，语言栈通过输入选择，缺失工具链时红而非跳过",
    "reusable-review.yml 封装 WAVE-12 的评审环，默认 `required: false`",
    "三者均声明最小 `permissions:`，并要求调用方显式传入所需 secrets（不使用 `secrets: inherit`）",
    "在 loop 自身的 pr-ci.yml 上先自用一次（吃自己的狗粮），确认可用后再供产品仓调用"
  ],
  "verify": "从一个临时仓库以 workflow_call 调用三者，确认无需在调用侧写任何逻辑即可跑通"
}
```

```json loop
{
  "schema": 1,
  "id": "R13-2",
  "objective": "gate/loop-conformance",
  "title": "实现产品仓合规门禁：pin 新鲜度、必需文件、薄壳完整性、机制副本为零",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G5", "N14"],
  "paths": ["gates/gate_conformance.py", "tests/test_gate_conformance.py"],
  "blocked_by": "R13-1",
  "acceptance": [
    "检查 1 —— pin 存在且合法：LOOP.yml 存在，loop.sha 是 40 位十六进制且在 loop 仓真实可达",
    "检查 2 —— pin 新鲜：落后主干 ≤ max_lag_tags(默认 2) 个 tag 且 ≤ max_lag_days(默认 30) 天，超出即红",
    "检查 3 —— 必需文件齐备：CHARTER.md（含机器可读索引段且 last-human-edit 不为 PENDING）、LOOP.yml、UPSTREAM.yaml、薄壳 workflow",
    "检查 4 —— 薄壳未被魔改：薄壳 workflow 的内容哈希与 loop 侧模板一致（允许仅 `with:` 参数不同），出现任何本地 run 步骤即红",
    "检查 5 —— 机制副本为零：产品仓中不得存在 gates/ lenses/ conductor/ loopd/ prompts/ settings/ 下与 loop 同名的实现文件；发现即红并列出文件清单",
    "检查 6 —— 薄壳引用的 reusable workflow 必须钉 40 位 SHA 且该 SHA 与 LOOP.yml 的 loop.sha 一致",
    "tests 对六项检查各覆盖至少一个失败用例与一个通过用例",
    "该 gate 同时在 loop 侧以『对全部注册产品仓做体检』的定时形式运行，结果汇总为一张周报"
  ],
  "verify": "拿一个人为破坏的产品仓副本跑一遍，六项必须逐一报红且信息可定位"
}
```

```json loop
{
  "schema": 1,
  "id": "R13-3",
  "objective": "product-x 转为真正的模板仓",
  "title": "product-x 落地 CHARTER.md / LOOP.yml / 薄壳 workflow，并设为 GitHub template repository",
  "repo": "product-x",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G2", "G5"],
  "paths": [
    "product-x/CHARTER.md",
    "product-x/LOOP.yml",
    "product-x/.github/workflows/loop-ci.yml"
  ],
  "blocked_by": "R13-1",
  "acceptance": [
    "把 loop 仓 templates/product-x/CHARTER.md 落到 product-x 根目录。该文件由 AI 代拟，含 P/U/G1-G4/Q1-Q8/N1-N10 与 GRIPE BOX 与机器可读索引段，末尾 `last-human-edit: PENDING`",
    "**人类必须做的事**：仓库主人逐条确认或修改 CHARTER 内容，并把 last-human-edit 改成真实日期。在此之前 gate/loop-conformance 检查 3 会红，这是刻意设计——章程是唯一不可由 AI 终局裁定的文件",
    "落地 LOOP.yml（模板见 loop 仓 templates/product-x/LOOP.yml），loop.sha 填当前 loop 主干 40 位 SHA",
    "新增薄壳 .github/workflows/loop-ci.yml：只做 `uses: Cloudbird-Software/loop/.github/workflows/reusable-product-ci.yml@<sha>` 与 reusable-gates，本地零 run 步骤；触发含 pull_request / merge_group / push(branches: main)",
    "旧的 ci.yml 在薄壳跑通并观察一个完整周期后删除；删除前后 required check 名保持一致，避免出现『required 但永不上报』的挂起（切换清单写进 PR 描述，由人类在 Settings 同步）",
    "product-x 作为模板仓的定位写进其 README：它示范 LOOP 体系，不承载真实产品逻辑（对应 CHARTER N7）"
  ],
  "verify": "从模板新建 product-probe，只填 CHARTER 即通过全部门禁；改动点计数 ≤5",
  "human_action": "① 审定并签署 product-x 的 CHARTER.md；② 在 GitHub Settings 勾选 Template repository；③ 同步 required check 名单"
}
```

```json loop
{
  "schema": 1,
  "id": "R13-4",
  "objective": "product-x 机制副本清零",
  "title": "删除 product-x 中 gates / conductor 等 loop 机制的本地副本",
  "repo": "product-x",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G5", "N14"],
  "paths": ["product-x/.loop/gates/", "product-x/conductor/"],
  "blocked_by": "R13-3",
  "acceptance": [
    "删除 .loop/gates/ 下的 gate 实现副本（gate_paths.py / gate_verdict.py 等），改由 reusable-gates 从 loop 侧 checkout 提供",
    "删除 conductor/ 下与 loop 同名的实现副本（tick.py 等），改由 loop 侧单一实现服务（R11-6 已使其可配置化）",
    "materialize.py 的 4.5KB 模板桩一并删除——它既不是拷贝也不是实现，是纯粹的混淆源",
    "删除必须发生在薄壳跑通之后：PR 描述中给出『删除前后各一次完整 CI 全绿』的两条运行链接",
    "gate/loop-conformance 的检查 5 在本卡合并后报告副本数 = 0",
    "product-x 保留的目录结构与文件清单写进其 README，作为『产品仓应该长什么样』的活样例"
  ],
  "verify": "删除后再开一个空 PR，确认所有门禁仍真实执行（日志逐道可见），而非因文件消失而回到 SKIP"
}
```

```json loop
{
  "schema": 1,
  "id": "R13-5",
  "objective": "产品仓注册表与 fan-out",
  "title": "template-sync：由 products.yml 驱动，把种子文件漂移以 PR 形式扇出到全部产品仓",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G5"],
  "paths": [".github/workflows/template-sync.yml", "products.yml"],
  "blocked_by": null,
  "acceptance": [
    "products.yml 作为产品仓注册表的唯一真源，字段含 repo / 创建日期 / loop pin / 负责人 / 启用的 lenses / gates profile；新产品仓上线必须先登记",
    "template-sync.yml 按 products.yml 的 sync.seed_files 扇出：`create-only` 类文件（如 CHARTER.md）仅在缺失时创建，`replace` 类文件（如薄壳 workflow）随模板更新",
    "**只开 PR，绝不直推**（open_pr_only: true 必须被代码强制，而非仅写在配置里）；扇出 PR 走与普通 PR 完全相同的门禁，豁免数为 0",
    "扇出 PR 标题含 `[template-sync]` 与源模板 SHA，便于聚合与回溯；同一漂移在同一仓库只保留一张开着的 PR（幂等）",
    "对未在 products.yml 登记但引用了 loop reusable workflow 的仓库，定时任务开 Incident 告警（防止影子产品仓脱管）",
    "扇出失败必须红并开 Incident，不得静默"
  ],
  "verify": "改一处种子文件，确认在 product-probe 上开出 PR 且该 PR 的门禁与普通 PR 一致；重跑一次确认不产生第二张 PR"
}
```

```json loop
{
  "schema": 1,
  "id": "R13-6",
  "objective": "loop 自身进入产品仓的升级环",
  "title": "把 loop 登记进产品仓 UPSTREAM.yaml，走第 8 环冷静期 + 重放 + 自动回退",
  "repo": "product-x",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G5", "G1"],
  "paths": ["product-x/UPSTREAM.yaml", "conductor/loop_pin.py"],
  "blocked_by": "R13-3",
  "acceptance": [
    "product-x/UPSTREAM.yaml 新增 `Cloudbird-Software/loop` 条目，pin 为 tag + 40 位 SHA，附 sha256/来源说明与 min_age（冷静期）",
    "新增 conductor/loop_pin.py：解析 LOOP.yml 与 UPSTREAM.yaml 中的 loop pin，供第 8 环升级、gate/loop-conformance、template-sync 三方共用同一解析实现（避免又出现三份平行解析）",
    "loop 发新 tag 后，产品仓在冷静期届满时自动开 bump PR：同步更新 LOOP.yml.loop.sha、UPSTREAM.yaml 与全部薄壳 workflow 的 `@<sha>`，三者必须一致（一致性由 gate/loop-conformance 检查 6 保证）",
    "bump PR 必须先跑 bench 重放：新 pin 下的四指标不得劣化超过 policy.yml 的阈值，否则自动关闭 PR 并开 Incident",
    "自动回退：若 bump 合并后的首个周期内出现门禁性失败，自动开回退 PR 恢复上一个 pin，并开 Incident 记录",
    "min_age 冷静期不得为 0，具体值写进 policy.yml"
  ],
  "verify": "在 loop 打一个测试 tag，观察 bump PR 的开出、bench 重放、以及人为制造失败后的自动回退全链路"
}
```
