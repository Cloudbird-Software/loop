# WAVE-02 · 状态权威与持久化

> **目标**：状态权威从 GitHub Issue 迁到 `loop-state` orphan 分支（一次解决伪 CAS、持久化黑洞、事件日志、audit 状态丢失四病）；单写者收口；epoch fencing；schema 单源；**产出系统历史上第一张 FMC-E 卡（分水岭）**。
> **入口条件**：W1 全绿；AGENT_APP 就位（Day-0 已做则跳过）。
> **宪法依据**：本波引用手册附录 A（已立法入 CHARTER N16-N35 + G6/G7）。
> **波结构**：W2-5 与 W2-6 并行；其余按路径互斥 + blocked_by 序化，防止 materialize 路径冲突。4 张 critical 卡各配 V2-x 异构 verify 卡（N8.5）。跨波次路径重叠由 materializer 按波次隔离判定，不构成冲突。

## 波前清单（人类执行）

- [ ] 建 `loop-state` orphan 分支（一次性）：`git checkout --orphan loop-state && git rm -rf . && git commit --allow-empty -m "loop-state init" && git push origin loop-state`
- [ ] 加 ruleset：`loop-state` 分支仅允许 CONDUCTOR_APP push（bypass 仅该 App；拒 force push、拒删除）
- [ ] 迁移纪律宣讲：本波之后 `.loop/audit/**`、`.loop/plan/inbox/**`、metrics、baselines 一律落 loop-state；`.gitignore` 对应该指向真正临时目录
- [ ] CHARTER N16-N35 + G6/G7 已立法（本 PR 落地）

---

## 卡包发放表（W2）

### W2-1 · loop-state 布局 + 真 CAS

