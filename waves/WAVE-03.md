# WAVE-03 · 执行自治（72h 零干预演示）★ 无人化的真正起点

> **目标**：执行半消失——dispatcher 自动把**人类仍批量投放的卡**分给沙盒执行，72 小时零人工干预；背压、scoped token、escalation、kill switch 全部就位。**关键区分（防腐烂总闸门）**：卡仍由人类批量投放（Planner 依旧手动），投放后全程无人干预。
> **入口条件**：W2 关闭判定中"事件-投影对账 72h diff=0"**移入本波出口 Z 判定**（D7 采纳，避免依赖本波才建的对账工具自举）；入口其余项：W2 组件全绿；escalation.yml（低强度启动）、dispatcher 四数值已人类审批并手写进 policy.yml；6 张演示卡已备（demo_cards.json）。
> **tick.py 接线纪律（评审 H1/B1/B9 采纳）**：`conductor/tick.py` 为**单 owner = W3-TK**（专门接线卡）。W3-4（escalate 库）、W3-5（digest 库）、W3-9（对账库）只产纯库函数，**不写 tick.py**；由 W3-TK 把它们注册进 STEPS 并对 cas 状态变更接入事件发射。materializer 据此强制，杜绝"无人可注册"。
> **波结构**：W3-1（dispatcher+policy.yml 写入）/W3-2/W3-3 为 dispatcher 三件套；W3-4/5/9/TK 为库→接线链（TK blocked 依赖 4/5/9）；W3-8/9/10/TK 是回看/补链卡与机制卡并行；W3-7 72h 演示 block 全部机制卡（1..6,9,10,TK）。全套 critical 配异构 V3-x（N8.5/N12）。

## 时间积累项回看（W0/W1/W2 遗留的"需时间积累"测试项）

> 按用户指令回看先期波次中依赖**时间积累**才能判定的测试项；不满足者开新卡 W3-8/W3-9/W3-10 一并处理。**原则**：时间积累判据一律放波级 Gate（跨多日），**不放单卡 AC**（评审 B11：单卡 done 时点不可能为真）。

| 回看项 | 出处（手册 §） | 判定标准 | 当前状态 | 结论 |
|---|---|---|---|---|
| 病链连续绿 48h | W0 波后关闭 | 最近 48h conductor CI 全 success | W1 入口已确认绿（gh run view 达 48h 累计） | 非本波阻塞 |
| canary 连续 3 晚 12/12 | §5.3/§5.4 正证 5（W1-9） | `canary/history.jsonl` 累计 ≥3 个不同自然日全拦截 | **仅单快照** `canary/results.json`，无跨日历史 | **❌ → W3-8**（累计判定放波级 Z） |
| canary 链路假报警 | W1-9 遗留（实测） | 关 issue 失败被误判"链路断"，每小时 noise incident + product-x 泄漏合成票 | `.loop/scripts/canary-chain.sh` 清理失败走 exit1 | **❌ → W3-8**（解耦） |
| 事件-投影对账连续 72h diff=0 | §6.4-4 / W2 关闭判定 | `state_reconcile.py --check` diff==0；tick 对账步累计 72h | `events.py`/`state_reconcile.py` 不存在；tick 无对账步 | **❌ → W3-9（库）+ W3-TK（接线）** |
| gate 反注入（C-step1） | W1 决策文档 | run_gates 单一归约器 + untrusted exit4 + realpath 包含性 + min_gates | 三 commit 仓内不存在，run_gates 为旧版，PR225 不含 | **❌ → W3-10 全新重实现（非搬移）** |

### 明确的问题
1. **canary 无跨日累计**：canary.yml 覆盖写 `results.json`，"连续 N 晚"无历史载体，违反 §5.4 字面要求。
2. **W2 对账工具缺失**：W2 关闭判定引用 `state_reconcile.py --check`，但该文件与事件日志均未落地。
3. **C-step1 从未合并**：决策文档所称 c7eca50/315e45a/0dcfc9c 仓库中不存在，run_gates.py 为旧版。
4. **canary 链路清理假报警**（W1-9 实测遗留）：清理失败被当作链路断裂，每小时噪声。

---

## 波前清单（人类执行）

- [x] dispatcher 四数值已批准（`max_concurrent_sandboxes=4`、每仓并发 `2`、令牌桶 `<20% 降级`、日预算 `$30`），由波前人工项手写进 policy.yml（W3-1 只读、不落盘）。
- [x] escalation.yml 初版按**低强度启动**批准（默认 `on_sla_breach: notify`，freeze 仅 `severity=critical` 或连续多次违约发通知，实际全局冻结由 kill switch `freeze.all` 统一承担——双机制合一）。
- [ ] **人类手写 policy.yml 初值**：四数值（max_concurrent_sandboxes=4/每仓并发2/令牌桶<20%/日预算$30）+ `rings:` 段 + `freeze:` 段（freeze.all:false）。policy.yml 唯一写者=W3-TK（freeze.all 翻转）；W3-1 只读。（W3-1 AC-0 断言值存在；W3-6 AC-2 断言 ring0）
- [ ] 清扫 W1-9 遗留：关闭 product-x 已泄漏的 canary 合成票（epoch 早于本波启动，`state:done`/`not_planned`）——W3-8 AC-8。
- [ ] 产 `waves/WAVE-03/demo_cards.json`：6 张演示卡（含 1 跨仓、1 loop 机制、1 注定失败标记 `fail:true`），每卡 id/repo/tier/acceptance 摘要。
- [ ] kill switch 演练预约在波中第三天。

---

## 卡包发放表（W3）

### W3-1 · dispatcher 派卡引擎 + policy.yml 数值落盘

