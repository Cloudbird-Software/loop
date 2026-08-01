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

| 卡ID | 内容与产出 | 模型 | 验收命令 |
|---|---|---|---|
| W0-1 | state_of_system.py + 成熟度证据门 | GLM-5.2 (mechanism) | `python3 conductor/state_of_system.py --verify` → 0 |
| W0-2 | liveness 全链化 | GLM-5.2 | `cat .loop/liveness.yml` 含 9 条 cron 期望 |
| W0-3 | 病链根因修复（conductor 10 连败 + audit 3 连败） | GLM-5.2 | `gh run list --workflow=audit.yml --limit 3` 有 success |
| W0-4 | tick 降频 + smoke 修正 | Seed-2.1-Turbo + GLM-5.2 | `bash .loop/smoke.sh` → 16/16 PASS |
| W0-5 | digest 自动化 | GLM-5.2 | `HUMAN-TODO.md` 每日自动更新四问 |
| W0-6 | 平台确权（CODEOWNERS + ruleset settings） | Seed-2.1-Turbo（起草）+ 人类（应用） | `gh api .../rulesets/<id>` 两仓复核 |
| W0-7 | token 重建（GH_TOKEN/SCRIBE_GH_TOKEN → App 铸造） | GLM-5.2 | `grep -rn 'secrets.GH_TOKEN\|secrets.SCRIBE_GH_TOKEN' .github/workflows/` 零命中 |
| W0-8 | cron/工作流静态门 | Seed-2.1-Turbo | 负证：非法 cron PR → CI 红 |

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
