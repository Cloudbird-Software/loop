# WAVE-01 · 入口、真相与边界

> **目标**：程序能启动（CLI）、提示词与实现一致（F7）、测试测真入口；被约束者不再持有约束的写权限；canary C01–C12 首次全部拦截。
> **入口条件**：W0 全绿。
> **波前冻结**：`WAVE_FROZEN=false`（已解）。

## 波次摘要

本波次共 **10 张卡**（9 张 impl + 1 张异构 verify），旨在：
1. 修复 `loopd` CLI，使其能稳定启动并正确派发 16 个动词。
2. 建立契约测试与元测试，确保 CLI 行为稳定。
3. 修复 prompts 文档漂移问题，实现文档与代码的自动比对。
4. 消除 Gate 注入风险，严格控制门禁脚本加载路径。
5. 引入 gitleaks 与 Semgrep 自研规则，增强安全与静态分析。
6. 建立立法机制（Exceptions、Ratchet），实现规则的动态管理。
7. 建立 Pin/Profile 完整性检查，确保供应链安全。
8. 上线 Canary 故障注入测试，验证全部门禁的有效性。
> **人类决策点**：1 个——CHARTER N 段（N16-N32）立法属人类职责（见 W1-7 `human_action`）；其余设计已在操作手册 §5 中定稿。

---

## 卡包发放表（W1）

### W1-1 · loopd CLI 修复（Critical）

```json loop
{
  "schema": 1,
  "id": "W1-1",
  "wave": "WAVE-01",
  "objective": "loopd CLI 修复：main(argv) 派发 + 16 动词统一 _emit JSON + 退出码表",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "loopd/loopd.py",
    "loopd/commands.py",
    "loopd/__init__.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**"
  ],
  "charter": ["G0", "G1"],
  "acceptance": [
    "AC-1: python3 loopd/loopd.py help EXIT=0 且 stdout 为合法 JSON 格式",
    "AC-2: loopd help 输出包含 16 个已知动词列表",
    "AC-3: loopd nonexistent-verb 退出码为 64 且 JSON 含 UNKNOWN_VERB",
    "AC-4: 代码中存在 _emit 方法用于统一 JSON 输出",
    "AC-5: 代码中定义了退出码常量（OK=0, REFUSED=10, GATE=11, UNKNOWN_VERB=64, CRASH=70, ENV=78）"
  ],
  "blocked_by": [],
  "model_hint": "qwen-max",
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

### V1-1 · loopd CLI 异构验证（Critical, Verify）

```json loop
{
  "schema": 1,
  "id": "V1-1",
  "wave": "WAVE-01",
  "objective": "对 W1-1 的 CLI 契约做异构盲验证：正/负用例 subprocess 实测 + 产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W1-1",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/schemas/verdict.json"
  ],
  "forbid_paths": [
    "loopd/**"
  ],
  "charter": ["G4"],
  "acceptance": [
    "AC-1: python3 loopd/loopd.py help 的 stdout 可被 json.tool 解析且含 16 个已知动词",
    "AC-2: python3 loopd/loopd.py nonexistent-verb 退出码=64 且 JSON 含 UNKNOWN_VERB",
    "AC-3: grep -E '_emit|UNKNOWN_VERB *= *64' loopd/loopd.py 命中（代码级）",
    "AC-4: 盲一半：不读 W1-1 过程评论，只据上述命令输出判 PASS/FAIL，VERDICT 附命令原文",
    "AC-5: VERDICT 写为 .loop/schemas/verdict.json，含 card_id=W1-1 + 证据清单"
  ],
  "blocked_by": ["W1-1"],
  "model_hint": "moonshot/kimi-k2.7",
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

### W1-2 · 契约测试 + 元测试