```json loop
{
  "schema": 1,
  "id": "W3-1",
  "wave": "WAVE-03",
  "objective": "conductor/dispatcher.py 派卡引擎 + 从 policy.yml 读四数值/rings/freeze（四数值+rings+freeze:false 由波前人工项落盘，本卡只读不写；dispatcher 一律从 policy.yml 读值不硬编码，读四数值=4/每仓并发2/令牌桶<20%/日预算$30）→ 写 loop-state/assignments/<sandbox>.json → 沙盒只拉自己的卡（推-拉混合），assignment 篡改拒绝 ASSIGNMENT_MISMATCH；freeze.all=true 时拒派新卡（全局冻结消费方之一）；policy.yml 唯一写者=W3-TK（freeze.all）",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "conductor/dispatcher.py"
  ],
  "forbid_paths": [
    "conductor/backpressure.py",
    "conductor/escalation.py",
    "conductor/human_queue.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/reconcile.py",
    "loopd/**",
    "escalation.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G1", "N30"],
  "acceptance": [
    "AC-0: policy.yml 含四数值 + rings + freeze 三段（grep -cE 'max_concurrent_sandboxes|concurrency_per_repo|quota_token_threshold|daily_budget' policy.yml ≥4；grep -q 'rings:' policy.yml；grep -q 'freeze:' policy.yml，EXIT 均 0）",
    "AC-1: python3 -c \"from conductor.dispatcher import dispatch; print('ok')\" EXIT=0",
    "AC-2: grep -q 'assignments/' conductor/dispatcher.py（写 loop-state/assignments/<sandbox>.json）",
    "AC-3: 沙盒只拉自己的卡：assignment 带 sandbox 标识，拉取侧校验一致（grep ASSIGNMENT_MISMATCH）",
    "AC-4: dispatcher 从 policy.yml 读四数值而非硬编码。具体命令：python3 - <<'PY'\nimport ast,sys\nsrc=open('conductor/dispatcher.py').read(); t=ast.parse(src)\nvals={}; import re\nfor a in ast.walk(t):\n    if isinstance(a,ast.Assign):\n        for x in a.targets:\n            if getattr(x,'id','') in ('MAX_CONCURRENT','CONCURRENCY_PER_REPO','QUOTA_THRESHOLD','DAILY_BUDGET'):\n                raise SystemExit('hardcode %s'%x.id)\nprint('ok')\nPY（无 DISpatcher 自编硬编码常量；值一律来自 policy.yml 读取）EXIT=0",
    "AC-4b（A7 收敛·单一预算判断）: dispatch 的并发/预算裁决统一调用 conductor/backpressure 库（grep 'from conductor.backpressure import' conductor/dispatcher.py，EXIT=0；不做第二套独立预算逻辑）",
    "AC-4c（freeze 消费方·机器可读）: dispatcher 读 policy.yml freeze.all；freeze.all=true 时 dispatch 拒派新卡并日志含 FROZEN（bash <<'SH'：fetch 下 freeze.all 置 true 的样本，断言 dispatch 返回 rejected 且无新 assignment 写入，EXIT=0）",
    "AC-5（负证·内联可执行）: 篡改 sandbox-A assignment 指向 sandbox-B → bash <<'SH' 内联脚本拉取校验得 ASSIGNMENT_MISMATCH 且 EXIT≠0"
  ],
  "blocked_by": ["W3-3"],
  "budget": 1.2,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-2 · scoped token 铸造

```json loop
{
  "schema": 1,
  "id": "W3-2",
  "wave": "WAVE-03",
  "objective": "scoped token 铸造：每次会话由 App 铸单仓/所需权限/1h installation token（create-github-app-token v3，owner/repositories 收窄 + 1h 过期）；沙盒启动脚本接入；绝不下发常驻 token/PAT",
  "tier": "critical",
  "role": "impl",
  "paths": [
    ".github/workflows/scoped-token.yml",
    "scripts/scoped-token.sh"
  ],
  "forbid_paths": [
    "conductor/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "escalation.yml",
    "tests/**"
  ],
  "charter": ["N15", "G3"],
  "acceptance": [
    "AC-1: .github/workflows/scoped-token.yml 存在且用 create-github-app-token v3（grep -q 'create-github-app-token'）",
    "AC-2: scripts/scoped-token.sh 含 owner/repositories 收窄（grep -q 'repositories'）",
    "AC-3: token 短签发 1h（grep -E 'expire|permissions|installation' scripts/scoped-token.sh 或 workflow 过期参数，杜绝常驻）",
    "AC-4（负证·行为）: 在 scripts/scoped-token.sh 中 grep 无任何持久化路径/常驻形态（grep -cE 'github_pat_|ghp_|gho_' → EXIT 非 0；grep 无 '>.*token.*\\.(txt|log)' 写持久化）",
    "AC-5: 沙盒启动脚本接入该 token（grep 引用 scoped-token.sh 或 token 环境注入）",
    "AC-6（负证·行为·机器可读）: 用 create-github-app-token 生成的安装 token 校验其 `expires_at` 距当前 ≤1h（bash/python 断言 expires_at - now <= 3600s，EXIT=0 才 PASS）；任何持有 >1h 或权限超 `repositories`+`contents:read` 的 token 形态 → 判 FAIL（EXIT≠0）"
  ],
  "blocked_by": ["W3-1"],
  "budget": 0.8,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-3 · 背压

```json loop
{
  "schema": 1,
  "id": "W3-3",
  "wave": "WAVE-03",
  "objective": "背压：并发上限/每仓上限/令牌桶（读 X-RateLimit-Remaining）/日预算；撞限显式降级 + Incident（不静默）",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "conductor/backpressure.py"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/escalation.py",
    "conductor/human_queue.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/reconcile.py",
    "loopd/**",
    "escalation.yml",
    "policy.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G1"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.backpressure import check_budget; print('ok')\" EXIT=0",
    "AC-2: grep -q 'X-RateLimit-Remaining' conductor/backpressure.py",
    "AC-3: grep -q 'daily_budget' conductor/backpressure.py（读 policy.yml 日预算，非硬编码）",
    "AC-4（撞限显式降级）: 背压降级路径写 Incident/issue，绝不静默 continue（grep -E 'incident|issue|alert' 在降级分支）",
    "AC-5（负证 N34·内联）: 日预算=0（LOOP_SIMULATE_BUDGET=0）→ 背压返回拒绝 + Incident + 未铸 token（bash <<'SH' 断言 check_budget 返回拒绝、Incident 打开、无 token 铸造记录，EXIT≠0）",
    "AC-6（行为负证·内联）: 并当前置 1 + 投 3 张无冲突卡 → 恰好 1 张进 claimed 且 rejected≥2（python/bash <<'SH' 确定性单元断言，不依赖真实时延；EXIT=0 对、否则 FAIL）"
  ],
  "blocked_by": [],
  "budget": 0.8,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-4 · escalation 库 + escalation.yml（低强度启动）

```json loop
{
  "schema": 1,
  "id": "W3-4",
  "wave": "WAVE-03",
  "objective": "conductor/escalation.py（纯库 evaluate()）+ escalation.yml：12 条 ESC-01..12（每条带 severity）+ SLA 24h + 三级动作 notify→warn→freeze；默认 on_sla_breach: notify（只提醒不冻结）；freeze 通知触发 `policy.yml freeze.all` 人工置位，由 kill switch 机制统一执行全局冻结；默认不冻，仅 critical/连续违约发通知。【tick 注册由 W3-TK 负责，本卡不改 tick.py】",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "escalation.yml",
    "conductor/escalation.py"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/backpressure.py",
    "conductor/human_queue.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/reconcile.py",
    "loopd/**",
    "policy.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G1", "N11", "N18"],
  "acceptance": [
    "AC-1: escalation.yml 含 ≥12 条 ESC-（grep -c 'ESC-' ≥12），且每条结构含 severity + 非空条件（用 python -c 加载 YAML，断言每 rule 有 .severity 且 .condition 非空）",
    "AC-2: escalation.yml 定义 notify/warn/freeze 档位且默认 on_sla_breach: notify（grep -q 'on_sla_breach: notify'）",
    "AC-3: escalation.yml 含 consecutive_breach_threshold: <N>（grep -q 'consecutive_breach_threshold'；N 具体化如 3）",
    "AC-4: python3 -c \"from conductor.escalation import evaluate; print('ok')\" EXIT=0；freeze 级别仅输出评估结果 `freeze` 由调用方触发 `freeze.all`（grep：evaluate 返回 outcome=\"freeze\" 不直接写环境变量，由 tick 决策链路由到 kill switch）",
    "AC-5（正证·低强度）: severity=medium 违约 → evaluate 返回 NOTIFY（python -c 调用 evaluate 断言 outcome==\"notify\"）",
    "AC-6（负证 N3）: 构造 severity=critical 违约（LOOP_SIMULATE_SLA_BREACH=1 夹具）→ evaluate 返回 \"freeze\"（python -c 断言 outcome==\"freeze\"，EXIT=0；评估机制正确）；notify 级别不输出 freeze"
  ],
  "blocked_by": [],
  "budget": 1.0,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-5 · HUMAN-QUEUE 纯库（digest 组装）

```json loop
{
  "schema": 1,
  "id": "W3-5",
  "wave": "WAVE-03",
  "objective": "conductor/human_queue.py（纯库）：人类决策自动入列 + SLA 计时 + digest 组装（引用 escalation 输出，输出含 SLA 列）；【tick 调度与 digest 步注册由 W3-TK 负责，本卡不改 tick.py】",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "conductor/human_queue.py"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/backpressure.py",
    "conductor/escalation.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/reconcile.py",
    "loopd/**",
    "escalation.yml",
    "policy.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G1"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.human_queue import add_decision, build_digest; print('ok')\" EXIT=0",
    "AC-2: grep 'SLA' conductor/human_queue.py（决策自动入列 + SLA 计时）",
    "AC-3: build_digest 输出含 SLA 列且引用 escalation 输出（grep -E 'escalation|SLA' conductor/human_queue.py）",
    "AC-4: 每类人类决策有唯一规则键（grep 规则定义，python -c 断言 keys 唯一）",
    "AC-5（正证·行为）: build_digest 输入含 2 类不同 SLA 决策 → 输出含 SLA 降序或到期时间列（python -c 构造输入断言列存在，EXIT=0）",
    "AC-6（负证 N30·机器可读）: 以非白名单身份（LOOP_IDENTITY=attacker）调用 add_decision → 抛 RAISE 或 quarantine 置位（bash/python -c 断言 EXIT≠0）"
  ],
  "blocked_by": ["W3-4"],
  "budget": 0.8,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-6 · kill switch（runbook；统一冻结唯一机制）

```json loop
{
  "schema": 1,
  "id": "W3-6",
  "wave": "WAVE-03",
  "objective": "kill switch 全局冻结（唯一机器冻结机制）：policy.yml freeze.all 全链消费（W0-2 已铺，本卡验证 no-op 语义与恢复 + 落盘真实消费方）；runbook（冻结/回滚 pin/全部打回 ready/导出状态/解冻恢复）写进 docs/runbook-freeze.md。【评审 M1/F3 采纳：本波冻结统一由 freeze.all 承担，不再有 MERGE_FROZEN 独立机制；ring 由 W3-1 落盘，本卡只读】",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "docs/runbook-freeze.md",
    ".github/workflows/freeze-yaml-check.yml"
  ],
  "forbid_paths": [
    "conductor/**",
    "loopd/**",
    "policy.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "escalation.yml"
  ],
  "charter": ["G1", "N18"],
  "acceptance": [
    "AC-1: docs/runbook-freeze.md 存在且含 冻结/回滚 pin/全部打回 ready/导出状态/解冻恢复 五节（grep 各节标题）",
    "AC-2: policy.yml 含 rings 与 freeze 段（grep -q 'ring0' policy.yml；grep -q 'freeze' policy.yml；W3-1 AC-0/波前人工项已落盘）。代码层无 MERGE_FROZEN 残留（grep -rn 'MERGE_FROZEN' --include=*.py --include=*.sh --include=*.yml --include=*.yaml --include=*.json conductor/ gates/ .github/ scripts/ → 退出 1（无命中）才 PASS；限代码文件，不扫 waves/** 文档）",
    "AC-3（正证·消费方·机器可读）: 交付 .github/workflows/freeze-yaml-check.yml：freeze.all=true 时任何评估门禁对 README/docs 的写操作 step 被 skip 并打 FROZEN 标记（grep workflow 含 `if: ... freeze.all != 'true'` 守卫，EXIT=0）",
    "AC-4（行为正证·freeze 生效）: freeze.all=true 后跑全链 → 无写操作、日志含 FROZEN、loop-state commit 数不变（bash 断言 delta==0，EXIT=0）",
    "AC-5（行为负证·恢复）: freeze 后按 runbook 解冻 → 下游卡恢复可直接消费（bash 断言 freeze.all=false 后写操作恢复、无 FROZEN 残留，EXIT=0）",
    "AC-6: 明确冻结机制唯一性（grep runbook 含 kill-switch 章节，无 MERGE_FROZEN 分节，不混用另一机制）"
  ],
  "blocked_by": [],
  "budget": 0.8,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-7 · 72h 零干预演示执行（本波出口核心；role=impl）

```json loop
{
  "schema": 1,
  "id": "W3-7",
  "wave": "WAVE-03",
  "objective": "72h 演示执行（BOT 主跑，人类只观察）：第 4 天 06:00 UTC 由 scheduled_demo_drop 步（W3-TK）以 bot 身份一次性投放 6 张演示卡（见 demo_cards.json），仅观察不动 72h；产出 waves/WAVE-03/evidence/72h-events.jsonl 完整事件流；kill switch 演练在波中执行并恢复。演示卡由人类建卡，PR 由沙盒/bot 身份开与合（零干预=无人类 merge）【role=impl：本卡是执行/产证据，非盲一半验证；证据真伪由 V3-7 独立复核】",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "waves/WAVE-03/evidence/**",
    "waves/WAVE-03/demo_cards.json"
  ],
  "forbid_paths": [
    "conductor/**",
    ".github/**",
    "loopd/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "escalation.yml",
    "tests/**"
  ],
  "charter": ["G0", "G1"],
  "acceptance": [
    "AC-0: demo_cards.json 存在且含 6 张卡（grep -c '\"repo\"' demo_cards.json ==6；含 1 张 fail:true）",
    "AC-1: waves/WAVE-03/evidence/72h-events.jsonl 非空（test -s）",
    "AC-2（零干预·正向追溯）: 每张 merged 演示卡属于 demo_cards.json 白名单，且 merged_by 为 bot 白名单（gh pr view --json mergedBy：login ∈ {CONDUCTOR_APP, github-actions[bot], loop-canary-bot}），且投放事件由 bot actor 写入事件流（scheduled_demo_drop）。人类只建卡，不 merge",
    "AC-3: ≥1 张经历 reaper 回收后重试成功（事件流含 reclaim→ready 重试序列）",
    "AC-4: ≥1 张跨仓卡、≥1 张 loop 机制卡完成（事件流含对应 repo 维度）",
    "AC-5: tick STEPS 中 W3-TK 新注册的 reconcile/escalate/digest/scheduled_demo_drop 四步各自有 last_success_at（python 读 tick Step 注册表断言四键存在且 last_success_at 非空；不设任意步数常量基线）",
    "AC-6: 72h 内 gh api rate_limit core remaining 从未低于 20%（记录 min）",
    "AC-7（时间跨度·防 12h 速成）: events.jsonl 首末条 timestamp 差 ≥72h（python 断言 >= 72*3600）",
    "AC-8（kill switch 演练）: 72h 内 freeze.all=true 演练 ≥1 次且可恢复（事件流含 freeze→unfreeze 序列，解冻后 freeze.all=false 且无 FROZEN 残留）"
  ],
  "blocked_by": [
    "W3-1",
    "W3-2",
    "W3-3",
    "W3-4",
    "W3-5",
    "W3-6",
    "W3-9",
    "W3-10",
    "W3-TK"
  ],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-8 · ★回看补债：canary 连续 N 晚累计 + 链路清理假报警

```json loop
{
  "schema": 1,
  "id": "W3-8",
  "wave": "WAVE-03",
  "objective": "回看补债（W1-9）：① canary 结果改为 append-only 历史（canary/history.jsonl，追加非覆盖），提供按自然日累计判定脚本；② 修 canary 链路清理假报警（canary-chain.sh 关 issue 失败被误判为链路断裂→每小时 noise incident + product-x 泄漏合成票），清理判据与链路判据解耦 + 不吞 stderr + 清扫已泄漏合成票",
  "tier": "standard",
  "role": "impl",
  "paths": [
    ".github/workflows/canary.yml",
    "canary/history.jsonl",
    "scripts/canary-nightly.sh",
    ".loop/scripts/canary-chain.sh",
    ".loop/scripts/canary-survival.sh"
  ],
  "forbid_paths": [
    "conductor/**",
    "loopd/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "escalation.yml"
  ],
  "charter": ["G3", "N29", "N11"],
  "acceptance": [
    "AC-1: canary.yml 按日追加写 canary/history.jsonl（grep 追加写法 open(...,'a')；非覆盖）",
    "AC-2: history.jsonl 每条含 date/count/all_intercepted（python -c 断言字段），字段结构可机器校验【跨 ≥3 自然日的累计判定放波级 Z，不在此 AC（单卡 done 时点不可达）】",
    "AC-3: scripts/canary-nightly.sh 存在且支持 `--since N`（bash 调用 --since 3 满足则 EXIT=0，>1 程序块回报 EXPLICIT 语义）",
    "AC-4（负证 N29）: 注入一晚未拦截记录 → bash scripts/canary-nightly.sh --since 3 判 FAIL EXIT≠0，无假绿",
    "AC-5: 覆盖式 results.json 改追加（grep 覆盖已移除）",
    "AC-6（假报警修复）: canary-chain.sh 清理失败（close issue/push delete 任一 fail）不在链路判据 exit1——链路存活由链路步骤判定，清理失败独立 CLEANUP_WARN（grep：清理分支与链路判据解耦）",
    "AC-7（不吞错）: canary-chain.sh/canary-survival.sh 失败分支去除 `>/dev/null 2>&1` 吞错，原因留痕（grep stderr 不再静默）",
    "AC-8（清扫遗留·机器可读）: bash <<'SH'\n  START=$(git log --format=%ct --diff-filter=A -- waves/WAVE-03.md | tail -1)\n  LEFT=$(gh api 'search/issues?q=repo:cloudbird-software/product-x+label:card+is:open+created:<'$START' --jq .total_count)\n  [ \"$LEFT\" -eq 0 ] && echo clean && exit 0\nexit 1\nSH\n（LEFT: OPEN canary 合成票早于本波启动（取 WAVE-03.md 首次引入 commit 时间戳，自动读，无需人工替换））"
  ],
  "blocked_by": [],
  "budget": 0.8,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-9 · ★回看补债：事件日志 + 对账纯库

```json loop
{
  "schema": 1,
  "id": "W3-9",
  "wave": "WAVE-03",
  "objective": "回看补债（W2 关闭判定）：落地 conductor/events.py（append-only 事件日志，每行 JSONL，落 loop-state/events/*.jsonl）+ conductor/state_reconcile.py（对账纯库，事件日志 vs 投影状态 diff 判定 + 覆盖率断言）；【tick 注册对账步与 cas 事件发射接入由 W3-TK 负责，本卡不改 tick.py】",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "conductor/events.py",
    "conductor/state_reconcile.py"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/backpressure.py",
    "conductor/escalation.py",
    "conductor/human_queue.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/reconcile.py",
    "loopd/**",
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "escalation.yml"
  ],
  "charter": ["G3", "N30", "N31"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.events import append_event; print('ok')\" EXIT=0（append 非覆盖）",
    "AC-2: python3 -c \"from conductor.state_reconcile import reconcile; print('ok')\" EXIT=0",
    "AC-3（反真空·覆盖率）: reconcile 判定含'日志非空且覆盖每类状态迁移'（python -c 造 2 类迁移事件，断言覆盖率==2，空日志 → 判定 FAIL/EXIT≠0）",
    "AC-4: 事件日志路径指向 loop-state 下（grep events/ + loop-state 分支常量），不落 .gitignore 覆盖路径（N31）",
    "AC-5（负证 N29/N30）: 注入一条事件与投影不符（伪造/断链）→ reconcile 检出 diff≠0 + Incident（EXIT≠0），不 fail-open"
  ],
  "blocked_by": [],
  "budget": 1.0,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-10 · ★C-step1 反注入（重实现）

```json loop
{
  "schema": 1,
  "id": "W3-10",
  "wave": "WAVE-03",
  "objective": "重实现 C-step1：gates/run_gates.py 退出码收敛 + 反注入。① 单一归约器 reduce_exit（穷举无 default；归约优先级为『先命中者胜』的检查顺序，与存量代码一致：untrusted(4)→error(3)→unresolved(2)→fail(1)→pass(0)，括号内为退出码数值，非优先级刻度；用户字面语义 untrusted>error>unresolved>fail>pass，数值单调递减故两者一致）；② trust_check 用 realpath 包含性（拒 .. 逃逸/逃出根符号链接/setuid·setgid·sticky），解析到受控根外 → untrusted + exit4；③ min_gates 反空过；④ 每 gate 带 reason。注：原 c7eca50/315e45a/0dcfc9c 仓内不存在，全新重写非搬移（N13）。",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "gates/run_gates.py",
    "gates/test_run_gates.py"
  ],
  "forbid_paths": [
    "gates/gate_ratchet.py",
    "gates/gate_pin_integrity.py",
    "gates/gate_secrets.py",
    "gates/gate_semgrep.py",
    "gates/gate_doc_drift.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "bench/**",
    "pins/**",
    "canary/**",
    ".github/**"
  ],
  "charter": ["G1", "G3", "N11", "N17"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.run_gates import reduce_exit, trust_check; print('ok')\" EXIT=0",
    "AC-2: 退出码契约 0/1/2/3/4（grep 归约优先级表），含旧优先级迁移说明（python -c 对混样断言优先级：构造含 untrusted+error+fail 的 sample 调 reduce_exit→断言返回 4；含 error+unresolved+fail→返回 3；仅 unresolved+fail→返回 2；仅 fail→返回 1；全 pass→返回 0；EXIT=0 才算过）。注意退出码数值与归约优先级分离：归约是检查顺序（untrusted→error→unresolved→fail→pass），数值 exit code 是输出结果",
    "AC-3: main 之下的逻辑无 sys.exit 直调（grep：sys.exit 仅出现在 main 守卫）",
    "AC-4（反注入·行为）: 符号链接逃逸受控根 → python -c 调 trust_check 断言返回 untrusted/exit4（EXIT≠0），伪造 /gates_evil 不被 /gates 前缀误判（realpath 包含性，非 startswith）",
    "AC-5（min_gates 反空过）: 实际执行 pass/fail 数 < min_gates → exit2（python -c 断言 EXIT=2）",
    "AC-6（reason）: 未执行 gate 带 reason not_found/root_unavailable（grep reason 字段）",
    "AC-7（回归·含 canary 探针对齐）: test_run_gates 全量 PASS 且 canary 故障样本 C01/C08/C11 的期望退出码契约未回归（由 V3-10 复核；因 .github/** ∈ forbid，探针回归由 V3-10 或 CI 承载，AC 注明）"
  ],
  "blocked_by": [],
  "budget": 1.2,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-TK · ★接线卡：cas 事件发射 + tick STEPS 注册（tick.py 单 owner）

```json loop
{
  "schema": 1,
  "id": "W3-TK",
  "wave": "WAVE-03",
  "objective": "接线闭环：① conductor/cas.py 的 cas_update 成功路径调用 events.append_event（事件发射 owner，避免空日志真空绿）；② conductor/tick.py 注册 STEPS：对账步（调 state_reconcile.reconcile，失败开 Incident）+ escalate 步（调 escalation.evaluate 读 escalation.yml，critical→freeze 时置 policy.yml freeze.all=true）+ digest 步（调 human_queue.build_digest）+ 演示投放步 scheduled_demo_drop（bot 触发，事件流含投放事件）；③ freeze.all=true 时 tick 各步 skip 打 FROZEN。使'事件-投影对账连续 72h diff=0'与 escalation 周期评估真实发生。tick.py/cas.py 仅本卡可改（评审 H1/B1/B9/A7/A8/N2/N3/M1 采纳）",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "conductor/tick.py",
    "conductor/cas.py",
    "policy.yml"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/backpressure.py",
    "conductor/escalation.py",
    "conductor/human_queue.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/reconcile.py",
    "loopd/**",
    ".github/**",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**"
  ],
  "charter": ["G3", "N30", "N31"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.tick import STEPS; print('ok')\" EXIT=0",
    "AC-2: grep -q 'append_event' conductor/cas.py（cas_update 成功路径发射，非注释死串——V3-TK 用 mock.patch/死串负证复核）",
    "AC-3: STEPS 注册含 reconcile/escalate/digest/scheduled_demo_drop 步（grep -E 'reconcile|escalate|build_digest|scheduled_demo_drop' conductor/tick.py 在 STEPS 定义处）",
    "AC-4: escalate 步读 escalation.yml 的 SLA/severity，且 critical→freeze 时置 freeze.all=true（grep -E 'escalation.yml|escalation.evaluate|freeze.all' conductor/tick.py）",
    "AC-4b（freeze 消费方·机器可读）: freeze.all=true 时 tick 各 STEPS 执行前 skip 并打 FROZEN 标记（bash <<'SH' 注入 freeze.all=true，断言步骤日志 FROZEN 且无写副作用，EXIT=0）",
    "AC-5（行为·单步指纹·内联）: 注入 tick 某步异常 → 该步 TICK_STEP_ERRORED + Incident，其余步仍执行，整体 exit 1（bash <<'SH' 内联注入断言，EXIT≠0；N4 判据落地）",
    "AC-6（行为·活锁判定·内联）: reconcile diff≠0 → 对账步 FAIL + 开 Incident（bash <<'SH' 注入 diff → EXIT≠0），不 fail-open"
  ],
  "blocked_by": [
    "W3-4",
    "W3-5",
    "W3-9"
  ],
  "budget": 1.0,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

---

## 异构验证卡（V3-x，全套补齐，N8.5/N12）

> verify_target 指向对应 impl 卡；paths 仅 `.loop/verdicts/v3-*.json`；verifier vendor ≠ impl vendor；盲一半协议同 W2 V2-x。

### V3-1 · 异构验证 W3-1

```json loop
{
  "schema": 1,
  "id": "V3-1",
  "wave": "WAVE-03",
  "objective": "对 W3-1 dispatcher 盲一半异构验证：独立复现 assignment 篡改拒绝（ASSIGNMENT_MISMATCH）与'从 policy.yml 读四数值不硬编码'，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-1",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-1.json"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "policy.yml"
  ],
  "charter": ["N30", "G1"],
  "acceptance": [
    "AC-1: bash 篡改 sandbox-A assignment → AV3-1 独立脚本达 ASSIGNMENT_MISMATCH（EXIT≠0）",
    "AC-2: 断言 dispatcher 读 policy.yml 四 key 且非硬编码（grep 读值引用，若无则 FAIL）",
    "AC-3: 盲一半：只读 schema 与命令输出，不读 W3-1 源码注释/过程；据命令判 PASS/FAIL",
    "AC-4: VERDICT 写 .loop/verdicts/v3-1.json，verifier_model.vendor ≠ impl_model.vendor"
  ],
  "blocked_by": ["W3-1"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-2 · 异构验证 W3-2

```json loop
{
  "schema": 1,
  "id": "V3-2",
  "wave": "WAVE-03",
  "objective": "对 W3-2 scoped token 盲一半异构验证：复核 token 作用域收窄与 1h 失效、无持久化 token 形态，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-2",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-2.json"
  ],
  "forbid_paths": [
    ".github/workflows/scoped-token.yml",
    "scripts/scoped-token.sh"
  ],
  "charter": ["N15", "G1"],
  "acceptance": [
    "AC-1: 复现脚本确认无常驻 token 形态（grep 无 ghp_/gho_/持久化，EXIT 非 0）",
    "AC-2: 确认 owner/repositories 收窄（grep 'repositories'）与 1h 过期（grep expire/permissions）",
    "AC-3: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v3-2.json，vendor 异构"
  ],
  "blocked_by": ["W3-2"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-4 · 异构验证 W3-4

```json loop
{
  "schema": 1,
  "id": "V3-4",
  "wave": "WAVE-03",
  "objective": "对 W3-4 escalation 盲一半异构验证：severity=critical 触发 freeze、medium 只 notify、阈值具名，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-4",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-4.json"
  ],
  "forbid_paths": [
    "escalation.yml",
    "conductor/escalation.py"
  ],
  "charter": ["G1", "N11"],
  "acceptance": [
    "AC-1: 复现 critical 违约 → evaluate 断言 outcome==\"freeze\"（EXIT=0 判定机制正确）；medium → 仅 notify 不输出 freeze，对象 VERDICT",
    "AC-2: 断言 consecutive_breach_threshold 具名（grep）",
    "AC-3: 断言无 MERGE_FROZEN 直接写路径（统一由 kill switch freeze.all 机制），符合双机制合一决策（grep -q 'MERGE_FROZEN' conductor/escalation.py → 退出非 0 才 PASS）",
    "AC-4: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v3-4.json，vendor 异构"
  ],
  "blocked_by": ["W3-4"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-7 · 异构验证 W3-7（72h 证据真伪）

```json loop
{
  "schema": 1,
  "id": "V3-7",
  "wave": "WAVE-03",
  "objective": "对 W3-7 72h 演示证据盲一半异构验证：事件流的真实性（非伪造/速成）、时间跨度≥72h、零干预正向追溯、kill switch 演练，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-7",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-7.json"
  ],
  "forbid_paths": [
    "waves/WAVE-03/evidence/**",
    "waves/WAVE-03/demo_cards.json"
  ],
  "charter": ["G0", "G1", "N12"],
  "acceptance": [
    "AC-1: python 断言 events.jsonl 首末 timestamp 差 ≥72h 且行数>0（EXIT=0 才 PASS）",
    "AC-2: 随机抽 ≥1 条 merged 事件，gh 复核其 PR author 为 bot+入 merge queue（gh api 复核），非伪造",
    "AC-3: 零干预逆向复核：对 events.jsonl merge 事件逐一 gh pr 复核，无人类 actor 篡改迹象；DEP 不读写证据文件",
    "AC-4: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v3-7.json，vendor 异构"
  ],
  "blocked_by": ["W3-7"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-9 · 异构验证 W3-9

```json loop
{
  "schema": 1,
  "id": "V3-9",
  "wave": "WAVE-03",
  "objective": "对 W3-9 事件/对账库盲一半异构验证：伪造事件-投影不符→diff≠0+Incident；空日志→覆盖率 FAIL；产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-9",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-9.json"
  ],
  "forbid_paths": [
    "conductor/events.py",
    "conductor/state_reconcile.py"
  ],
  "charter": ["G3", "N30", "N31"],
  "acceptance": [
    "AC-1: 复现伪造事件-diff≠0+Incident（EXIT≠0），不 fail-open",
    "AC-2: 空日志 → 覆盖率判定 FAIL（EXIT≠0），非真空绿",
    "AC-3: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v3-9.json，vendor 异构"
  ],
  "blocked_by": ["W3-9"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-10 · 异构验证 W3-10

```json loop
{
  "schema": 1,
  "id": "V3-10",
  "wave": "WAVE-03",
  "objective": "对 W3-10 反注入盲一半异构验证：符号链接逃逸→exit4；min_gates→exit2；跑 canary C01/C08/C11 探针对齐（.github/** ∈ W3-10 forbid，探针回归由本卡/CI 承载），产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-10",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-10.json"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/test_run_gates.py"
  ],
  "charter": ["G1", "N11", "N17"],
  "acceptance": [
    "AC-1: 符号链接逃逸受控根 → 关联 exit4（python -c 因 survive 断言，EXIT≠0）",
    "AC-2: min_gates 不足 → exit2（python -c 断言 EXIT=2）",
    "AC-3: 删实现仅留同名注释的负证：grep 判据被死串满足 → 判 FAIL（反 grep 行为空洞，M2 采纳）",
    "AC-4: 跑 canary 故障样本 C01/C08/C11 断言期望退出码契约未回归（EXIT=0），VERDICT 写 .loop/verdicts/v3-10.json，vendor 异构"
  ],
  "blocked_by": ["W3-10"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V3-TK · 异构验证 W3-TK

```json loop
{
  "schema": 1,
  "id": "V3-TK",
  "wave": "WAVE-03",
  "objective": "对 W3-TK 接线盲一半异构验证：cas_update 成功路径触发事件（非死串）、tick 注册 3 步、单步故障隔离，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W3-TK",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v3-tk.json"
  ],
  "forbid_paths": [
    "conductor/tick.py",
    "conductor/cas.py"
  ],
  "charter": ["G3", "N30"],
  "acceptance": [
    "AC-1: 触发 cas_update 成功 → 事件日志 append 且可 read 回（python 断言非死串，删除仅留注释即失败）",
    "AC-2: tick STEPS 注册含 reconcile/escalate/digest（python 断言 STEPS 键）",
    "AC-3: 注入第 3 步异常 → TICK_STEP_ERRORED + 其余步继续（bash，EXIT≠0）",
    "AC-4: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v3-tk.json，vendor 异构"
  ],
  "blocked_by": ["W3-TK"],
  "budget": 0.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

---

## 本波次的检查方法（Wave-level Gate）

> **关闭判定**：正证全过 + 负证全拦 + W3-7 72h 判据全绿（V3-7 PASS）+ 事件-投影对账连续 72h diff=0 → **WAVE-03: DONE**；任一 FAIL → NOT DONE。
> **入口先决**：W2 全绿；escalation.yml 与 dispatcher 四数值已人类审批；demo_cards.json 已备（6 卡）。**入口不自举**：P 组不检查本波才建的库（对账工具），否则成环（评审 H4 采纳）。

### P. 入口

```bash
bash .loop/smoke.sh                                  # → 16/16 PASS
python3 conductor/state_of_system.py --verify EXIT=0
git branch -a | grep -E 'loop-state'                 # → loop-state 分支存在
grep -q 'rings:' policy.yml && echo ok               # W3-1 已落盘四数值+ring
test -s waves/WAVE-03/demo_cards.json && [ "$(grep -c '\"repo\"' waves/WAVE-03/demo_cards.json)" -eq 6 ] && echo ok
```

### Q. 正证（每张卡 ≥1 条行为级可运行检查，非仅 import/grep）

```bash
# W3-1 dispatcher
python3 -c "from conductor.dispatcher import dispatch; print('ok')"
grep -q 'ASSIGNMENT_MISMATCH' conductor/dispatcher.py && echo ok
grep -c 'max_concurrent_sandboxes' policy.yml | awk '$1>=1'
# W3-2 scoped token
grep -q 'create-github-app-token' .github/workflows/scoped-token.yml && echo ok
grep -cE 'ghp_|gho_|github_pat_' scripts/scoped-token.sh; test $? -ne 0 && echo ok   # 无常驻=EXIT≠0
# W3-3 背压：并当前置1只放行1（行为）
python3 -c "from conductor.backpressure import check_budget; print('ok')"
grep -q 'X-RateLimit-Remaining' conductor/backpressure.py && echo ok
# W3-4 escalation：medium 只 notify
python3 -c "from conductor.escalation import evaluate; print('ok')"
grep -q 'on_sla_breach: notify' escalation.yml && grep -q 'consecutive_breach_threshold' escalation.yml && echo ok
# W3-5 human_queue 纯库
python3 -c "from conductor.human_queue import add_decision, build_digest; print('ok')"
grep -q 'SLA' conductor/human_queue.py && echo ok
# W3-6 kill switch + ring（读到 ring + runbook 五节）
test -f docs/runbook-freeze.md && grep -q '解冻恢复' docs/runbook-freeze.md && grep -q 'ring0' policy.yml && echo ok
# W3-8 canary 累计（bash，勿用 python3 跑 .sh）
bash scripts/canary-nightly.sh --since 3 && echo ok
test -s canary/history.jsonl && echo ok
grep -q 'CLEANUP_WARN' .loop/scripts/canary-chain.sh && echo ok
# W3-9 事件-投影对账库（含覆盖率）
python3 -c "from conductor.events import append_event; from conductor.state_reconcile import reconcile; print('ok')"
# W3-10 反注入（行为负证：符号链接逃逸→not untrusted 即 FAIL）
python3 -c "from gates.run_gates import reduce_exit, trust_check; print('ok')"
# W3-TK 接线：tick 注册 + cas 发射
python3 -c "from conductor.tick import STEPS; print('ok')"
grep -q 'append_event' conductor/cas.py && echo ok
# V3-x verdicts 就位
ls .loop/verdicts/v3-1.json .loop/verdicts/v3-7.json 2>/dev/null && echo ok
# W3-7 72h 判据（见卡 acceptance + V3-7 PASS）
# 事件-投影对账连续 72h diff=0（tick 对账日志；跨日复跑，见 Z）
```

### R. 负证（每条含可执行命令 + 期望 EXIT，机器可跑）

```bash
# W3-1 N5：篡改 assignment → ASSIGNMENT_MISMATCH（bash 注入，EXIT≠0）
# W3-2    ：提取常驻 token 形态 → EXIT≠0
# W3-3 N34：日预算=0 + 并当前置1 → 拒派+Incident+未铸 token，只放行1（EXIT≠0）
# W3-4 N3 ：severity=critical 违约 → evaluate 返回 freeze（EXIT=0 断言 outcome=="freeze"）；medium → 仅 notify（不 freeze）
# W3-5 N30：LOOP_IDENTITY=attacker 调 add_decision → 拒绝/隔离（EXIT≠0）
# W3-6    ：freeze.all=true → no-op（FROZEN、loop-state commit 数不变、无写，EXIT=0）；解冻 → freeze.all=false 写恢复（EXIT=0）；反向：无 MERGE_FROZEN 残留（grep 非 0）
# W3-8    ：注入一晚未拦截 → 连续判定 FAIL（EXIT≠0）；清理失败 → CLEANUP_WARN 不误判链路断
# W3-9 N29/N30：伪造事件-投影不符 → diff≠0（EXIT≠0）；空日志 → 覆盖率 FAIL（EXIT≠0）
# W3-10 N17：符号链接逃逸 → exit4（EXIT≠0），/gates_evil 不被 /gates 误判
# W3-TK N4 ：注入第3步异常 → TICK_STEP_ERRORED + 其余步继续 + 整体 exit1（EXIT≠0）
# （以上每条以 bash 负证脚本为准，命令粘贴即跑，杜绝纯注释）
```

### Z. 关闭（全过才算 DONE）

```bash
# Q 组全 EXIT=0 且 R 组负数脚本全 EXIT≠0（R 已机器化，非注释）
# W3-7 判据全绿 + V3-7 PASS（72h 证据真伪独立复核）
# 事件-投影对账连续 72h diff=0（tick 对账日志跨日累计 ≥72h）
# canary/history.jsonl 累计跨 ≥3 个自然日且全拦截（bash scripts/canary-nightly.sh --since 3 EXIT=0）
# 72h 末无未关闭 incident（gh issue list --label incident --state open 为空）
# gh api repos/Cloudbird-Software/loop/issues 无残留 incident
# 各卡 VERDICT 写满 .loop/verdicts/v3-*.json 且 verifier vendor ≠ impl vendor
```

判定：Q 全部 EXIT=0 + R 全部 EXIT≠0 + W3-7 判据全绿（V3-7 PASS）+ 对账 72h diff=0 + canary 3 晚累计 → **WAVE-03: DONE**

---

## Not Doing (主动放弃的项)

- **D1**: 不引入 dispatcher 之外的优化器/HQG/RHG/任何新扫描器——dispatcher 只在"人类已投放卡"上分派（§7.0 防腐烂总闸门）。
- **D2**: 不做 silent_release.auto_merge=true——policy.yml 现为 false，留待 W5 评估。
- **D3**: 不启用强模型验收环（W4 信号保真度后再评估）。
- **D4**: dispatcher 四数值经 policy.yml 由人类审批、W3-1 只读落盘，不写死进代码。
- **D5**: escalation 不全自动 freeze——默认 notify；freeze 结果统一交给 kill switch `freeze.all` 执行全局冻结（双机制合一，用户"低强度启动 + 减少复杂度"决策）。
- **D6**: C-step1 只做反注入与退出码收敛，**不做"逐 gate 内容哈希锁定"**（独立承重机制，依赖 pins/allowed.json + manifest 对账）。
- **D7**: 手册 §7.3 负证 N2（已落 W3-3 AC-5）采实现集成而非唯一强制；N4（tick 故障隔离，落 W3-TK AC-5）能力源自 W2-8——两者均保在位，不静默删除。

---

## Retro Prev（对上一波次的教训回应 + 评审闭环）

**W0/W1/W2 时间积累项回看结论**（详见文首表）：
1. canary 单快照、缺跨日累计 → **W3-8**（累计判定放波级，不塞单卡 AC）。
2. W2 对账工具/事件日志未落地 → **W3-9（库）+ W3-TK（接线）**。
3. C-step1 三 commit 仓内不存在 → **W3-10 全新重实现**（非搬移，防假绿）。

**评审意见闭环（PR270 11 条 AI + 4 条 Copilot 全部采纳）**：
- 接入点 owner：tick.py/cas.py 收口到 **W3-TK**，W3-4/5/9 改纯库——解决 H1/B1/A8/A9/B9。
- 全套异构 V3-x（W3-1/2/4/9/10/TK/7）——解决 H3/N8.5/N12。
- W3-7 role=impl + V3-7 验收证据；blocked_by 补 W3-10；AC 加 72h 跨度、kill switch 演练、零干预正向追溯（维持该概念，不引入 audit-log 严格复核）。
- 判据机器化：R 组改可执行命令；'python3 .sh'修 bash；乱字修正；grep 补行为级（W3-2 AC-6 token 1h 失效、W3-5 AC-5/6 digest 行为）；dispatcher 四数值落盘 owner=W3-1（A7 收敛：dispatch 统一调 backpressure 库）。
- **双机制合一**（M1/F3/你的决策）：删除 MERGE_FROZEN 独立机制，全局冻结统一由 kill switch `freeze.all` 承担；W3-6 落盘真实消费方 `freeze-yaml-check.yml` 负证生效。
- W3-7 blocked_by 移除 W3-8（演示不依赖 canary 历史，缩短关键路径）；对账 72h 移入波级 Z（D7 解自举）。
- F5：W3-10 的 test_run_gates 回归由 V3-10/CI 承载，不依赖 impl 自持测试。

**架构教训**：承重文件（tick.py/cas.py/policy.yml）的写权若不单 owner，会出现"判据按字面无法合法完成"的空洞；策略下落盘必须与消费方收敛到同一责任卡或明确人为录入点；同语义机制重复（MERGE_FROZEN vs freeze.all）会制造假绿，可合并的机制一律合并。

---

## 人类摘要（≤200 字）

**本波次押注**：执行真实自治——dispatcher、scoped token（1h）、背压、escalation（低强度：默认提醒，冻结统一由 kill switch `freeze.all` 执行）、kill switch/ring，收尾 **72h 零干预演示**。回看 W0/W1 落地三张补债卡：W3-8（canary 跨日累计+清假报警）、W3-9+W3-TK（事件-投影对账 + 接线闭环）、W3-10（C-step1 反注入重实现）。评审驱动补齐全套异构 V3-x、机器化判据、并消除 MERGE_FROZEN/freeze.all 双机制假绿。

**最大风险**：首张 72h 零干预暴露 dispatcher/scoped-token/escalation 集成断层（跨仓派卡、token 失效时序、freeze 联动），预判 ≥3 处，暴露多少修多少（V3-7 独立验收）。

**需要人类决策**：已批 3 项（dispatcher 四数值、escalation 低强度初版、V 卡全套补齐）；本波新增波前人工项=写四数值初值进 policy.yml、产 demo_cards.json、清扫泄漏 canary 合成票。