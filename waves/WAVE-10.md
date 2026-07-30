# WAVE-10 — 止血：让绿灯重新代表"通过"

> 本波次唯一目的：把"名义 8 道门禁、实际拦截力 = 0"这件事彻底终结。在 WAVE-10 全绿之前，其余波次一律不得开工——因为在假绿的地基上做任何验证都不可信。

**来源**：`docs/审查裁决-2026-07-30.md` 中裁定为 TRUE 的 F-A / F-D / P1-1，以及本次审查新发现的 `settings/main-protection.json` 缺失 `required_status_checks` 缺陷。

**已在本 PR 中先行完成（不再单开卡）**：

- 新增 `.github/workflows/pr-ci.yml`（loop 仓史上第一个 `pull_request` 触发的门禁）
- 六处假绿全部改为显式失败，正当例外强制写 `fake-green-ok: <理由>`
- 五个 workflow 补 `concurrency`
- `tick.py` 三处 `eval()` 清零；非测试文件 `utcnow()` 全部改 aware UTC
- `gate_charter` / `gate_diffsize` / `gate_license` / `gate_upstream` 四个 skeleton 全部实现
- `canary.yml` 过时注释（"用 admin PAT 绕过保护"）改为事实

---

## 本波次的检查方法（Wave-level Gate）

波次负责人（conductor）在关闭本 Wave 父 issue 前，必须逐条粘贴以下命令的**真实输出**：

1. **假绿为零**：在 loop 与 product-x 两仓分别跑
   `python3 -c "..."`（即 `pr-ci.yml` 的 `no-fake-green` job 逻辑），两仓均输出 `violations: 0`。
2. **门禁真的会红**：在 loop 开一个故意违反的 PR（例如新增一行 `foo || true` 且不写 `fake-green-ok`），
   截图/粘贴 GitHub 上该 PR 的 `no-fake-green` **红色** check 结论。这是"负向验证"，只看绿是无效的。
3. **未执行即失败**：在 product-x 临时删除 `.loop/gates/gate_paths.py` 开 PR，
   CI 必须**红**且日志出现 `GATE_NOT_EXECUTED: gate_paths`，而不是 `SKIP`。
4. **单一真源**：`gh issue list -R Cloudbird-Software/product-x --search "V-009"` 与
   `git -C loop log -1 --stat cards/` 一致——`cards/` 已冻结且 README 指向 product-x issues。
5. **settings 往返一致**：`python3 gates/gate_settings_roundtrip.py` 输出 `OK`，
   且 `gh api repos/Cloudbird-Software/product-x/rules/branches/main` 的 check 集合与文件逐字相等。

任一条不成立，Wave-10 不得关闭，后续波次不得启动。

---

## 卡片

```json loop
{
  "schema": 1,
  "id": "R10-1",
  "objective": "loop 仓 required checks 接线 + 门禁负向测试",
  "title": "把 pr-ci.yml 的 5 个 job 接成 loop 仓 required checks，并为每个 check 写负向测试",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N11"],
  "paths": ["settings/loop-main-protection.json", "tests/test_pr_ci_negative.py"],
  "forbid_paths": [".github/workflows/pr-ci.yml"],
  "blocked_by": null,
  "acceptance": [
    "新增 settings/loop-main-protection.json，逐字描述 loop 仓 main 分支应有的 ruleset，required_status_checks 至少含 test / lint / no-fake-green / actions-pinned / schemas 五项，bypass_actors 为空数组",
    "新增 tests/test_pr_ci_negative.py：对 no-fake-green 与 actions-pinned 两个扫描器各构造至少一个『必须被判定为违规』的输入，断言其返回非零；再各构造一个合规输入断言返回零",
    "负向测试必须直接调用扫描逻辑本体（从 pr-ci.yml 中抽出为 conductor/scan_workflows.py 亦可，但本卡不改 pr-ci.yml，改由 R11-1 收口），不得复制粘贴一份平行实现",
    "pytest -q 全绿且总数比当前基线增加 ≥4",
    "在 PR 描述中粘贴：故意引入一处未标注的 `|| true` 后 no-fake-green 变红的 CI 链接"
  ],
  "verify": "reviewer 必须亲自 checkout 该 PR，本地故意破坏一次并确认扫描器返回非零；只跑绿色路径不算验证",
  "human_action": "合并后由人类在 GitHub → Settings → Rules 中把这 5 个 check 设为 required（见 HUMAN-TODO.md 第 6 条）"
}
```

