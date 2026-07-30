# WAVE-11 — 门禁真实化与供应链卫生

> 让 8 道门禁从"名义存在"变成"每一道都被跑过、每一道都被证明过会红"，并把供应链与密钥的可信度补齐。

**依赖**：WAVE-10 全部关闭后方可开工（本波次的所有验证都建立在"绿灯可信"之上）。
本波次内部 R11-1 → R11-2/R11-5 存在依赖，其余卡片可完全并行。

**来源**：`docs/审查裁决-2026-07-30.md` 的 P1-2 / P1-5 / P2-8 / P2-9 / P2-10 / F-D(tick 分叉)。

---

## 本波次的检查方法（Wave-level Gate）

1. **每道门禁都有红过的证据**：`gh pr list -R Cloudbird-Software/loop --search "label:negative-proof"`
   返回 ≥8 条已关闭的 PR，每条对应一道 gate 的"故意让它红"实验，且 PR 正文含失败的 check 链接。
   **这是本波次唯一的承重验收**——一道 gate 若从未在真实 PR 上红过，就等于不存在。
2. **异构真的被强制**：把 `ROUTING.yaml` 里 verify 的 model 临时改成与 impl 相同，开 PR，
   `gate/heterogeneity` 必须红。
3. **供应链无占位**：`grep -c 'w0-fill' UPSTREAM.yaml` 输出 `0`。
4. **无未钉 SHA**：两仓 `actions-pinned` 扫描均输出 `bad: 0`。
5. **无凭证入 URL**：`grep -rn 'x-access-token:\$' .github/` 命中数为 0。
6. **无跨仓分叉**：`diff <(loop 侧 tick.py) <(product-x 侧 tick.py)` —— product-x 侧文件已删除，
   diff 命令因文件不存在而失败即为通过；`gate/loop-conformance` 报告机制副本数 = 0（与 WAVE-13 联合验收）。

---

## 卡片

