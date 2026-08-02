# Card #244: [Card] W2-1 — conductor/cas.py::cas_update 真 CAS（git ref force=false，422→CASConflict→重读重试）+ loop-state 分支目录布局

**ID:** W2-1
**Tier:** standard
**Role:** impl
**Paths:** conductor/cas.py
**Forbidden:** .github/**, CHARTER.md, policy.yml, prompts/**, gates/**, conductor/tick.py, conductor/materialize.py, conductor/intent.py, conductor/state_audit.py, conductor/reconcile.py, loopd/**, lenses/**, settings/**, cards/**, waves/**, tests/**

## Acceptance Criteria
1. AC-1: python3 -c "from conductor.cas import cas_update" EXIT=0（模块可导入）
2. AC-2: 对同一 ref 以 base_sha=旧值并发两次 cas_update，恰一次成功、另一次抛 CASConflict 且零写（loop-state commit 数 == +1）
3. AC-3: cas_update 用 PATCH refs/heads/loop-state force=false（grep 源码断言 force=false 路径存在）
4. AC-4: 布局常量含 cards/leases/audit/plan/metrics/events/baselines（grep 断言）
5. AC-5（负证）: 以 force=true 或错误 base_sha 调用时 cas_update 必须拒绝/抛错，不得静默覆盖

## Body