```json loop
{
  "schema": 1,
  "id": "W1-2",
  "wave": "WAVE-01",
  "objective": "契约测试 + 元测试：16 动词 × ≥1 成功用例 + ≥1 拒绝用例 + AST 元测试守护",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "tests/test_cli_contract.py",
    "tests/test_cli_meta.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**"
  ],
  "charter": ["G0"],
  "acceptance": [
    "AC-1: pytest tests/test_cli_contract.py -q 全绿且用例数 ≥ 32",
    "AC-2: 所有用例通过 subprocess 调用 loopd/loopd.py，而非 import",
    "AC-3: python3 tests/test_cli_meta.py EXIT=0",
    "AC-4: 元测试断言 test_cli_contract.py 未直接 import loopd 内部模块"
  ],
  "blocked_by": ["W1-1"],
  "model_hint": "qwen-max",
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

### W1-3 · prompts 真相修复 + Doc Drift 门

```json loop
{
  "schema": 1,
  "id": "W1-3",
  "wave": "WAVE-01",
  "objective": "prompts 真相修复（F7）+ gate_doc_drift.py 三方比对",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "prompts/P0.md",
    "prompts/P1.md",
    "prompts/P2.md",
    "prompts/P3.md",
    "prompts/P4.md",
    "prompts/P5.md",
    "prompts/P6.md",
    "prompts/P7.md",
    "prompts/P8.md",
    "prompts/P9.md",
    "gates/gate_doc_drift.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "gates/run_gates.py",
    "gates/gate_secrets.py",
    "gates/gate_semgrep.py",
    "gates/gate_ratchet.py",
    "gates/gate_pin_integrity.py",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**"
  ],
  "charter": ["G3"],
  "acceptance": [
    "AC-1: grep -ohE 'loopd [a-z-]+' prompts/*.md | sort -u 结果全部存在于 loopd HANDLERS 中",
    "AC-2: python3 gates/gate_doc_drift.py EXIT=0",
    "AC-3: gate_doc_drift.py 实现三方比对（prompts ↔ HANDLERS ↔ argparse）",
    "AC-4: prompts 中不存在 loopd claim / loopd reaper 等不存在的动词"
  ],
  "blocked_by": ["W1-1"],
  "model_hint": "seed-2.1-turbo",
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

### W1-4 · Gate 注入消除

```json loop
{
  "schema": 1,
  "id": "W1-4",
  "wave": "WAVE-01",
  "objective": "gate 注入消除：policy.yml search_dirs 仅留 ${LOOP_ROOT}/gates + run_gates 启动断言",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "policy.yml",
    "gates/run_gates.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "prompts/**",
    "gates/gate_doc_drift.py",
    "gates/gate_secrets.py",
    "gates/gate_semgrep.py",
    "gates/gate_ratchet.py",
    "gates/gate_pin_integrity.py",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**",
    ".gitleaks.toml"
  ],
  "charter": ["G3", "G4"],
  "acceptance": [
    "AC-1: grep -A3 'search_dirs' policy.yml 仅包含 ${LOOP_ROOT}/gates",
    "AC-2: run_gates.py 启动时打印每个 gate 的解析绝对路径和文件 SHA256",
    "AC-3: run_gates.py 包含 .loop-control 存在性断言",
    "AC-4: grep 'search_dirs' policy.yml 零命中产品仓路径",
    "AC-5（负证）: 在 search_dirs 范围外放置假 gate 文件，run_gates 解析必须 FAIL 且拒不加载"
  ],
  "blocked_by": ["W0-2"],
  "model_hint": "qwen-max",
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

### W1-5 · gitleaks 门 + 出站过滤

```json loop
{
  "schema": 1,
  "id": "W1-5",
  "wave": "WAVE-01",
  "objective": "gitleaks gate + 出站过滤：PR Diff 范围扫描 + conductor/outbound.py 集成",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "gates/gate_secrets.py",
    "conductor/outbound.py",
    ".gitleaks.toml"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/gate_doc_drift.py",
    "gates/run_gates.py",
    "gates/gate_semgrep.py",
    "gates/gate_ratchet.py",
    "gates/gate_pin_integrity.py",
    "conductor/audit.py",
    "conductor/tick.py",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**"
  ],
  "charter": ["G3"],
  "acceptance": [
    "AC-1: gates/gate_secrets.py 存在且使用 gitleaks 扫描 PR Diff",
    "AC-2: conductor/outbound.py 存在 scrub_outbound() 函数",
    "AC-3: .gitleaks.toml 存在",
    "AC-4: grep -rn 'secrets.GH_TOKEN\\|secrets.SCRIBE_GH_TOKEN' .github/workflows/ 零命中",
    "AC-5（负证）: 对含 ghp_ 形态 PAT 的构造输入调用 gate_secrets.py 必须返回 FAIL（禁止 fail-open）"
  ],
  "blocked_by": ["W1-4"],
  "model_hint": "qwen-max",
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