```json loop
{
  "schema": 1,
  "id": "R10-2",
  "objective": "修复 product-x 门禁路径 bug 并补 merge_group",
  "title": "product-x ci.yml：探测 .loop/gates/、未执行即失败、补 merge_group 触发、钉 action SHA、push 加分支过滤",
  "repo": "product-x",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N11"],
  "paths": ["product-x/.github/workflows/ci.yml"],
  "forbid_paths": ["product-x/.loop/gates/**"],
  "blocked_by": "R10-3",
  "acceptance": [
    "四个 gate job 的 `if gates/… elif ../gates/… else SKIP; ec=0` 模式全部删除，改为调用 R10-3 交付的统一入口 gates/run_gates.py（经 .loop/gates/ 解析）",
    "任何 gate 未能被定位或未能执行时，job 必须以非零退出，日志打印 `GATE_NOT_EXECUTED: <gate 名>`；SKIP 语义从 CI 中彻底消失",
    "先取证再动手：跑 `gh api repos/Cloudbird-Software/product-x/contents/.github/workflows/ci.yml --jq .content | base64 -d | grep -n merge_group`。若缺失则补 `on: merge_group:`（缺失会导致 merge queue 里 required check 永不上报，即 F-002 的成因）；若已存在则在 PR 描述中给出证据并关闭 product-x #89/#90。**不得仅凭 issue 上的 status-done 标签下结论**——本次审查的最大教训就是状态字段不可采信",
    "`on: push:` 补 `branches: [main]`，避免任意分支推送触发全量 CI",
    "8 处 `actions/checkout@v4` 等未钉版本的 action 全部改为 40 位 commit SHA，并在行尾注释 `# vX.Y.Z`（与 loop 仓 11 处现有写法一致）",
    "job 名与 GitHub 上线上 ruleset 实际强制的 6 个 check（lint/test/verify/contract/paths-lease/verdict-binding）逐字对齐，不得新增/改名任何已被强制的 check 名，除非同一 PR 里同时更新 settings 快照（见 R10-4）",
    "在 PR 描述中粘贴：临时删除 .loop/gates/gate_paths.py 后 CI 变红且日志含 GATE_NOT_EXECUTED 的证据"
  ],
  "verify": "reviewer 必须在 PR 分支上真的删掉一个 gate 文件并观察 CI 变红。仅确认『改完还是绿』不构成验证——这正是本 bug 潜伏至今的原因",
  "note": "复现结论纠正了专家：.loop/gates/ 并非空目录，里面有可工作的 gate_paths.py(94行)/gate_verdict.py(159行)。这是路径不匹配 bug，不是缺代码。根因是『没有任何机制报告门禁被 SKIP』，所以本卡的承重验收项是第 2 条而非第 1 条"
}
```

```json loop
{
  "schema": 1,
  "id": "R10-3",
  "objective": "gate 统一入口：未执行等价于失败",
  "title": "实现 gates/run_gates.py —— 单一 gate 运行器，缺席、崩溃、超时一律判失败",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G3", "N11"],
  "paths": ["gates/run_gates.py", "tests/test_run_gates.py"],
  "blocked_by": null,
  "acceptance": [
    "run_gates.py 接受 `--profile <name>` 与 `--gates a,b,c`，从 policy.yml 的 gates.profile 读取该 profile 应当执行的 gate 全集",
    "对 profile 中声明但在文件系统上找不到的 gate，打印 `GATE_NOT_EXECUTED: <名>` 并以退出码 2 结束；对执行中抛异常的 gate 打印 `GATE_ERRORED` 并退出 3；仅当全部 gate 均实际执行且返回 0 时才退出 0",
    "gate 解析顺序显式声明并有测试覆盖：`gates/` → `.loop/gates/` → `$LOOP_ROOT/gates/`；三处都找不到才算缺席",
    "每个 gate 有独立超时（默认 120s，可由 policy.yml 覆盖），超时按失败处理",
    "输出机器可读摘要 JSON 到 `--out`，含每个 gate 的 name/status/exit_code/duration_ms，供 evidence 收集",
    "tests/test_run_gates.py 覆盖：全通过、缺席、崩溃、超时四种路径，各断言退出码",
    "policy.yml 中新增/明确 gates.profile 的 gate 全集清单（若已存在则以其为准，不得偷偷缩小集合）"
  ],
  "verify": "在 loop 与 product-x 各跑一次 run_gates.py，两边都必须能定位到全部 gate；再人为改名一个 gate 文件，确认退出码为 2"
}
```

```json loop
{
  "schema": 1,
  "id": "R10-4",
  "objective": "settings 快照与线上 ruleset 逐字对齐",
  "title": "修复 main-protection.json 缺失 required_status_checks（本次审查新发现的高危缺陷）",
  "repo": "loop",
  "state": "ready",
  "tier": "critical",
  "role": "impl",
  "charter": ["G3", "N5"],
  "paths": ["settings/main-protection.json", "gates/gate_settings_roundtrip.py"],
  "blocked_by": null,
  "acceptance": [
    "settings/main-protection.json 补齐 `required_status_checks` 规则，其 required_status_checks 数组与线上 ruleset(id 19949520) 实际强制的集合逐字相等；文件中原先那份列了 8 个 check 的过时片段（含 diffsize-budget/license-whitelist/minage-cooldown/upstream-registry 四个 ci.yml 里根本不存在的 job）必须删除或改为与线上一致",
    "新增 gates/gate_settings_roundtrip.py：拉取线上 ruleset，与仓库快照做归一化比对（忽略 id/created_at 等服务端字段），不一致则非零退出并逐字段打印 diff",
    "该 gate 接入 drift.yml 的定时漂移检测，替换现有会产生永久噪声的比对逻辑",
    "PR 描述中必须写明：为什么修这个文件是紧急的——policy.yml 一旦实现 apply，会以人类批准的名义把线上仅有的 6 道真门禁删光。这是本次审查中专家与复现者双双漏掉的一条",
    "严格遵守 N5：本卡只做检测与开 Incident，绝不写任何自动 apply/修正 ruleset 的代码路径"
  ],
  "verify": "reviewer 必须独立执行 `gh api repos/Cloudbird-Software/product-x/rules/branches/main` 并把返回的 check 集合与 PR 中的文件逐字比对，不得采信 PR 描述"
}
```

```json loop
{
  "schema": 1,
  "id": "R10-5",
  "objective": "单一工单真源：冻结 cards/",
  "title": "终结双真源——cards/ 转为只读归档，product-x issues 成为唯一工单真源",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G0", "G3"],
  "paths": ["cards/", "prompts/P-continue.md"],
  "blocked_by": null,
  "acceptance": [
    "cards/README.md 顶部加醒目冻结声明：本目录自 <合并日期> 起为只读历史归档，任何状态字段不再具有权威性；新工单一律走 product-x issues 的 `json loop` 块",
    "cards/*.md 中所有 `status:` / `ready:` 字段统一改写为 `status: archived`，或在每个文件头部插入 `> ARCHIVED — 权威状态见 product-x issue #<n>` 的回指行；V-009 必须显式记录其真源冲突（loop 侧 done vs product-x #99 open/pending）及最终裁决",
    "cards/INDEX.md 增加一列 `product_x_issue`，把每张卡映射到 product-x 的实际 issue 号；无法映射的卡明确标注 `ORPHAN` 并在 PR 描述中列出",
    "prompts/P-continue.md 的接单来源从 cards/ 改为 product-x issues（走 tick.py/loopd 的 CAS 领卡），不再有任何『AI 手改 markdown 字段推进状态机』的指令",
    "P-continue.md 中允许『一次会话先 impl 再 verify』的措辞删除，改为显式禁止（对应 N12：不允许实现方自证）",
    "grep -rn 'cards/' 在 conductor/ 与 .github/workflows/ 下命中数为 0（除归档说明外）"
  ],
  "verify": "reviewer 抽查任意三张 cards/*.md，确认其状态字段已失效化；再确认 P-continue.md 走一遍，AI 不可能再通过改 markdown 推进状态机",
  "note": "loop 仓 cards/README.md 与 WORKFLOW.md 本就把 cards/ 标为『暂行期』，设计意图即切到 product-x issues。本卡只是把从未发生的切换真正执行掉"
}
```

```json loop
{
  "schema": 1,
  "id": "R10-6",
  "objective": "Incident 幂等与噪声治理",
  "title": "canary/drift 的 Incident 去重：同一根因只留一张开着的单",
  "repo": "loop",
  "state": "ready",
  "tier": "standard",
  "role": "impl",
  "charter": ["G1", "G3"],
  "paths": ["conductor/drift_check.py", ".loop/scripts/canary-survival.sh"],
  "blocked_by": "R10-4",
  "acceptance": [
    "Incident 开单前先按 `fingerprint`（根因哈希，而非时间戳）查重；已有 open 的同指纹 Incident 时改为追加评论并更新计数，不再新开",
    "Incident 标题含稳定指纹前缀，便于人工与脚本聚合",
    "为存量噪声提供一次性收敛脚本（放在 .loop/scripts/ 下，本卡 paths 已覆盖），能按指纹批量关闭历史重复 Incident 并在最新一张上汇总",
    "关闭时写明关闭理由与指纹，保留每个指纹最新 1 张作为证据",
    "loop 仓 open 的 canary Incident 数从当前的数十张收敛到 ≤5 张，且每张对应一个不同指纹"
  ],
  "verify": "跑两次漂移检测，确认第二次不产生新 issue 而是在原单追加评论"
}
```