```json loop
{
  "schema": 1,
  "id": "W2-1",
  "wave": "WAVE-02",
  "objective": "conductor/cas.py::cas_update 真 CAS（git ref force=false，422→CASConflict→重读重试）+ loop-state 分支目录布局",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "conductor/cas.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/intent.py",
    "conductor/state_audit.py",
    "conductor/reconcile.py",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G1", "G3", "N31"],
  "acceptance": [
    "AC-1: python3 -c \"from conductor.cas import cas_update\" EXIT=0（模块可导入）",
    "AC-2: 对同一 ref 以 base_sha=旧值并发两次 cas_update，恰一次成功、另一次抛 CASConflict 且零写（loop-state commit 数 == +1）",
    "AC-3: cas_update 用 PATCH refs/heads/loop-state force=false（grep 源码断言 force=false 路径存在）",
    "AC-4: 布局常量含 cards/leases/audit/plan/metrics/events/baselines（grep 断言）",
    "AC-5（负证）: 以 force=true 或错误 base_sha 调用时 cas_update 必须拒绝/抛错，不得静默覆盖"
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

### W2-2 · 单写者 intent.yml

```json loop
{
  "schema": 1,
  "id": "W2-2",
  "wave": "WAVE-02",
  "objective": "单写者 intent.yml：repository_dispatch loop-intent 接收 agent 意图→CONDUCTOR_APP 经 cas 写→回写；loopd 状态写改发意图+轮询；done/verified 仅 CI 身份可写",
  "tier": "critical",
  "role": "impl",
  "paths": [
    ".github/workflows/intent.yml",
    "conductor/intent.py"
  ],
  "forbid_paths": [
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/cas.py",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/state_audit.py",
    "conductor/reconcile.py",
    "conductor/schema_types.py",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["N19", "N30", "G1"],
  "acceptance": [
    "AC-1: .github/workflows/intent.yml 存在且 event=repository_dispatch、type=loop-intent（grep 断言）",
    "AC-2: 本地 CAS 保留为快速失败；正常路径经发意图+轮询（源码 grep：intent 提交+轮询存在）",
    "AC-3（负证 N1）: 用 AGENT_APP 直 gh issue edit 写 state:verified → 权限拒绝",
    "AC-4（负证 N2）: 用 AGENT_APP 直 push loop-state → ruleset 拒绝",
    "AC-5: done/verified 仅 CI 身份可写（N19/N30；源码 grep：h_done 上限 in_review）"
  ],
  "blocked_by": ["W2-1"],
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

### V2-2 · 单写者异构验证

```json loop
{
  "schema": 1,
  "id": "V2-2",
  "wave": "WAVE-02",
  "objective": "对 W2-2 单写者做异构盲验证：负证 N1/N2（AGENT_APP 写 state:verified 被拒、直 push loop-state 被拒）+ 正证（intent 收到即经 cas 写）+ 产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W2-2",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/w2-2.json"
  ],
  "forbid_paths": [
    ".github/**",
    "conductor/intent.py",
    "conductor/cas.py"
  ],
  "charter": ["N19", "N30", "G1"],
  "acceptance": [
    "AC-1: 用 AGENT_APP 直 gh issue edit 写 state:verified → 权限拒绝（负证 N1，EXIT≠0）",
    "AC-2: 用 AGENT_APP 直 push loop-state → ruleset 拒绝（负证 N2，EXIT≠0）",
    "AC-3: 正常通道经 intent 提交+轮询可写状态成功（正证 EXIT=0）",
    "AC-4: 盲一半：只读 W2-2 的 schema 与命令输出，不读 W2-2 源码注释与过程评论，据命令输出判 PASS/FAIL",
    "AC-5: VERDICT 写为 .loop/verdicts/w2-2.json，含 card_id=W2-2 + 证据清单，verifier_model.vendor ≠ impl_model.vendor"
  ],
  "blocked_by": ["W2-2"],
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

### W2-3 · epoch fencing + 看门狗 + gate_epoch

```json loop
{
  "schema": 1,
  "id": "W2-3",
  "wave": "WAVE-02",
  "objective": "epoch fencing：领卡 lease_epoch=attempt；分支 card/<id>/e<epoch>；每次写携 epoch，StaleLeaseError 自杀；看门狗租约到期未续→中止本地工作；gates/gate_epoch.py 分支 epoch≠卡 epoch→FAIL+自动关 PR",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "gates/gate_epoch.py",
    "loopd/domain/lease.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/state_audit.py",
    "conductor/reconcile.py",
    "loopd/loopd.py",
    "loopd/domain/transitions.py",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    "rules/**"
  ],
  "charter": ["G1", "N17"],
  "acceptance": [
    "AC-1: loopd/domain/lease.py 含 lease_epoch 写入；分支名 pattern card/<id>/e<epoch>（grep 断言）",
    "AC-2: 看门狗线程在租约到期未续时中止本地工作（源码 grep：watchdog 超时→本地退出）",
    "AC-3: gates/gate_epoch.py 存在且校验 PR 分支 epoch 与卡 epoch（grep 断言）",
    "AC-4（负证 N3）: 以过期 epoch 推 card/<id>/e<old> 开 PR → gate_epoch FAIL + 自动关 PR（EXIT=GATE）"
  ],
  "blocked_by": ["W2-2"],
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

### W2-4 · 哈希链完整性 + state_audit

```json loop
{
  "schema": 1,
  "id": "W2-4",
  "wave": "WAVE-02",
  "objective": "哈希链：卡块 integrity:{seq,prev,writer,nonce}；conductor/state_audit.py 重放 timeline/userContentEdits：seq 连续/prev 链得上/writer∈白名单；断链→回滚最后合法版+Incident(state-tamper)+quarantined",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "conductor/state_audit.py",
    "conductor/state.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/reconcile.py",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G3", "N29"],
  "acceptance": [
    "AC-1: python3 conductor/state_audit.py --verify EXIT=0（seq/prev/writer 全部合法、writer∈白名单）",
    "AC-2: conductor/state.py 定义 integrity:{seq,prev,writer,nonce}（grep 断言）",
    "AC-3（负证 N4）: CONDUCTOR_APP 伪造 prev 断链 commit → state_audit 检出 + Incident + 卡 quarantined",
    "AC-4: 断链时回滚到最后合法版本（源码 grep：回滚逻辑存在）"
  ],
  "blocked_by": ["W2-2"],
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

### V2-4 · 哈希链审计异构验证

```json loop
{
  "schema": 1,
  "id": "V2-4",
  "wave": "WAVE-02",
  "objective": "对 W2-4 哈希链做异构盲验证：负证（伪造断链 commit 被 state_audit 检出 + Incident + quarantined）+ 正证（完整链 verify EXIT=0）+ 产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W2-4",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/w2-4.json"
  ],
  "forbid_paths": [
    "conductor/state_audit.py",
    "conductor/state.py"
  ],
  "charter": ["G3", "N29"],
  "acceptance": [
    "AC-1: python3 conductor/state_audit.py --verify EXIT=0（正证：完整链合法）",
    "AC-2: 注入伪造 prev 断链 commit → state_audit 检出 + Incident(state-tamper) + 卡 quarantined（负证 EXIT≠0）",
    "AC-3: 断链时回滚到最后合法版本（源码 grep 回滚逻辑存在）",
    "AC-4: 盲一半：只读 W2-4 schema 与命令输出，不读 W2-4 源码注释与过程评论",
    "AC-5: VERDICT 写为 .loop/verdicts/w2-4.json，含 card_id=W2-4 + 证据清单，verifier_model.vendor ≠ impl_model.vendor"
  ],
  "blocked_by": ["W2-4"],
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

### W2-5 · schema 单一事实源 + 卡方言统一

```json loop
{
  "schema": 1,
  "id": "W2-5",
  "wave": "WAVE-02",
  "objective": "schema 单源：datamodel-code-generator 生成 conductor/schema_types.py（CI 校验与源一致）；全代码从生成物读；gate_schema_singlesource；读者接受 {N,N-1}+SCHEMA_UNSUPPORTED；统一双卡方言（lease_until/model/attempt 必填）",
  "tier": "standard",
  "role": "impl",
  "paths": [
    ".loop/schemas/**",
    "conductor/schema_types.py",
    "gates/gate_schema_singlesource.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/gate_epoch.py",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/state_audit.py",
    "conductor/state.py",
    "conductor/reconcile.py",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    "rules/**"
  ],
  "charter": ["G3"],
  "acceptance": [
    "AC-1: 生成物与源一致（重新生成后 git diff 为空）",
    "AC-2: grep -rn 'lease_until' --include='*.py' loopd/ conductor/ gates/ | grep -v schema_types | wc -l → 0（注释除外）",
    "AC-3: gates/gate_schema_singlesource.py 存在（grep 断言）",
    "AC-4（负证）: 未知 schema 版本 → SCHEMA_UNSUPPORTED 显式错误（拒绝而非 fail-open）"
  ],
  "blocked_by": ["W2-1"],
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

### W2-6 · 声明式转移表 + merge-completion

```json loop
{
  "schema": 1,
  "id": "W2-6",
  "wave": "WAVE-02",
  "objective": "声明式转移表 loopd/domain/transitions.py（含 done/closed/respec/stalled/orphaned/merged/abandoned；ALLOWED_TRANSITIONS_BY_SOURCE：ci 可写 verified、judgment 只能 failed、agent 只走前三步）+ 穷举性质测试 + merge-completion reconciler（merged→done+merged_sha+unblock_deps）；reaper 限 {claimed,in_progress}；reaper 判据=心跳判活、CI run 判进展",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "loopd/domain/transitions.py",
    "conductor/reconcile.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/tick.py",
    "conductor/materialize.py",
    "conductor/state_audit.py",
    "conductor/state.py",
    "loopd/loopd.py",
    "loopd/domain/lease.py",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["N19", "G1"],
  "acceptance": [
    "AC-1: pytest 穷举性质测试全绿（states×events 全空间有定义；非法转移全抛 IllegalTransition）",
    "AC-2: conductor/reconcile.py 实现 merged→done + merged_sha + unblock_deps；被踢→ready(attempt+1)（grep 断言）",
    "AC-3: reaper 判据=心跳判活、CI run 判进展（源码 grep：运行中 CI→租约自动延期）",
    "AC-4（负证 N6）: 构造 verified→in_progress 非法转移 → IllegalTransition",
    "AC-5: 12 分钟无 commit 的 CI → 卡未被 reaper 回收、attempt 不变（长 CI 实验）"
  ],
  "blocked_by": ["W2-2"],
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

### V2-6 · 转移表异构验证

```json loop
{
  "schema": 1,
  "id": "V2-6",
  "wave": "WAVE-02",
  "objective": "对 W2-6 声明式转移表做异构盲验证：负证（verified→in_progress 非法转移抛 IllegalTransition）+ 正证（穷举性质测试全绿）+ 产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W2-6",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/w2-6.json"
  ],
  "forbid_paths": [
    "loopd/domain/transitions.py",
    "conductor/reconcile.py"
  ],
  "charter": ["N19", "G1"],
  "acceptance": [
    "AC-1: pytest -q tests/test_transitions.py 全绿（正证：全空间有定义）",
    "AC-2: 构造 verified→in_progress 非法转移 → 抛 IllegalTransition（负证 EXIT≠0）",
    "AC-3: merged→done+merged_sha+unblock_deps 的 reconciler 行为可验证（正证 EXIT=0）",
    "AC-4: 盲一半：只读 W2-6 schema 与命令输出，不读源码注释与过程评论",
    "AC-5: VERDICT 写为 .loop/verdicts/w2-6.json，含 card_id=W2-6 + 证据清单，verifier_model.vendor ≠ impl_model.vendor"
  ],
  "blocked_by": ["W2-6"],
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

### W2-7 · materializer 事务化 + loopd 分层

```json loop
{
  "schema": 1,
  "id": "W2-7",
  "wave": "WAVE-02",
  "objective": "materializer 事务化：幂等键 CARD-<wave>-<idx>-<sha8>+upsert+materialized.json（completed_at 最后写）+tick[materialize_repair]+gate_wave_immutable；loopd 分层（cli/usecases/domain/ports/adapters，契约测试守护行为不变）",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "conductor/materialize.py",
    "loopd/loopd.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/tick.py",
    "conductor/state_audit.py",
    "conductor/state.py",
    "conductor/reconcile.py",
    "loopd/domain/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G0", "N31"],
  "acceptance": [
    "AC-1: 幂等键 CARD-<wave>-<idx>-<sha8> + upsert + materialized.json（grep 断言）",
    "AC-2: 故障测试：物化中途杀进程→重跑收敛（无重复无缺失）",
    "AC-3: loopd 分层（cli/usecases/domain/ports/adapters；grep 断言分层目录/模块存在）",
    "AC-4: W1-1 契约测试仍全绿（python3 loopd/loopd.py help + pytest -q，行为不变守护）"
  ],
  "blocked_by": ["W2-6"],
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

### V2-7 · 事务化/分层异构验证

```json loop
{
  "schema": 1,
  "id": "V2-7",
  "wave": "WAVE-02",
  "objective": "对 W2-7 materializer 事务化 + loopd 分层做异构盲验证：正证（幂等重跑收敛）+ 负证（叠加重复卡被收敛/无重复）+ 产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W2-7",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/w2-7.json"
  ],
  "forbid_paths": [
    "conductor/materialize.py",
    "loopd/loopd.py"
  ],
  "charter": ["G0", "N31"],
  "acceptance": [
    "AC-1: python3 loopd/loopd.py help 契约仍可用（正证：行为不变，EXIT=0）",
    "AC-2: 重跑 materializer 物化同一 wave → 幂等收敛，无重复卡、无缺失卡（正证 EXIT=0）",
    "AC-3: 故障恢复：模拟中途中断后重跑 → 收敛（负证不产生重复物化，EXIT=0 且无重复）",
    "AC-4: 盲一半：只读 W2-7 schema 与命令输出，不读源码注释与过程评论",
    "AC-5: VERDICT 写为 .loop/verdicts/w2-7.json，含 card_id=W2-7 + 证据清单，verifier_model.vendor ≠ impl_model.vendor"
  ],
  "blocked_by": ["W2-7"],
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

### W2-8 · 身份外置 + tick supervisor

```json loop
{
  "schema": 1,
  "id": "W2-8",
  "wave": "WAVE-02",
  "objective": "身份外置：materializer/派卡把 model/family 写入 leases/<card>.json（agent 只读）；policy.yml models: 段落地；gate_heterogeneity 改读租约+family/vendor 级；verdict.verifier_model 从租约取；tick supervisor 化（Step 注册表+per-step 超时/异常/last_success_at，禁止 try/except pass）；接 W2-4 的 state_integrity_audit 步",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "conductor/tick.py",
    "conductor/materialize.py",
    "gates/gate_heterogeneity.py",
    "policy.yml"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "prompts/**",
    "gates/gate_epoch.py",
    "gates/gate_schema_singlesource.py",
    "conductor/cas.py",
    "conductor/intent.py",
    "conductor/state_audit.py",
    "conductor/state.py",
    "conductor/reconcile.py",
    "conductor/schema_types.py",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    "rules/**"
  ],
  "charter": ["G4", "N30", "G1"],
  "acceptance": [
    "AC-1: materializer 派卡把 model/family 写入 leases/<card>.json（agent 只读；grep 断言）",
    "AC-2: policy.yml 含 models: 段（id→family→vendor 映射，grep 断言）",
    "AC-3: gate_heterogeneity 改读租约 + family/vendor 级（grep 断言读租约非 env）",
    "AC-4: tick supervisor 化：Step 注册表 + per-step 超时/异常/last_success_at（grep 断言）",
    "AC-5（负证 N5）: 沙盒内篡改 LOOP_MODEL env 后领 verify 卡 → 判定不受影响（读租约而非 env）"
  ],
  "blocked_by": ["W2-7"],
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

### W2-9 · ★ FMC-E 首卡（人类亲手驱动，不派 agent 自主权）

```json loop
{
  "schema": 1,
  "id": "W2-9",
  "wave": "WAVE-02",
  "repo": "product-x",
  "objective": "在 product-x 仓产出一张满足全部硬条件的卡（全机器端到端、证据链完整）：materializer 建→agent 领→CI 门禁全绿（无 SKIP）→verdict 由 CI 身份发布且 head_sha 绑定→merge queue 合入→卡自动终态。内容建议：给 tests/acceptance/ 加健康检查断言",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "product-x/tests/acceptance/**"
  ],
  "verify": "本卡为跨仓卡（repo=product-x），路径带 product-x/ 前缀；在 loop 建单、在 product-x 开 PR，PR 正文反向链接回本 loop；验收按 FMC-E 七条件机械核验。",
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/**",
    "loopd/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "human_action": "人类亲手驱动演示（按手册 §6.3 剧本：materializer dry_run=false 物化→impl 沙盒走 next/save/verify/done→verify 沙盒（Kimi-K3）产 verdict→merge→自动终态。agent 只观察、只 Launch，不获得自主实现权）。详见手册 §6.3 七条件。",
  "charter": ["G0", "G6"],
  "acceptance": [
    "AC-1: 卡 issue comment 含合法 json verdict 块且 gate_verdict 通过（run id）",
    "AC-2: verdict.head_sha == 合并前 PR head SHA（gh pr view --json headRefOid 独立复算）",
    "AC-3: verifier_model.vendor ≠ impl_model.vendor（从 loop-state/leases/ 读，不从块读）",
    "AC-4: acs[].id 全部命中卡的 acceptance ids，无孤儿",
    "AC-5: 卡 lease_until/heartbeat_at/attempt/model 四字段非 null（对照 F2：卡真的被领过）",
    "AC-6: PR 经 merge queue 合入（gh pr view --json mergedAt 非空，required checks 全绿）",
    "AC-7: 合并 commit 是 origin/main 祖先（git merge-base --is-ancestor <sha> origin/main EXIT=0）"
  ],
  "blocked_by": ["W2-3", "W2-4", "W2-5", "W2-8"],
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

> **关闭判定**：正证全过 + 负证全拦 + FMC-E 七条件满足 + 事件-投影对账连续 72h diff=0 → **WAVE-02: DONE**；任一 FAIL → NOT DONE。
> **入口先决**：W1 波次关闭判定已通过；AGENT_APP 就位；loop-state 分支已建。

### P. 入口（W1 确实绿 + W2 前置就位）

```bash
bash .loop/smoke.sh            # → 16/16 PASS
python3 conductor/state_of_system.py --verify EXIT=0
git branch -a | grep -E 'loop-state'   # → loop-state 分支存在
```

### Q. 正证（每张卡 = 可运行检查）

```bash
# W2-1：真 CAS + 并发
python3 -c "from conductor.cas import cas_update"           # EXIT=0
# 并发实验（§6.4-2）
python3 conductor/cas.py --concurrency-test                  # 5 沙盒 / 恰 1 成功其余 CASConflict / commit 数==+1
# W2-2：单写者 intent 通道（正证）
grep -q 'loop-intent' .github/workflows/intent.yml && echo ok  # event=repository_dispatch type=loop-intent
grep -q 'done' conductor/intent.py && echo ok                 # 状态写发意图
# W2-3：epoch fencing（正证；epoch 推导见 W2-3 AC）
python3 -c "from loopd.domain.lease import lease_epoch; print('ok')"  # lease_epoch 写入
grep -q 'e{epoch}\|e<%s>%.*epoch' loopd/domain/lease.py && echo ok    # 分支名含 epoch
# W2-4：审计完整性
python3 conductor/state_audit.py --verify                   # EXIT=0
python3 conductor/state_reconcile.py --check                # diff==0
# W2-5：schema 单源
python3 -c "import conductor.schema_types; print('ok')"     # EXIT=0
grep -rn 'lease_until' --include='*.py' loopd/ conductor/ gates/ | grep -v schema_types | wc -l  # → 0
# W2-6：转移表穷举 + merge-completion
pytest -q tests/test_transitions.py                          # 全绿：全空间有定义
# W2-7：materializer 事务化 + loopd 分层（正证，§6.4-3）
python3 loopd/loopd.py help | python3 -m json.tool >/dev/null # 契约仍可用
python3 -c "from conductor.materialize import CARD_KEY; print('ok')"  # 幂等键存在
# W2-8：身份外置读租约
grep -q 'leases/' gates/gate_heterogeneity.py && echo ok     # 读租约非 env
grep -q 'models:' policy.yml && echo ok                      # models 段存在
# V2-x：4 张 verify 卡的 VERDICT（见各自卡 acceptance）
# FMC-E 七条件（W2-9，见卡 acceptance）
# 持久化验证（§6.4-4）：.loop/audit/state.json 在 loop-state；连续 3 次 audit 后 occurrences≥2
python3 conductor/state_audit.py --verify
jq -e '.occurrences >= 2' .loop/audit/state.json            # 或等价检查
```

### R. 负证（故障注入必须被拦，禁止 fail-open）

```bash
# W2-2 N1：AGENT_APP 直写 state:verified → 权限拒绝
# W2-2 N2：AGENT_APP 直 push loop-state → ruleset 拒绝
# W2-3 N3：过期 epoch 推 card/<id>/e<old> → gate_epoch FAIL + 自动关 PR
# W2-4 N4：伪造 prev 断链 commit → state_audit 检出 + Incident + quarantined
# W2-5    ：未知 schema 版本 → SCHEMA_UNSUPPORTED 显式错误
# W2-6 N6：verified→in_progress → IllegalTransition
# W2-7    ：重复卡号/断幂等 → materializer 收敛不产生重复物化（叠加后无重复）
# W2-8 N5：篡改沙盒 LOOP_MODEL env 领 verify 卡 → 判定不受影响（读租约）
# V2-2    ：AGENT_APP 写 state/wrong 或 push loop-state 被拒（对应 W2-2 N1/N2）
# V2-4    ：伪造断链 commit → state_audit 检出 + quarantined（对应 W2-4 N4）
# V2-6    ：verified→in_progress → IllegalTransition（对应 W2-6 N6）
# V2-7    ：中途中断后重跑 → 无重复物化（对应 W2-7 幂等负证）
```

### Z. 关闭（全过才算 DONE）

```bash
# 上述 Q 组全 EXIT=0 且 R 组全 EXIT≠0；且：
# FMC-E 七条件证据入 waves/WAVE-02/evidence/first-verdict/
# 事件-投影对账连续 72h diff=0（tick 对账日志）
gh api "repos/Cloudbird-Software/loop/issues" --jq 'length'  # 无残留 incident；findings 清零
```

判定：Q 全部 EXIT=0 + R 全部 EXIT≠0 + FMC-E 七条件满足 + 对账 diff=0 → **WAVE-02: DONE**

---

## Not Doing (主动放弃的项)

- **D1**: 不引入 dispatcher / holdout / RHG / router / 任何优化器 / 任何新扫描器（这些是 W3+ 的事，手册 §6.5 禁止项复核）。
- **D2**: 不做 git ref CAS 的从旁实现——W2 采用"真 CAS（ref force=false）+ 单写者"，git ref CAS 完整方案入 ADR 备选。
- **D3**: 不改动 CHARTER N 段以外的产品逻辑；N 段立法由本波人类批准。

---

## Retro Prev（对上一波次的教训回应）

**W1 教训回顾**：
1.  CLI 契约测试覆盖了用户可见行为，但状态权威仍在 Issue（伪 CAS / 持久化黑洞）。
2.  多卡共享 tick.py / materialize.py / loopd.py，路径冲突需用 blocked_by 序化。
3.  schema 未被代码消费（V-602），"看似生效"的契约制造了第二种真相。

**W2 针对教训的改进**：
1.  W2-1 真 CAS + W2-4 哈希链，把状态权威迁到 loop-state，堵死伪 CAS 与持久化黑洞。
2.  波次卡表按路径互斥 + blocked_by 序化设计（W2-4→W2-7 上 tick/materialize 由后继卡串行持有），规避冲突。
3.  W2-5 schema 单源，代码从生成物读，杜绝手写字段列表。

---

## 人类摘要（≤200 字）

**本波次押注**：把"状态的真相"从 GitHub Issue 与 gitignored 目录，迁到受 CAS 保护的 `loop-state` 分支，配单写者、epoch fencing、哈希链、schema 单源；产出第一张 FMC-E 卡作为全案分水岭。这是从"能跑"到"状态可信 + 可审计"的关键一步。

**最大风险**：首张 FMC-E 卡会暴露单元测试发现不了的集成问题（跨仓 verdict 发错仓、verdict head_sha 绑定、acceptance 结构化），预判至少三处，暴露多少修多少。

**需要人类决策**：1 个——本 pack 同时交付 CHARTER N16-N35 + G6/G7 立法（本 PR）；AGENT_APP 就位与 loop-state 分支创建（波前）。
