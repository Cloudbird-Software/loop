# WAVE-03 · 执行自治（72h 零干预演示）★ 无人化的真正起点

> **目标**：执行半消失——dispatcher 自动把**人类仍批量投放的卡**分给沙盒执行，72 小时零人工干预；背压、scoped token、escalation、kill switch 全部就位。**关键区分（防腐烂总闸门）**：卡仍由人类批量投放（Planner 依旧手动），投放后全程无人干预。
> **入口条件**：W2 全绿（含事件-投影对账落地——本波 W3-9 补齐 W2 关闭判定的最后一环，见"时间积累项回看"）。
> **波结构**：W3-1/W3-2/W3-3（dispatcher 三件套）由 W3-2、W3-3 在 W3-1 之后串行持有 scoped token / backpressure；W3-4/W3-5/escalation 系独立；W3-8/W3-9 是回看补债卡，并行于机制卡；W3-7 72h 演示 block 全部前置。路径两两互斥，由 materializer 强制。

## 时间积累项回看（W0/W1/W2 遗留的"需时间积累"测试项）

> 按用户指令回看先期波次中依赖**时间积累**才能判定的测试项，逐项核对当前是否满足；不满足者开新卡 W3-8 / W3-9 一并处理。

| 回看项 | 出处（手册 §） | 判定标准 | 当前状态 | 结论 |
|---|---|---|---|---|
| 病链连续绿 48h | W0 波后关闭 | 最近 48h conductor/audit 全 success | 见 CI run 记录（gh 可达时可复核） | 由 W1 入口已确认绿，非本波阻塞 |
| canary 连续 3 晚 12/12 | §5.3/§5.4 正证 5（W1-9） | `canary/*.jsonl` 累计 3 个不同自然日全拦截 | **仅单快照** `canary/results.json`（今日覆盖昨日），无跨日历史；canary.yml 每小时覆盖写 | **❌ 未满足**：缺"连续 3 晚"的证据载体 → **开 W3-8** |
| 事件-投影对账连续 72h diff=0 | §6.4-4 / W2 关闭判定 | `conductor/state_reconcile.py --check` diff==0；tick 对账日志累计 72h | **`state_reconcile.py` 不存在**；**`conductor/events.py`（append-only 事件日志，loop-state/events/*.jsonl）不存在**；tick 无对账步 | **❌ 未满足**：W2 关闭判定引用的对账工具未落地，72h 无从累计 → **开 W3-9** |
| 6 张演示卡事件流完整，产出 `waves/WAVE-03/evidence/72h-events.jsonl` | §7.3/§7.5（W3-7 出口） | 事件日志存在 + 72h 对账 diff=0 | 依赖 W3-9 的事件日志底座 | 由 W3-9 前置解决 |

### 明确的问题

1. **canary 无跨日累计**：canary.yml 每小时把 `canary/results.json` 覆盖写入，任何时刻只有"最近一次"的形态；"连续 N 晚全拦截"这类时间积累判定没有任何历史载体可查。违反 §5.4"连续 3 晚"的字面要求。
2. **W2 对账工具缺失**：WAVE-02 关闭判定 Q 组引用了 `python3 conductor/state_reconcile.py --check # diff==0`，但该文件与 append-only 事件日志均未落地；W2-1 布局常量虽声明 `events/` 目录，却无写入器与对账器。W3 入口"W2 全绿"因此存在一个隐性缺口，需先补齐。

---

## 波前清单（人类执行）

- [ ] 审批 dispatcher 四数值并写进 policy.yml：`max_concurrent_sandboxes`（建议 4）、每仓并发上限（建议 2）、API 配额令牌桶阈值（<20% 降级）、日预算（建议 $30）。
- [ ] 审批 escalation.yml 初版（ESC-01..12 与 SLA 24h、`on_sla_breach: freeze_merge_queue`）。**注**：AGENTS.md 将 `escalation.yml` 列为 W2 创建，但当前仓库不存在该文件——由 W3-4 新建，需本波人类审批准入。
- [ ] 准备本波演示用的 6 张 trivial/standard 卡（含 1 张跨仓卡、1 张 loop 机制卡、1 张注定失败一次的卡——用于验证 reaper 自愈）。
- [ ] kill switch 演练预约在波中第三天。

---

## 卡包发放表（W3）

### W3-1 · dispatcher 派卡引擎

```json loop
{
  "schema": 1,
  "id": "W3-1",
  "wave": "WAVE-03",
  "objective": "conductor/dispatcher.py：资格过滤（role/异构读租约/路径租约/依赖/预算/并发）→ 写 loop-state/assignments/<sandbox>.json → 沙盒只拉自己的卡（推-拉混合，领卡竞态消失）；assignment 篡改拒绝（ASSIGNMENT_MISMATCH）",
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
  "charter": ["G1", "N30"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.dispatcher import dispatch; print('ok')\" EXIT=0",
    "AC-2: grep -q 'assignments/' conductor/dispatcher.py（写 loop-state/assignments/<sandbox>.json）",
    "AC-3: 沙盒只拉自己的卡：dispatcher 输出含 sandbox 标识，拉取侧校验 assignment 一致（grep ASSIGNMENT_MISMATCH）",
    "AC-4: 资格过滤含 role / 异构读租约 / 路径租约 / 依赖 / 预算 / 并发（grep 断言各条件）",
    "AC-5（负证 N5): 把 sandbox-A 的 assignment 篡改指向 sandbox-B 的卡 → 拉取被拒 ASSIGNMENT_MISMATCH（EXIT≠0）"
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

### W3-2 · scoped token 铸造

```json loop
{
  "schema": 1,
  "id": "W3-2",
  "wave": "WAVE-03",
  "objective": "scoped token 铸造：每次会话由 App 铸单仓/所需权限/1h installation token（create-github-app-token v3，owner/repositories 收窄）；沙盒启动脚本接入；绝不下发常驻 token",
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
    "escalation.yml"
  ],
  "charter": ["N15", "G3"],
  "acceptance": [
    "AC-1: .github/workflows/scoped-token.yml 存在且用 create-github-app-token v3（grep）",
    "AC-2: grep -q 'repositories' scripts/scoped-token.sh（owner/repositories 收窄），且无 secrets.*PAT 引用",
    "AC-3: token 有效期 1h（expire 参数/llibre 短签发；grep）",
    "AC-4: 沙盒启动脚本接入该 token（grep 引用 scoped-token.sh 或 token 环境注入）",
    "AC-5（负证）: 尝试从中提炼常驻 token/PAT 形态 → 拒绝或 1h 后失效验证（脚本不含持久化路径）"
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
  "objective": "背压：并发/每仓上限/令牌桶（读 X-RateLimit-Remaining）/日预算；撞限显式降级+Incident（不静默）",
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
    "AC-2: grep -q 'X-RateLimit-Remaining' conductor/backpressure.py（令牌桶读配额余量）",
    "AC-3: grep -q 'budget' conductor/backpressure.py（日预算）",
    "AC-4: 撞限路径显式降级 + Incident（grep：降级分支写 Incident/issue，绝不静默 continue）",
    "AC-5（负证 N1）: 并当前离线设 1 时并发控制只放行 1 个（grep 语义 / 单测断言上限生效）"
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

### W3-4 · escalation + freeze_merge_queue

```json loop
{
  "schema": 1,
  "id": "W3-4",
  "wave": "WAVE-03",
  "objective": "escalation.yml + conductor/escalation.py：12 条触发器（ESC-01..12）+ SLA 24h；超时 freeze_merge_queue（设 repo var MERGE_FROZEN=1，required check merge-not-frozen 读取）",
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
  "charter": ["G1", "N11"],
  "acceptance": [
    "AC-1: escalation.yml 存在且含 ESC-01..ESC-12 至少 12 条触发条件（grep -c 'ESC-'）",
    "AC-2: escalation.yml 含 SLA 24h 与 on_sla_breach: freeze_merge_queue（grep）",
    "AC-3: conductor/escalation.py 可 import（python3 -c）且写 repo var MERGE_FROZEN=1（grep）",
    "AC-4: .github 侧有 merge-not-frozen required check 读取 MERGE_FROZEN（跨卡依赖 W3-4 外部，本卡 grep 断言 escalation.py 写入路径）",
    "AC-5（负证 N3）: SLA=1 分钟并制造人为超时 → 触发 freeze_merge_queue，escalation 写 Incident + MERGE_FROZEN=1（EXIT≠0 被拦；或 API 验证 var 置位）"
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

### W3-5 · HUMAN-QUEUE 完整化

```json loop
{
  "schema": 1,
  "id": "W3-5",
  "wave": "WAVE-03",
  "objective": "HUMAN-QUEUE 完整化：Project 写卡规则（每类人类决策自动入列+SLA 计时）；digest 接入 escalation 输出（次日 digest 含 SLA 列）",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "conductor/human_queue.py",
    "conductor/tick.py"
  ],
  "forbid_paths": [
    "conductor/dispatcher.py",
    "conductor/backpressure.py",
    "conductor/escalation.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
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
    "AC-1: python3 -c \"from conductor.human_queue import add_decision; print('ok')\" EXIT=0",
    "AC-2: grep 'SLA' conductor/human_queue.py（人类决策自动入列 + SLA 计时）",
    "AC-3: conductor/tick.py digest 调用 human_queue 且输出含 SLA 列（grep）",
    "AC-4: digest 接入 escalation 输出（grep escalation/human_queue 在 generate_digest 中被引用）",
    "AC-5: 每类人类决策有唯一规则键（grep human_queue 规则定义）"
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

### W3-6 · kill switch + ring 灰度

```json loop
{
  "schema": 1,
  "id": "W3-6",
  "wave": "WAVE-03",
  "objective": "kill switch + ring 灰度：policy.yml freeze 全链检查（W0-2 已铺）；rings:{ring0:[product-x], ring1:[], ring2:[\"*\"]} 配置与升级环联动（W6 用）；runbook（冻结/回滚 pin/全部打回 ready/导出状态）写进 docs/runbook-freeze.md",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "policy.yml",
    "docs/runbook-freeze.md"
  ],
  "forbid_paths": [
    "conductor/**",
    "loopd/**",
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
    "AC-1: policy.yml 含 rings 配置且有 ring0:[product-x]、ring1:[], ring2:[\"*\"]（grep）",
    "AC-2: policy.yml freeze.all=true 时 iterate 全链 no-op 语义被消费（grep freeze 读取方，W0-2 已铺须具现）",
    "AC-3: docs/runbook-freeze.md 存在且含 冻结/回滚 pin/全部打回 ready/导出状态 四节（grep 段落标题）",
    "AC-4（正证）: freeze.all=true 后运行全链 → 无写操作、日志含 FROZEN（见本波 Z 负证演练）",
    "AC-5: 升级环联动 rings 配置（grep upgrade_ring 或派卡读 ring 字段）"
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

### W3-7 · 72h 零干预演示执行（本波出口核心）

```json loop
{
  "schema": 1,
  "id": "W3-7",
  "wave": "WAVE-03",
  "objective": "72h 演示执行（BOT 主跑，人类只观察）：第 4 天 06:00 UTC 一次性投放 6 张演示卡，仅观察不动 72h；产出 waves/WAVE-03/evidence/72h-events.jsonl 完整事件流",
  "tier": "critical",
  "role": "verify",
  "paths": [
    "waves/WAVE-03/evidence/**"
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
    "escalation.yml"
  ],
  "charter": ["G0", "G1"],
  "acceptance": [
    "AC-1: events 日志存在且事件流完整：waves/WAVE-03/evidence/72h-events.jsonl 非空",
    "AC-2: 72h 内 ≥5 张演示卡 ready→merged 且事件日志无人类 actor（grep 人类 handle 不在 event writer 白名单）",
    "AC-3: ≥1 张经历 reaper 回收后重试成功（事件流含 reclaim->ready 重试序列）",
    "AC-4: ≥1 张跨仓卡、≥1 张 loop 机制卡完成（事件流含对应 repo 维度）",
    "AC-5: tick ≥11 步各有 last_success_at，liveness 能对单步报警（grep tick Step 注册表 + 单步指纹）",
    "AC-6: 72h 内 gh api rate_limit core remaining 从未低于 20%（记录 min）"
  ],
  "blocked_by": [
    "W3-1",
    "W3-2",
    "W3-3",
    "W3-4",
    "W3-5",
    "W3-6",
    "W3-8",
    "W3-9"
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

### W3-8 · ★回看补债：canary 连续 3 晚累计核验（承接 W1-9）

```json loop
{
  "schema": 1,
  "id": "W3-8",
  "wave": "WAVE-03",
  "objective": "回看补债（W1-9 时间积累项）：canary 改为按自然日累计，写 append-only 历史（canary/history.jsonl，跨日保留），并提供'连续 N 晚全拦截'的判定脚本；不再覆盖式写单快照 results.json",
  "tier": "standard",
  "role": "impl",
  "paths": [
    ".github/workflows/canary.yml",
    "canary/history.jsonl",
    "scripts/canary-nightly.sh"
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
  "charter": ["G3", "N29"],
  "acceptance": [
    "AC-1: canary.yml 输出按日累计写入 canary/history.jsonl（非覆盖单快照；grep 追加写）",
    "AC-2: canary/history.jsonl 每条含 date + count + all_intercepted（grep 字段），可回溯 ≥3 个自然日",
    "AC-3: scripts/canary-nightly.sh 存在且可判定'连续 N 晚全拦截'（G1.. 形态 + exit 逻辑）",
    "AC-4（负证 N29 双证）: 注入某晚一条未拦截记录 → 连续判定 FAIL（EXIT≠0），且无假绿",
    "AC-5: 当前 results.json 单快照逻辑被累计逻辑替代（grep 快照覆盖已移除/改追加）"
  ],
  "blocked_by": [],
  "budget": 0.6,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W3-9 · ★回看补债：事件-投影对账 + append-only 事件日志（承接 W2 关闭判定）

```json loop
{
  "schema": 1,
  "id": "W3-9",
  "wave": "WAVE-03",
  "objective": "回看补债（W2 关闭判定）：落地 conductor/events.py（append-only 事件日志，每行 JSONL，落到 loop-state/events/*.jsonl）+ conductor/state_reconcile.py --check（事件日志 vs 投影状态 diff=0）；tick 注册对账步（失败开 Incident），使'事件-投影对账连续 72h diff=0'变可判",
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
    "AC-1: python3 -c \"from conductor.events import append_event; print('ok')\" EXIT=0（可 import 且是追加非覆盖）",
    "AC-2: python3 -c \"from conductor.state_reconcile import reconcile; print('ok')\" EXIT=0",
    "AC-3: python3 conductor/state_reconcile.py --check 存在且（clean 时）EXIT=0、diff=0（grep --check 分支）",
    "AC-4: 事件日志路径指向 loop-state 下（grep events/ + loop-state 分支常量），不落 .gitignore 覆盖路径（N31）",
    "AC-5（负证 N29/N30）: 注入一条事件日志与投影不符（伪造/断链）→ 对账检出 diff≠0 + Incident（EXIT≠0），不 fail-open"
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

---

## 本波次的检查方法（Wave-level Gate）

> **关闭判定**：正证全过 + 负证全拦 + W3-7 72h 判据全绿 + 事件-投影对账连续 72h diff=0 → **WAVE-03: DONE**；任一 FAIL → NOT DONE。
> **入口先决**：W2 全绿（W3-9 补齐对账工具后方才成立）；dispatcher 四数值、error-escalation.yml 已人类审批；演示 6 卡已备。

### P. 入口（W2 确实绿 + W3 前置就位 + 对账工具落地）

```bash
bash .loop/smoke.sh                                  # → 16/16 PASS
python3 conductor/state_of_system.py --verify EXIT=0
python3 -c "from conductor.state_reconcile import reconcile; print('ok')"   # W3-9 已落地
git branch -a | grep -E 'loop-state'                 # → loop-state 分支存在
grep -q 'rings:' policy.yml && echo ok               # W3-6 前置（人类审批值）
```

### Q. 正证（每张卡 = 可运行检查）

```bash
# W3-1 dispatcher
python3 -c "from conductor.dispatcher import dispatch; print('ok')"        # EXIT=0
grep -q 'ASSIGNMENT_MISMATCH' conductor/dispatcher.py && echo ok
# W3-2 scoped token
grep -q 'create-github-app-token' .github/workflows/scoped-token.yml && echo ok
grep -q 'repositories' scripts/scoped-token.sh && echo ok
# W3-3 背压
python3 -c "from conductor.backpressure import check_budget; print('ok')"  # EXIT=0
grep -q 'X-RateLimit-Remaining' conductor/backpressure.py && echo ok
# W3-4 escalation
grep -c 'ESC-' escalation.yml | awk '$1>=12'                               # ≥12
grep -q 'MERGE_FROZEN' conductor/escalation.py && echo ok
# W3-5 human queue
python3 -c "from conductor.human_queue import add_decision; print('ok')"   # EXIT=0
grep -q 'SLA' conductor/human_queue.py && echo ok
# W3-6 kill switch + ring
grep -q 'ring0' policy.yml && echo ok
test -f docs/runbook-freeze.md && echo ok
# W3-8 canary 累计
python3 scripts/canary-nightly.sh --since 3 && echo ok                    # 连续3晚判定 EXIT=0
test -s canary/history.jsonl && echo ok
# W3-9 事件-投影对账
python3 conductor/state_reconcile.py --check                               # EXIT=0, diff=0
python3 -c "from conductor.events import append_event; print('ok')"
# W3-7 72h 判据（见卡 acceptance / §7.3）
# 事件-投影对账连续 72h diff=0（tick 对账日志）
python3 conductor/state_reconcile.py --check  # 连续 72h 每日复跑
```

### R. 负证（故障注入必须被拦，禁止 fail-open）

```bash
# W3-1 N5：assignment 篡改 → ASSIGNMENT_MISMATCH
# W3-3 N1：并当前置 1 → 并发控制只放行 1
# W3-4 N3：SLA=1min + 人为超时 → MERGE_FROZEN=1 + Incident
# W3-8  ：注入一晚未拦截记录 → 连续判定 FAIL（EXIT≠0）
# W3-9 N29/N30：伪造事件-投影不符 → diff≠0 + Incident（EXIT≠0）
# W3-6  ：freeze.all=true → 全链 no-op（exit 0 但 FROZEN、loop-state commit 数不变、无写）
# W3-2  ：无明显常驻 token / PAT 形态落入仓
```

### Z. 关闭（全过才算 DONE）

```bash
# Q 组全 EXIT=0 且 R 组全 EXIT≠0；
# W3-7 72h 判据全绿（§7.3 正证 1-6）+ 事件流完整（waves/WAVE-03/evidence/72h-events.jsonl 非空）
# 事件-投影对账连续 72h diff=0（W3-9 对账日志）
# findings/incidents 清零；gh api repos/Cloudbird-Software/loop/issues 无残留 incident
```

判定：Q 全部 EXIT=0 + R 全部 EXIT≠0 + W3-7 判据全绿 + 对账 72h diff=0 → **WAVE-03: DONE**

---

## Not Doing (主动放弃的项)

- **D1**: 不引入 dispatcher 之外的优化器/HQG/RHG/任何新扫描器——保持 dispatcher 只在"人类已投放卡"上分派（§7.0 防腐烂总闸门）。
- **D2**: 不做 silent_release.auto_merge=true——policy.yml 现为 false，保持人类对 trivial 子集放行的控制，留到 W5 之后再评估。
- **D3**: 不启用强模型验收环（ROUTING 中 review 段状态保持，W4 信号保真度后再评估）。
- **D4**: 不把 dispatcher 的四个数值写死进代码——一律经 policy.yml 由人类审批。

---

## Retro Prev（对上一波次的教训回应 + 本次回看）

**W0/W1/W2 时间积累项回看结论**（详见文首表）：
1.  canary 只有单快照、缺跨日累计（W1-9 "连续 3 晚"字面未满足）→ **W3-8 补债**。
2.  W2 关闭判定引用的 `state_reconcile.py` 与 append-only 事件日志从未落地，72h 对账无法累计 → **W3-9 补债**（也是 W3 入口隐性缺口的显性化）。

**W2/上游架构教训**：
- 卡状态、事件、审计已是 W2 三件套，但"事件日志"这一环只有布局常量、没有写入器与对账器——W2 关闭判定存在"声明了但没实现"的漂移。教训：关闭判定的每条检查都必须在提交前 `test -f`/`grep` 真存在，而非照抄文档方块。
- canary 这类周期任务的历史证据必须 append-only 落盘，禁止覆盖式单快照作为"连续 N 晚"的凭证。

---

## 人类摘要（≤200 字）

**本波次押注**：让执行真实自治——dispatcher 分派、scoped token（1h 短签发）、背压、escalation（SLA 24h + MERGE_FROZEN）、kill switch/ring，最后以 **72h 零人工干预演示**收官。同时按你的指令回看 W0/W1，发现并落地两张补债卡：**W3-8**（canary 连续 3 晚有了跨日累计证据）与 **W3-9**（W2 关闭判定里"事件-投影对账"这把一直没生成的钥匙终于造出来），两者是 W3 入口"W2 全绿"真正成立的前提。

**最大风险**：首张 72h 零干预会暴露 dispatcher/scoped-token/escalation 的集成断层（跨仓派卡、token 失效时序、freeze 联动），预判至少三处，暴露多少修多少。

**需要人类决策**：2 个——① dispatcher 四数值（并发/每仓上限/令牌桶阈值/日预算）写入 policy.yml；② escalation.yml 初版审批（当前仓库不存在该文件，需按本波 W3-4 新建并批准进入）。