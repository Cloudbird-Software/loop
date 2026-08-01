# WAVE-00 · 诚实化与止血（Day-0 + W0 合并）

> **目标**：不加任何新能力，让仓库停止对自己撒谎；四条病链转绿；平台免费项全部上锁。
> **入口条件**：Day-0 全部打勾。
> **波前冻结**：`WAVE_FROZEN=true`（已设），`git rev-parse HEAD` 作为基线。

## 波前清单（人类执行）

- [x] `WAVE_FROZEN=true`
- [x] 基线 HEAD：`54e0ef0`（2026-08-01 00:09 UTC）
- [x] 标签就位：needs-human / evidence-fraud / placebo-gate / rhg-watch / state-tamper / metric-incident
- [x] `waves/WAVE-00/evidence/` 目录就位
- [x] 根 CODEOWNERS 就位（机制路径 → @randypanding）

## 卡包发放表（W0）

```json loop
{
  "schema": 1,
  "id": "W0-1",
  "wave": "WAVE-00",
  "objective": "state_of_system.py 生成系统真实状态 + gate_maturity_evidence 标签升级需 run 证据",
  "tier": "standard",
  "role": "impl",
  "paths": ["conductor/state_of_system.py", "gates/gate_maturity_evidence.py", "docs/STATE-OF-THE-SYSTEM.md"],
  "forbid_paths": [".github/**", "policy.yml", "CHARTER.md", ".github/CODEOWNERS"],
  "charter": ["G1", "G3"],
  "acceptance": [
    "AC-1: python3 conductor/state_of_system.py --verify EXIT=0",
    "AC-2: cat gates/gate_maturity_evidence.py 含 NO_RUN_EVIDENCE 错误码 EXIT=0",
    "AC-3: cat docs/STATE-OF-THE-SYSTEM.md 含 chain 状态条目 EXIT=0"
  ],
  "blocked_by": [],
  "model_hint": "GLM-5.2",
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

```json loop
{
  "schema": 1,
  "id": "W0-2",
  "wave": "WAVE-00",
  "objective": ".loop/liveness.yml 登记 9 条 cron 期望周期 + policy.yml freeze 机制",
  "tier": "standard",
  "role": "impl",
  "paths": [".loop/liveness.yml", "policy.yml"],
  "forbid_paths": ["CHARTER.md", ".github/workflows/**", "conductor/tick.py", ".github/CODEOWNERS"],
  "charter": ["G1"],
  "acceptance": [
    "AC-1: cat .loop/liveness.yml 含 9 条 cron 期望（template-sync 30h / audit 30h / upgrade 180h / tick 1h / canary 2h / drift 8h / scribe 30h / nightly-rubric 30h / policy 168h）",
    "AC-2: cat policy.yml 含 freeze:{all:false, chains:[]} 配置",
    "AC-3: grep 'if frozen' .github/workflows/conductor.yml EXIT=0"
  ],
  "blocked_by": [],
  "model_hint": "GLM-5.2",
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

```json loop
{
  "schema": 1,
  "id": "W0-3",
  "wave": "WAVE-00",
  "objective": "诊断并修复 conductor 10 连败与 audit 3 连败的真实根因（Python 代码层）",
  "tier": "critical",
  "role": "impl",
  "paths": ["conductor/tick.py", "conductor/audit.py", ".github/workflows/audit.yml", "waves/WAVE-00/evidence/"],
  "forbid_paths": ["policy.yml", "CHARTER.md", ".github/workflows/pr-ci.yml", ".github/workflows/conductor.yml", ".github/CODEOWNERS"],
  "charter": ["G1"],
  "acceptance": [
    "AC-1: gh run list --workflow=audit.yml --limit 3 有 success",
    "AC-2: gh run list --workflow=conductor.yml --limit 10 连续绿",
    "AC-3: test -f waves/WAVE-00/evidence/root-cause.md EXIT=0"
  ],
  "blocked_by": ["W0-1"],
  "model_hint": "GLM-5.2",
  "budget": 1.5,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

```json loop
{
  "schema": 1,
  "id": "W0-4",
  "wave": "WAVE-00",
  "objective": "tick cron 降频（*/5→*/15）+ smoke f-a 规则修正 + 恢复 shadow-freshness 用例",
  "tier": "standard",
  "role": "impl",
  "paths": [".github/workflows/conductor.yml", ".loop/smoke.sh", "gates/gate_smoke.py", "DECISIONS.md"],
  "forbid_paths": ["policy.yml", "CHARTER.md", "conductor/tick.py", "conductor/audit.py", ".github/CODEOWNERS"],
  "charter": ["G0"],
  "acceptance": [
    "AC-1: grep 'cron' .github/workflows/conductor.yml 含 '*/15 * * * *'",
    "AC-2: bash .loop/smoke.sh EXIT=0 且 16/16 PASS（或 ADR 写入 DECISIONS.md）",
    "AC-3: cat DECISIONS.md 含 shadow-freshness 条目 或 bash .loop/smoke.sh 含该用例 EXIT=0"
  ],
  "blocked_by": [],
  "model_hint": "Seed-2.1-Turbo",
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

```json loop
{
  "schema": 1,
  "id": "W0-5",
  "wave": "WAVE-00",
  "objective": "tick 每日生成 HUMAN-TODO.md 四问 + digest issue 评论 + liveness 配置读取",
  "tier": "standard",
  "role": "impl",
  "paths": ["conductor/tick.py", ".loop/templates/human-todo.md"],
  "forbid_paths": ["policy.yml", "CHARTER.md", ".github/workflows/**", ".github/CODEOWNERS"],
  "charter": ["G1"],
  "acceptance": [
    "AC-1: python3 conductor/tick.py --generate-digest 生成 HUMAN-TODO.md 含四问",
    "AC-2: grep '卡在我这的' .loop/HUMAN-TODO.md EXIT=0",
    "AC-3: grep 'liveness' conductor/tick.py EXIT=0"
  ],
  "blocked_by": ["W0-2", "W0-3"],
  "model_hint": "GLM-5.2",
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

```json loop
{
  "schema": 1,
  "id": "W0-6",
  "wave": "WAVE-00",
  "objective": "根 CODEOWNERS 就位 + settings 文件更新（评审数 1 + code owner + required checks）",
  "tier": "critical",
  "role": "impl",
  "paths": [".github/CODEOWNERS", "settings/loop-main-protection.json", "settings/product-x-main-protection.json"],
  "forbid_paths": ["CHARTER.md", "policy.yml"],
  "charter": ["G0"],
  "acceptance": [
    "AC-1: cat .github/CODEOWNERS 包含机制路径→@randypanding",
    "AC-2: cat settings/loop-main-protection.json 含 require_code_owner_review:true",
    "AC-3: cat settings/product-x-main-protection.json 含相同配置"
  ],
  "blocked_by": [],
  "model_hint": "Seed-2.1-Turbo",
  "budget": 0.3,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

```json loop
{
  "schema": 1,
  "id": "W0-7",
  "wave": "WAVE-00",
  "objective": "workflow 中 GH_TOKEN/SCRIBE_GH_TOKEN 改为 App 铸造 + PAT 扫描 lens",
  "tier": "critical",
  "role": "impl",
  "paths": [".github/workflows/reusable-review.yml", ".github/workflows/nightly-rubric.yml", ".github/workflows/scribe.yml", "lenses/lens-pat-scan.sh"],
  "forbid_paths": ["CHARTER.md", "policy.yml", ".github/CODEOWNERS"],
  "charter": ["G3"],
  "acceptance": [
    "AC-1: grep -rn 'secrets.GH_TOKEN|secrets.SCRIBE_GH_TOKEN' .github/workflows/ 零命中",
    "AC-2: grep 'create-github-app-token' .github/workflows/ EXIT=0",
    "AC-3: bash lenses/lens-pat-scan.sh EXIT=0 或检出 PAT 形态凭据"
  ],
  "blocked_by": ["W0-1"],
  "model_hint": "GLM-5.2",
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

```json loop
{
  "schema": 1,
  "id": "W0-8",
  "wave": "WAVE-00",
  "objective": "actionlint + pinact 进 pr-ci + cron 语法自定义校验脚本",
  "tier": "trivial",
  "role": "impl",
  "paths": [".github/workflows/pr-ci.yml", "tools/check-cron.py"],
  "forbid_paths": ["CHARTER.md", "policy.yml", ".github/CODEOWNERS", "conductor/**"],
  "charter": ["G0"],
  "acceptance": [
    "AC-1: cat .github/workflows/pr-ci.yml 含 actionlint + pinact step",
    "AC-2: python3 tools/check-cron.py --cron '0 5 0 * *' EXIT=1",
    "AC-3: python3 tools/check-cron.py --cron '*/15 * * * *' EXIT=0"
  ],
  "blocked_by": [],
  "model_hint": "Seed-2.1-Turbo",
  "budget": 0.3,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

> ⚠ 路径交叉说明：W0-3 与 W0-5 在 `conductor/tick.py` 上有交叉。W0-5 已 `blocked_by: ["W0-3"]`，因此 W0-3 完成前 W0-5 不会启动。两张卡对 tick.py 的修改不同层面：W0-3 修复根因，W0-5 新增功能。

## 波后验收（双证）

### 正证
1. `python3 conductor/state_of_system.py --verify` → EXIT=0
2. `gh run list --workflow=conductor.yml --limit 20` → 最近 48h 全 success
3. `gh run list --workflow=audit.yml --limit 3` → ≥1 次 success
4. `bash .loop/smoke.sh` → 16/16 PASS
5. `gh api repos/Cloudbird-Software/product-x/rulesets/19949520 --jq .enforcement` → `active`
6. `gh api repos/Cloudbird-Software/loop --jq '.security_and_analysis.secret_scanning.status'` → `enabled`

### 负证
- N1：无 run 证据标签升级 → `gate_maturity_evidence` FAIL, `NO_RUN_EVIDENCE`
- N2：`freeze.all=true` → tick 退出 0、日志 `FROZEN`、无写操作
- N3：liveness 阈值临时改 1h → 开 Incident
- N4：非法 cron → actionlint 红

## 波后关闭

- 全部正证 + 负证通过
- 病链连续绿 48h
- Day-0 清单无欠账
