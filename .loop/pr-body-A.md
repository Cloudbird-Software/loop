# Package A — loopd 与沙盒层（卡包 A2/A4/W4-1/V3/V2 loopd 侧）

分支 `night/A` → `main`。合并顺序：A 先于 E（接口契约 0.6）。

## 做了什么

| 任务 | 实现 | 文件 |
|---|---|---|
| loop finding 无证据拒收 | 按 `.loop/schemas/finding.json` 校验：`evidence` ≥1 项、每项含 `tool`+`rule_id`+`location`，不符返回非零并说明（`NO_EVIDENCE`/`BAD_EVIDENCE`/`MISSING_FIELDS`） | `loopd/loopd.py` `h_finding`+`_validate_finding`；`.loop/schemas/finding.json` |
| loop propose `<wave.md>` | 开波次 PR，仅允许改 `waves/**`（越界 `OUT_OF_SCOPE` 拒收），PR 正文带「机器自检」占位段 | `loopd/loopd.py` `h_propose`+`_wave_pr_body` |
| loop verdict `<f.json>` | 按接口契约 0.6 VERDICT schema 全量校验；`head_sha ≠ 当前 HEAD` 拒收并提示重跑 | `loopd/loopd.py` `h_verdict`+`_validate_verdict`+`VERDICT_REQUIRED` |
| finding 标题改写 | 同 fingerprint 的 `occurrences ≥ 3` 时，强制把 body 内 `proposed_card` 标题改写为「为 X 写一个检查器」（X=lens 或 lens.rule_id，唯一 rule_id 时更具体） | `loopd/loopd.py` `_enforce_checker_title`+`_bump_occurrences` |
| bootstrap.sh 预热 opencode | pin 版本 + SHA256 校验（占位值，E 包回填；占位期间降级为打印 actual+警告，不阻断 bootstrap） | `loopd/bootstrap.sh` |
| UPSTREAM.yaml 追加 opencode | `sst/opencode` 条目（seam B，OPC-v4 P9 格式），A 包只追加、E 包全量整理 | `UPSTREAM.yaml` |
| smoke.sh 新增 Stage J | 共 11 项，含两个必测用例 | `.loop/smoke.sh` |

## 新增 handler 与动词表对照（SPEC.md §1）

| 动词 | handler | 状态 |
|---|---|---|
| `finding <file>` | `h_finding` (loopd.py:540) | +schema 校验/无证据拒收/occurrences≥3 标题改写 |
| `propose <file>` | `h_propose` (loopd.py:606) | +「机器自检」占位段/waves/** 越界拒收 |
| `verdict <file>` | `h_verdict` (loopd.py:658) | +VERDICT schema 全量校验/head_sha 过期拒收+重跑提示 |

辅助函数：`_validate_finding`(409) / `_extract_finding_block`(445) / `_finding_body`(456) / `_finding_title`(486) / `_enforce_checker_title`(489) / `_bump_occurrences`(510) / `_wave_pr_body`(587) / `VERDICT_REQUIRED`(629) / `_validate_verdict`(631)。

## 验收证据

验收命令：`LOOP_IO_MODE=shim bash .loop/smoke.sh`

```
=== Stage J: finding / propose / verdict handlers ===
PASS j1 无 evidence 字段的 finding 被拒（必测）
PASS j1a evidence 空数组的 finding 被拒（NO_EVIDENCE）
PASS j1b evidence 缺 rule_id/location 被拒
PASS j2 合法 finding（带 evidence）被接受
PASS j3 head_sha 过期的 verdict 被拒 + 重跑提示（必测）
PASS j4 verdict 缺 acs 被 schema 拒收
PASS j4b verdict ac 缺 evidence 被拒
PASS j5 合法 verdict（head_sha 匹配）被接受
PASS j6 occurrences>=3 改写 proposed_card 标题为'为 X 写一个检查器'
PASS j7 propose PR 正文带'机器自检'占位段（仅允许 waves/**）
PASS j8 propose 越界（含非 waves/**）被拒
STAGE_J_OK
PASS: j. finding/propose/verdict handlers (无证据拒收 + head_sha 过期拒收 + occurrences>=3 + 机器自检)

===============================
SMOKE RESULTS: 20 PASS, 0 FAIL
===============================
```

- 两个必测用例（j1 无 evidence 的 finding 被拒、j3 head_sha 过期的 verdict 被拒）均 **PASS**
- 全量 smoke：**20 PASS / 0 FAIL，退出码 0**

## 假设清单

1. **VERDICT schema 字段以接口契约 0.6 为准**：`acs` 每项要求 `id`(非空 str)/`pass`(bool)/`evidence`(非空 str，形如 `文件::用例名`)；契约未限定 `acs` 数组上限，按最小实现只要求 ≥1 项。
2. **finding 指纹** = `sha256(lens + "|" + path + "|" + message)` 取前 16 位；配额检查待 policy.yml `audit.max_new_findings_per_day` 落地后接入（SPEC.md §8 待裁决项 4）。
3. **occurrences≥3 标题改写**：仅作用于 finding body 内的 `proposed_card.title` 块；已 filed 的 Finding issue 外层标题不动（避免破坏 issue 引用稳定性）。
4. **opencode pin 版本占位 `v0.0.0`**：该 tag 不存在，bootstrap 下载走 degrade_path（打印 warning 跳过），不影响 smoke；E 包回填真实 release tag + SHA256 后自动启用硬校验（不匹配即跳过安装）。
5. **UPSTREAM.yaml 字段名用 `items`**（非 `packages`）：当前文件现值已是 `items`，A 包沿用不重命名；E 包负责全量整理与字段统一（接口契约 0.6 明确 E 包后于 A 包）。
6. **CHARTER.md 缺失**：finding 处理器不依赖 charter 映射（proposed_card 占位 `["G0"]` 即可），本包无影响。

## 跨包请求

1. **→ E 包**：回填 `UPSTREAM.yaml` 中 `sst/opencode` 的真实 `pin`(release tag) 与 `sha256`，并同步 `loopd/bootstrap.sh` 的 `OPENCODE_VERSION`/`OPENCODE_SHA256`（或让 bootstrap 直接读取 UPSTREAM.yaml）。占位值 `v0.0.0`/`PLACEHOLDER_FILL_BY_UPSTREAM` 未回填前，bootstrap 走 degrade_path 不阻断。
2. **→ E 包**：全量整理 UPSTREAM.yaml（字段名统一 packages→items、其余依赖补登记）。A 包仅追加了 opencode 一条。
3. **→ D 包**：VERDICT schema 文件（D 包建文件）落盘后若与本包 `_validate_verdict` 实现有出入，以接口契约 0.6 为准；如需调整请提跨包请求，A 包不擅自改 D 包文件。

## 给人类的待办

1. **opencode 真实版本/SHA256**：E 包回填前，bootstrap 的 opencode 安装会跳过（degrade_path），沙盒异构验证降级为「同模型自验证 + 开 Finding 告警」。建议 E 包尽快回填真实 release tag。
2. **安全免责（铁律 8）**：org ruleset 启用、required checks 回填、安全测试均不在今晚范围，已跳过。
3. **合并**：A 先于 E 合并（接口契约 0.6）。本 PR 不自行合并。