### W1-6 · Semgrep 自研规则 v1

```json loop
{
  "schema": 1,
  "id": "W1-6",
  "wave": "WAVE-01",
  "objective": "Semgrep 自研规则 v1：rules/loop/ 9 条规则 + gates/gate_semgrep.py",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "rules/loop/silent-swallow.yml",
    "rules/loop/env-direct-read.yml",
    "rules/loop/cas-bypass.yml",
    "rules/loop/nondeterminism-in-conductor.yml",
    "rules/loop/dispatcher-orphan.yml",
    "rules/loop/mechanism-in-product.yml",
    "rules/loop/lens-missing-strict.yml",
    "rules/loop/subprocess-shell-true.yml",
    "rules/loop/unpinned-uses.yml",
    "gates/gate_semgrep.py"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/gate_doc_drift.py",
    "gates/run_gates.py",
    "gates/gate_secrets.py",
    "gates/gate_ratchet.py",
    "gates/gate_pin_integrity.py",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    ".gitleaks.toml"
  ],
  "charter": ["G3", "G4"],
  "acceptance": [
    "AC-1: rules/loop/ 下存在 9 条 .yml 规则文件",
    "AC-2: gates/gate_semgrep.py 存在且使用 semgrep 执行扫描",
    "AC-3: gate_semgrep.py 使用 --error 模式",
    "AC-4: gate_semgrep.py 不接 Semgrep Cloud 服务（--metrics off）",
    "AC-5（负证）: 塞入 silent-swallow 样本时 gate_semgrep.py 必须 FAIL（--error 生效，禁止漏报）"
  ],
  "blocked_by": ["W1-4"],
  "model_hint": "qwen-max",
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

### W1-7 · 立法包

```json loop
{
  "schema": 1,
  "id": "W1-7",
  "wave": "WAVE-01",
  "objective": "立法机制：.loop/exceptions.yml + gate_ratchet.py（棘轮）；N16-N32 立法交由人类（impl 不改 CHARTER.md）",
    "human_action": "人类在 CHARTER 'Never Doing（N 段）' 章节按需新增并同步登记机器可读索引 N16-N32；impl 仅搭棘轮/exceptions 落地机制",
  "tier": "standard",
  "role": "impl",
  "paths": [
    ".loop/exceptions.yml",
    "gates/gate_ratchet.py"
  ],
  "forbid_paths": [
    ".github/**",
    "policy.yml",
    "prompts/**",
    "gates/gate_doc_drift.py",
    "gates/run_gates.py",
    "gates/gate_secrets.py",
    "gates/gate_semgrep.py",
    "gates/gate_pin_integrity.py",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**",
    ".gitleaks.toml"
  ],
  "charter": ["G3", "G4"],
  "acceptance": [
    "AC-1（负证）: 注入一个较历史更宽松的 gate 配置，gate_ratchet.py 必须 FAIL（棘轮倒转被拦）",
    "AC-2: .loop/exceptions.yml 存在且包含空列表",
    "AC-3: gates/gate_ratchet.py 存在且检测配置变宽松（棘轮倒转）",
    "AC-4: gate_ratchet.py 允许配置变严格（棘轮正转）"
  ],
  "blocked_by": [],
  "model_hint": "qwen-max",
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

### W1-8 · Pin/Profile 过渡与产品仓对齐

```json loop
{
  "schema": 1,
  "id": "W1-8",
  "wave": "WAVE-01",
  "objective": "pin/profile 过渡与产品仓对齐：gate_pin_integrity.py + pins/allowed.json",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "gates/gate_pin_integrity.py",
    "pins/allowed.json",
    "templates/product-x/LOOP.yml"
  ],
  "forbid_paths": [
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/gate_doc_drift.py",
    "gates/run_gates.py",
    "gates/gate_secrets.py",
    "gates/gate_semgrep.py",
    "gates/gate_ratchet.py",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**",
    ".gitleaks.toml"
  ],
  "charter": ["G5"],
  "acceptance": [
    "AC-1: gates/gate_pin_integrity.py 存在",
    "AC-2: pins/allowed.json 存在且为 JSON 格式",
    "AC-3: gate_pin_integrity.py 检查 uses: 的 SHA 与 with: loop-sha 一致性",
    "AC-4: gate_pin_integrity.py 实现 merge-base 祖先校验",
    "AC-5（负证）: 篡改用例（uses: 与 with: loop-sha 不一致 / 非祖先 SHA）时 gate_pin_integrity.py 必须 FAIL"
  ],
  "blocked_by": [],
  "model_hint": "qwen-max",
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

### W1-9 · Canary Corpus v1 上线

```json loop
{
  "schema": 1,
  "id": "W1-9",
  "wave": "WAVE-01",
  "objective": "canary corpus v1 上线：C01-C12 故障样本 + canary.yml 扩展",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "bench/faults/C01-gate-injection.yml",
    "bench/faults/C02-pin-tamper.yml",
    "bench/faults/C03-ratchet-violation.yml",
    "bench/faults/C04-env-leak.yml",
    "bench/faults/C05-doc-drift.yml",
    "bench/faults/C06-cli-contract.yml",
    "bench/faults/C07-silent-swallow.yml",
    "bench/faults/C08-profile-override.yml",
    "bench/faults/C09-fake-green.yml",
    "bench/faults/C10-path-leak.yml",
    "bench/faults/C11-lens-skip.yml",
    "bench/faults/C12-semgrep-bypass.yml",
    ".github/workflows/canary.yml"
  ],
  "forbid_paths": [
    ".github/workflows/pr-ci.yml",
    ".github/workflows/reusable-gates.yml",
    ".github/**",
    "CHARTER.md",
    "policy.yml",
    "prompts/**",
    "gates/**",
    "conductor/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "loopd/**",
    "tests/**",
    "rules/**",
    ".gitleaks.toml"
  ],
  "charter": ["G3", "G4"],
  "acceptance": [
    "AC-1: bench/faults/ 下存在 12 个 C01-C12 .yml 故障样本",
    "AC-2: .github/workflows/canary.yml 存在且包含执行故障样本的步骤",
    "AC-3: canary.yml 执行后结果落盘到 canary/results.json",
    "AC-4: 结果中每个故障样本都有对应的期望拦截器和错误串",
    "AC-5: canary/results.json 满足 length==12 且全部 .intercepted=true（C01-C12 首次全部拦截）"
  ],
  "blocked_by": ["W1-5", "W1-6"],
  "model_hint": "qwen-max",
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

> **关闭判定**：下列"正证全过 + 负证全拦"且 findings/incidents 清零 → **WAVE-01: DONE**；任一 FAIL → NOT DONE。
> **入口先决**：W0 波次关闭判定已通过（病链 48h 连续绿 + smoke 16/16）。

### P. 入口（W0 确实绿）
```bash
gh run list --workflow=conductor.yml --limit 20 --json conclusion --jq "all(.[].conclusion; . == \"success\")"  # → true
bash .loop/smoke.sh            # → 16/16 PASS
```

### Q. 正证（每张卡 = 可运行检查，不是"文件存在"）
```bash
# W1-1/V1-1：CLI 契约（JSON + 16 动词）
python3 loopd/loopd.py help | python3 -m json.tool >/dev/null
test "$(python3 loopd/loopd.py help | grep -coE '\b(next|save|verify|done|drop|reset|ask|evidence|finding|propose|verdict|upstream|retire|status|tick|help)\b')" = 16
# W1-2：契约 + 元测试（subprocess 调用，不 import 内部模块；≥32 用例）
pytest -q tests/test_cli_contract.py
python3 tests/test_cli_meta.py
# W1-3：文档漂移
python3 gates/gate_doc_drift.py
grep -ohE 'loopd [a-z-]+' prompts/*.md | sort -u      # 全部在 HANDLERS
# W1-4：注入收敛
grep -A3 'search_dirs' policy.yml                     # 仅 ${LOOP_ROOT}/gates；零产品仓路径
# W1-7：立法棘轮 + exceptions
python3 gates/gate_ratchet.py
python3 -c "import yaml;assert yaml.safe_load(open('.loop/exceptions.yml')).get('exceptions')==[]"
# W1-8：pin 完整
python3 gates/gate_pin_integrity.py
# W1-9：canary 落盘且 12/12 拦截
jq -e '.results|length==12 and (all(.results[];.intercepted==true))' canary/results.json
```

### R. 负证（故障注入必须被拦，禁止 fail-open）
```bash
# W1-4：search_dirs 外注入假 gate → 必须 FAIL
echo 'print("evil")' >/tmp/fake.py; LOOP_ROOT=/tmp python3 gates/run_gates.py --gate fake && exit 1
# W1-5：内置 PAT 形态凭据 → gitleaks 必须 FAIL
python3 -c "print('ghp_'+'A'*36)" | python3 gates/gate_secrets.py /dev/stdin && exit 1
# W1-6：silent-swallow 样本 → semgrep --error 必须 FAIL
python3 gates/gate_semgrep.py && exit 1
# W1-7：棘轮倒转 → ratchet 必须 FAIL
LOOP_LOOSE=1 python3 gates/gate_ratchet.py && exit 1
# W1-1：未知动词退出码必须 = 64
python3 loopd/loopd.py nonexistent-verb; test "$?" = 64
```

### Z. 关闭（全过才算 DONE）
```bash
# 上述 Q 组全 EXIT=0 且 R 组全 EXIT≠0；且：
gh api "repos/Cloudbird-Software/loop/issues" --jq 'length'   # 无残留 incident；findings 清零
```
判定：Q 全部 EXIT=0 + R 全部 EXIT≠0 + findings 清零 → **WAVE-01: DONE**

---

## Not Doing (主动放弃的项)

- **D1**: 不引入 Semgrep Cloud 服务（仅用本地规则；"外部扫描服务"的 N 段立法由人类在 W1-7 `human_action` 落地）。理由：避免外部依赖、成本和数据隐私问题。
- **D2**: 不修改 loopd 分层架构（CLI/usecases/domain/ports/adapters）。理由：W2 才处理 loop-state 和身份外置，分层重构应与那波次一起做。
- **D3**: 不引入 dispatcher 或自动派卡机制。理由：W3 才引入 dispatcher，当前仍为人工派卡期。
- **D4**: 不升级 gitleaks 到最新主版本。理由：W1-5 仅要求 pin ≥8.30.1，避免不必要的升级风险。
- **D5**: 不在本波直接启用所有新 gate 为 required checks。理由：gitleaks 和 semgrep 先在 gate profile 候选中，经评审后由人类手动提升。

---

## Retro Prev (对上一波次的教训回应)

**W0 教训回顾**：
1.  **sys.path 问题（W0-3）**：conductor/tick.py 的延迟导入因 sys.path 问题失败 10+ 次。
2.  **引脚漂移（W0-3）**：audit.yml 的 upload-artifact SHA 无效，导致 3 次失败。
3.  **环境自检缺失**：agent 启动时环境配置错误导致多次返工。

**W1 针对教训的改进**：
1.  **W1-2 新增契约测试**：通过 subprocess 调用 loopd CLI，从用户角度验证行为，确保 sys.path 等环境问题被覆盖。
2.  **W1-8 新增 Pin 完整性检查**：gate_pin_integrity.py 检查 uses: SHA 的有效性和一致性，防止引脚漂移。
3.  **W1-9 新增 Canary 测试**：每晚自动跑故障注入测试，确保门禁持续有效。

---

## 人类摘要（≤200 字）

**本波次押注**：建立完整的 CLI 契约、文档漂移检测、门禁注入消除、安全扫描和立法机制。这是从"能跑"到"可信"的关键一步。

**最大风险**：单文件 CLI 回归风险；Semgrep 自研规则可能产生误报，需人工评审校准。

**需要人类决策**：1 个——CHARTER "Never Doing（N 段）"新增 N16-N32 属人类立法，impl 不改 CHARTER.md（见 W1-7 `human_action`）；评审确认其后实施。
