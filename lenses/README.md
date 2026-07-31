# Lenses 固化注册表（R12-6）

> **信任单调下降原则（R12-6）**：被强模型验收环独立复现确认（REPRODUCED）的 claim，
> 按 `policy.yml` 的 `review.harden_after_confirms`（默认 2）阈值固化为确定性 lens / 检查器。
> 固化后该缺陷类别不再依赖模型判断——系统对模型的信任单调下降，永不回升。
>
> 本注册表是「已固化检查器」的**唯一真源**，由 `conductor/harden.py` 维护；
> 任何手改都会被下次 `register_lens()` 之外的自洽性检查发现。新增条目请走
> `conductor/harden.py` 的 `register_lens()`，不要直接编辑下表。

## 已固化检查器

| lens 名 | 来源 claim id | 固化日期 | 覆盖缺陷类别 | 误报率 |
|---|---|---|---|---|
| no-fake-green | CL-N/A | 2026-07-30 | 假绿模式扫描 | 0.0 |
| gate-not-executed | CL-N/A | 2026-07-30 | GATE_NOT_EXECUTED 检测 | 0.0 |
| settings-ruleset-drift | CL-N/A | 2026-07-30 | settings 与线上 ruleset 往返一致 | 0.0 |

## 真实固化案例

> 固化卡交付时必须自带 ≥3 条真实固化案例（本节即所要求的案例集）。

1. **no-fake-green** — 源自审查裁决 P1-1（audit）。`.github/workflows/pr-ci.yml` 的
   `no-fake-green` job 静态扫描 workflow 中的吞错模式（`|| true` / `set +e` /
   `continue-on-error: true`），命中即非零退出（CHARTER N5）。确有正当理由的例外
   必须在行内或上一行写明 `fake-green-ok: <理由>`，让例外可追溯。固化日期
   2026-07-30，误报率 0.0。
2. **gate-not-executed** — 源自审查裁决 F-A（audit）。`gates/run_gates.py` 对
   `policy.yml gates.profiles.default` 声明但三处 search_dir 都找不到的 gate 返回
   exit code 2（`GATE_NOT_EXECUTED`），使「门禁静默 SKIP」等价于失败，根因 F-A
   （偷偷缩小 gate 集合 = 静默跳过）不再可能。固化日期 2026-07-30，误报率 0.0。
3. **settings-ruleset-drift** — 源自 settings 漂移（audit）。`conductor/drift_check.py`
   复用 `gates/gate_settings_roundtrip.py` 的比较逻辑，把 `settings/*.json` 与线上
   ruleset 做往返一致性比对；漂移即按稳定指纹开 Incident，**永不自动修**（CHARTER N5）。
   固化日期 2026-07-30，误报率 0.0。

## 如何新增条目

新增固化检查器一律通过 `conductor/harden.py` 的 `register_lens()` 追加，**不要手改本表**：

```python
from conductor.harden import register_lens
register_lens(
    name="my-checker",
    source_claim_id="CL-042",
    defect_category="某缺陷类别",
    false_positive_rate=0.0,
)
```

`register_lens()` 是幂等的：同名 lens 重复注册不会产生重复行；返回 `True` 表示新增了一行，
`False` 表示已存在（no-op）。`固化日期` 由 `register_lens()` 自动填入当天。

固化全流程（R12-6）：

1. claim 带 `suggested_checker` 字段，经强模型验收环独立复现确认（`REPRODUCED`，
   复现模型 ≠ 提出 claim 的模型，CHARTER N6）。
2. 同一 `suggested_checker` 确认次数达 `policy.yml review.harden_after_confirms`
   （默认 2）→ `should_harden()` 返回 `(True, reason)`。
3. `create_harden_card()` 开「写检查器」Card（`state=ready` / `tier=standard` /
   `role=impl` / `paths=[lenses/<name>.sh]`，验收标准必含
   「新检查器能在不调用任何 LLM 的情况下重现该缺陷」）。
4. `impl` 落地确定性 lens；验收通过后 `register_lens()` 在本表登记。
5. 后续同类 claim 经 `demote_future_claims()` 处理：已固化且确定性检查器当前绿
   （exit 0）时，给 claim 打 `already_hardened` 标记并把 `confidence` ×0.5 降权；
   检查器非绿 / 缺失 / 无法确认绿时不降权（保守）。
