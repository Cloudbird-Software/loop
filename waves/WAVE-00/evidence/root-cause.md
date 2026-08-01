# W0-3 根因分析：conductor 10+ 连败 & audit 3 连败

> 本文件满足 W0-3 AC-3：`test -f waves/WAVE-00/evidence/root-cause.md` 且
> `grep -c '根因\|root cause\|traceback'` > 0。记录两条病链的真实根因、复现证据
> 与修复方式，供 verify 与后续 audit lens 复核。

## 病链 1：conductor.yml 连续 10+ 次失败

### 根因（root cause）

`conductor/tick.py` 在 `race_mode_handler()` 内有一处**延迟导入**没有 sys.path 兜底：

```python
# conductor/tick.py:738（修复前）
def race_mode_handler():
    ...
    from conductor.claim_intake import is_claim_pickable_by_impl   # ← 崩在这里
```

conductor.yml 的 tick step 以 `python conductor/tick.py` 直接运行脚本。此时
`sys.path[0]` 是脚本所在目录 `conductor/`（而非仓库根），所以
`from conductor.claim_intake import ...` 去找 `conductor/conductor/claim_intake.py`，
找不到 → 抛 `ModuleNotFoundError: No module named 'conductor'`。

文件顶部（line 14-17）本有 try/except fallback，但只兜住了 `conductor.blocks`
一个导入；line 738 的 `conductor.claim_intake` 没有任何兜底，直接崩。

### 复现证据（traceback）

本地在 W0-3 worktree（HEAD=W0-4 commit 627530c，即修复前基线）直接运行：

```
$ python conductor/tick.py
...
[11] Race mode: critical dual-impl → pick winner, close loser, diff to journal...
Traceback (most recent call last):
  File "/tmp/loop-wt/W0-3/conductor/tick.py", line 830, in <module>
    main()
  File "/tmp/loop-wt/W0-3/conductor/tick.py", line 826, in main
    race_mode_handler()         # [11]
    ^^^^^^^^^^^^^^^^^^^
  File "/tmp/loop-wt/W0-3/conductor/tick.py", line 738, in race_mode_handler
    from conductor.claim_intake import is_claim_pickable_by_impl
ModuleNotFoundError: No module named 'conductor'
```

CI 侧对应 run：`Cloudbird-Software/loop` conductor.yml run `30684245290`
（最近一次 failure，traceback 同上）。`gh run list --workflow=conductor.yml --limit 10`
连续 10 条 failure，时间跨度 2026-07-31 14:37 → 2026-08-01 04:35 UTC。

### 修复

在 `conductor/tick.py` 顶部 stdlib 导入之后插入仓库根到 sys.path（根治所有
`conductor.*` 导入，含 race_mode_handler 内的延迟导入）：

```python
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
```

修复后复测：`python -c "from conductor.tick import race_mode_handler; from conductor.claim_intake import is_claim_pickable_by_impl"` → `import OK: conductor.* resolves`。
`python conductor/tick.py --dry-run` → 正常打印配置后退出，无 ModuleNotFoundError。

### 为什么 W0-4 的 cron 降频没有修好它

W0-4 把 conductor cron 从 `*/5` 降到 `*/15` 并加了 workflow 级 Freeze guard，
但**没有改 tick.py 的导入**——根因不在 cron 频率，而在 sys.path。降频只是让
失败来得慢一点（每 15 分钟失败一次而非每 5 分钟），失败本身仍在。W0-3 才是
真正修根因的卡。

---

## 病链 2：audit.yml 连续 3 次失败

### 根因（root cause）

`audit.yml` 最后一步 `Upload audit artifacts` 引用了一个**无效的 upload-artifact
SHA**（`b4b15b8c...`，GitHub 上不存在该 commit）。Actions 在解析 `uses:` 时向
`actions/upload-artifact` 仓库查该 SHA，返回 422 `No commit found for SHA`，
整个 job 失败。

这是一个**平台引脚漂移**问题：pin 的 SHA 在上游仓库不存在（被 force-push 覆盖或
本来就不属于该仓库），不是审计逻辑本身的问题。审计 Step 1-5 的 Python 逻辑本身
能跑（其 `from conductor.tick import ...` 在 heredoc 内以 cwd=仓库根 运行，
sys.path[0]='' 命中仓库根，导入正常）。

### 证据

- 失败 run：`gh run list --workflow=audit.yml --limit 3` → 3 条 failure
  （2026-07-30 04:35、2026-07-30 09:36、2026-07-31 09:50 UTC）。
- 旧 SHA `b4b15b8c...` → `gh api repos/actions/upload-artifact/commits/b4b15b8c...`
  返回 422 `No commit found for SHA: <旧SHA>`。
- 新 SHA `6f51ac03b9356f520e9adb1b1b7802705f340c2b` → 同 API 返回 200（有效 commit，
  对应 upload-artifact v4.5.0）。

### 修复

PR #167（`fix: 修复 W0 启动的 7 个阻塞问题`，2026-08-01 05:20 UTC 合并）已把
`actions/upload-artifact` 的 SHA 从无效值改为 `6f51ac03...`。3 条 failure run 全部
早于该合并时间，故尚未有 success run 落地。audit.yml cron 为 `3 7 * * *`（每天
07:03 UTC 一次），下一次定时运行（2026-08-02 07:03 UTC）应转绿，满足 AC-1
（`gh run list --workflow=audit.yml --limit 3` 有 success）。

W0-3 在此基础上把 audit.yml Step 2 的内联 heredoc 抽到 `conductor/audit.py`
（可 import / 可单测），audit.yml Step 2 改为薄壳 `python3 -m conductor.audit`。
这是结构性改进（让审计逻辑可被 tests/ 覆盖），**不改变 Step 2 的运行语义**——
逐字搬运，故不影响 AC-1 的转绿路径。

---

## W0-3 另一交付：tick.py freeze 逻辑（AC-4）

W0-4 在 conductor.yml 加了 workflow 级 Freeze guard（先于 tick.py 运行的独立 step）。
W0-3 在 tick.py 的 `main()` 内补了**进程内 freeze 守卫**（defense-in-depth）：

```python
# conductor/tick.py main()，在 zombie_reclaim() 之前
_freeze = POLICY.get("freeze", {}) or {}
if _freeze.get("all"):
    print("FROZEN: policy.freeze.all=true, skipping tick writes (wave frozen)")
    return
```

满足 wave 负证 N2：`freeze.all=true` → tick 退出 0、日志含 `FROZEN`、无写操作
（zombie_reclaim/escalate/unblock_deps 等全部跳过）。无论 tick.py 以何种方式
被调用（cron / workflow_dispatch / 手动 `python conductor/tick.py`），都 honor
freeze。本地复测：`LOOP_POLICY=<freeze.all=true 的 policy> python conductor/tick.py`
→ 只打印 `FROZEN: ...` 一行后退出，无任何 gh 写调用。

## 验证清单

| AC | 命令 | 状态 |
|---|---|---|
| AC-1 | `gh run list --workflow=audit.yml --limit 3` 有 success | 待下一次 cron（07:03 UTC）转绿；SHA 修复已上 main |
| AC-2 | `gh run list --workflow=conductor.yml --limit 10` 连续绿 | 待下一次 cron（*/15）转绿；sys.path 根因已修 |
| AC-3 | `grep -c '根因\|root cause\|traceback' waves/WAVE-00/evidence/root-cause.md` > 0 | 本文件即满足 |
| AC-4 | `grep -i 'frozen\|FROZEN' conductor/tick.py` 命中 > 0 | tick.py main() 内 freeze 守卫已就位 |