```json loop
{
  "schema": 1,
  "id": "R11-1",
  "objective": "八道门禁全部接线并逐个证明会红",
  "title": "新增 gates.yml 复用作业，把全部 gate 接进两仓 CI，并为每道 gate 留下负向证据",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N11"],
  "paths": [".github/workflows/gates.yml", "tests/test_gates_negative.py"],
  "blocked_by": "R10-3",
  "acceptance": [
    "新增 .github/workflows/gates.yml，以 workflow_call 形式暴露，输入 profile / target_repo，内部调用 gates/run_gates.py；loop 自身的 pr-ci.yml 与 product-x 的 ci.yml 均通过它执行门禁（product-x 侧接线在 R13-3 完成）",
    "loop 仓 9 个既有 workflow 中 `gate_` 引用数从 0 变为 ≥1（当前 loop 的 4 个真实 gate 从未被任何 workflow 调用过）",
    "tests/test_gates_negative.py：为 charter / diffsize / license / minage / paths / testown / upstream / verdict 八道门禁各写一个必然失败的输入，断言退出码非零；再各写一个必然通过的输入断言为零",
    "每道 gate 在真实 PR 上红过一次，PR 打 `negative-proof` 标签后关闭（不合并），链接汇总进本卡的完成评论",
    "gates.yml 的 job 名与 settings 快照中的 required check 名逐字一致，且与 R10-4 修好的 settings/main-protection.json 对得上"
  ],
  "verify": "reviewer 逐条打开 8 个 negative-proof PR，确认 check 确实是红的且失败原因就是对应 gate；只看 tests 通过不算",
  "note": "复现结论：loop 8 道门禁里真实有逻辑的是 minage/paths/testown/verdict 四个，另外四个已在本次 PR 中实现。本卡负责『接线 + 证明』，不负责重写逻辑"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-2",
  "objective": "CI 强制 impl 与 verify 模型异构",
  "title": "gate/heterogeneity —— 把『独立验证』从文档承诺变成机器强制",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3", "G4", "N12"],
  "paths": ["gates/gate_heterogeneity.py", "tests/test_gate_heterogeneity.py"],
  "blocked_by": "R11-1",
  "acceptance": [
    "gate_heterogeneity.py 读取 ROUTING.yaml，断言 impl 与 verify 两条 route 的 provider **且** model 均不相同；相同则非零退出并打印两条 route 的完整解析结果",
    "同时校验 evidence：对一张已产出 VERDICT 的卡，断言 verdict 记录中的 verifier model 与 impl 记录中的 model 不同、session id 不同；同会话自证一律判失败",
    "同样校验 review 域：review/accept 与 review/reproduce 两条 route 必须异构（强模型不得自己复现自己的 claim）",
    "ROUTING.yaml 中任何声称异构的注释若与实际配置矛盾，gate 必须红——本次审查中 ROUTING.yaml:49 的注释谎称『不同 provider』而实际两边都是 qwen/qwen3-max，这类情况必须被机器抓住",
    "tests 覆盖：同 provider 同 model、同 provider 异 model、异 provider 三种组合的判定",
    "接入 gates.yml 并成为 loop 与 product-x 的 required check"
  ],
  "verify": "把 ROUTING.yaml 的 verify route 临时改回 qwen/qwen3-max，确认 CI 红；改回后确认绿"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-3",
  "objective": "供应链哈希回填与安装校验",
  "title": "UPSTREAM.yaml 回填全部 sha256 占位，bootstrap.sh 安装前强制校验哈希",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3", "N6"],
  "paths": ["UPSTREAM.yaml", "loopd/bootstrap.sh"],
  "blocked_by": null,
  "acceptance": [
    "UPSTREAM.yaml 中 10 处 `w0-fill` 占位全部替换为真实 sha256（当前仅 sst/opencode 一项是真 hash）；无法取得哈希的条目必须给出原因并降级为显式 `sha256: unavailable` + `risk_accepted_by` 字段，不得留占位",
    "bootstrap.sh 中 `curl -fsSL https://mise.run | bash` 改为：先下载到临时文件 → 校验 sha256 与 UPSTREAM.yaml 一致 → 再执行；校验失败则非零退出",
    "gate_upstream 扩展为：发现任何 `w0-fill` 即红",
    "PR 描述中澄清定性：本项违反的是 UPSTREAM.yaml 自身的 sha256 规则，**不是** CHARTER N6（N6 管的是『不从非官方源安装』，mise.run 是官方源）。专家在此处归因有误，修复动作不变但记录必须准确",
    "两仓 `grep -c w0-fill UPSTREAM.yaml` 均为 0"
  ],
  "verify": "reviewer 随机抽 3 个条目，独立下载并计算 sha256，与文件比对"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-4",
  "objective": "密钥最小权限与轮换策略",
  "title": "scribe token 移出 URL、canary 凭证降权、建立密钥清单与轮换周期",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N15"],
  "paths": [".github/workflows/scribe.yml", ".github/workflows/canary.yml", "docs/密钥清单.md"],
  "blocked_by": null,
  "acceptance": [
    "scribe.yml 中两处 `https://x-access-token:${GH_TOKEN}@…` 形式的 remote URL 全部改为 `git config http.extraheader` 或 `gh auth setup-git`，令牌不再出现在 URL 中（URL 会进 git 配置、reflog 与进程列表）",
    "新增 docs/密钥清单.md：逐条登记全部凭证（按字面 secret 名 9-11 个 / 按逻辑凭证组 6 组，两种口径都要列清并说明差异），字段含 名称、承载身份、所需最小权限范围、使用者 workflow、轮换周期、上次轮换日期、责任人",
    "canary.yml 中 LOOP_CANARY_TOKEN 的用途逐行注明；凡 GITHUB_TOKEN 能胜任之处一律改用 GITHUB_TOKEN + 显式 permissions 块",
    "所有 workflow 顶层补最小 `permissions:`（默认 `contents: read`），按需在 job 级放开",
    "澄清并修正记录：canary **没有**用 admin 绕过分支保护——canary-chain.sh:76-79 明确拒绝 --admin 并改走 GraphQL enqueuePullRequest，线上 ruleset 的 bypass_actors 为空。真实风险仅是『高权限 PAT 存为 repo secret』这一密钥卫生问题，本卡按此定性修复",
    "docs/密钥清单.md 中列出仍需人类操作的项（轮换、降权、删除），并同步进 HUMAN-TODO.md"
  ],
  "verify": "reviewer 执行 `grep -rn 'x-access-token' .github/` 确认 0 命中；并核对每个 workflow 的 permissions 块确实是最小集"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-5",
  "objective": "锁文件门禁落地",
  "title": "实现 gates/lockdiff.py —— 依赖锁文件变更必须与 UPSTREAM.yaml 一致",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3", "N6"],
  "paths": ["gates/lockdiff.py", "tests/test_lockdiff.py"],
  "blocked_by": "R11-1",
  "acceptance": [
    "lockdiff.py 当前是 6 行 skeleton（print OK; exit 0），改为真实实现：解析 PR 中锁文件（package-lock.json / uv.lock / requirements.txt 等，按仓库实际存在者）的 diff",
    "任何新增或升级的依赖，若未在 UPSTREAM.yaml 登记，或登记的版本/哈希与锁文件不符，则非零退出并列出差异项",
    "仅删除依赖的 diff 允许通过；纯 transitive 变更给出 warning 但不红（阈值写进 policy.yml，不硬编码）",
    "tests 覆盖：新增未登记依赖（红）、升级到未登记版本（红）、删除依赖（绿）、无锁文件变更（绿）",
    "接入 gates.yml"
  ],
  "verify": "构造一个新增未登记依赖的 PR，确认 CI 红"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-6",
  "objective": "消除 tick.py 跨仓分叉",
  "title": "tick.py 收归 loop 单一实现，通过参数而非分叉支持两仓差异",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G5", "N14"],
  "paths": ["conductor/tick.py"],
  "blocked_by": null,
  "acceptance": [
    "把两仓 tick.py 的 25 行实质差异（LOOP_ROOT 解析、CONTROL_REPO 变量、product-x 侧多出的 canary stub）全部收敛为 loop 单一实现的配置项：由环境变量/LOOP.yml 驱动，而非两份代码",
    "product-x 侧的删除动作由 R13-4 执行；本卡只负责让 loop 版本能同时服务两种形态，并在 PR 描述中给出『product-x 侧删除后仍可工作』的运行证据",
    "为差异点补测试：LOOP_ROOT 未设置 / 设置为相对路径 / 设置为绝对路径三种情形",
    "澄清记录：两份文件并非相同拷贝而是**已分叉的兄弟**（diff 显示 25 行实质差异），materialize.py 更是 21KB 全实现 vs 4.5KB 模板桩，根本不构成拷贝。专家『两仓各存 33.8KB 拷贝』的措辞过头，修复方向不变但记录须准确",
    "pytest 全绿"
  ],
  "verify": "在两种环境变量组合下各跑一次 tick.py --dry-run，输出符合预期"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-7",
  "objective": "promptfoo 脚手架落地",
  "title": "补齐 promptfoo 配置与用例，让 nightly-rubric 从『注释掉 + EXIT=0』变成真评测",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3", "G4"],
  "paths": ["promptfoo/"],
  "blocked_by": null,
  "acceptance": [
    "新增 promptfoo/ 目录，含 promptfooconfig.yaml 与至少 5 条针对 prompts/P-*.md 的断言用例（覆盖：不得输出 PASS/FAIL 只输出 claim、必须含 repro、必须含 falsifier、不得自证、超出 paths 即拒绝）",
    "评测在无网络/无 API key 时以明确的 SKIPPED_NO_CREDENTIALS 非零码退出，由调用方决定是否降级——绝不静默 EXIT=0",
    "nightly-rubric.yml 中被注释掉的 promptfoo 调用恢复为真实调用（该文件由 R14-2 拥有，本卡只提供配置与文档，接线在 R14-2 完成）",
    "promptfoo/README.md 说明如何本地复跑与如何新增用例",
    "promptfoo 版本在 UPSTREAM.yaml 中已登记且钉版本（与 R11-3 协作，本卡不改 UPSTREAM.yaml，把需登记项写进 PR 描述交由 R11-3 收口）"
  ],
  "verify": "本地带 key 跑一次真实评测并粘贴结果；再不带 key 跑一次确认是明确失败而非假绿"
}
```

```json loop
{
  "schema": 1,
  "id": "R11-8",
  "objective": "workflow 安全 lens 真跑",
  "title": "把 zizmor / pinact 等 workflow 静态检查接进 PR 门禁",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N6"],
  "paths": [".github/workflows/ci-security.yml", "lenses/ci-security.sh"],
  "blocked_by": null,
  "acceptance": [
    "新增 lenses/ci-security.sh，调用 workflow 静态检查工具（工具选型必须先登记进 UPSTREAM.yaml 并钉版本+哈希，且须通过 GitHub Advisory DB 检查）",
    "新增 .github/workflows/ci-security.yml，在 pull_request 上运行该 lens，输出 SARIF",
    "工具缺失时以非零退出并打印 LENS_NOT_EXECUTED，绝不静默跳过（audit.yml:104-106 的『缺脚本 continue』模式在本卡中不得重现）",
    "首次运行必然报出既有问题；本卡允许设立一条基线白名单文件，但白名单每一项必须写明理由与到期日，且 lens 对『白名单项被修好后仍留在白名单』要报警",
    "SARIF 结果经 .loop/scripts/sarif2evidence.py 转为 evidence，为 WAVE-14 的 lens→工单打通做准备"
  ],
  "verify": "构造一处未钉 SHA 的 action 引用，确认 lens 报出并使 CI 红"
}
```
