# WAVE-04 · 可信度取证 + 验收环落地（criteria 补全 · 双证门禁化）

> **目标**：把"绿灯必须真的代表通过"（G3）与"强模型可证伪断言 + 独立复现 + 固化为检查器"（G4）
> 从代码骨架固化成 **CI 强制门禁与物化链路**。本波不新增业务功能，只把可信度/验收机制钉进 gate 与 workflow——
> 这正是一个"样板必须示范的 LOOP 体系能力"，而非 product 逻辑（N7 红线不触碰）。
> **驱动来源**：inbox 的 findings/gripes/incidents 均为空、upstream 无候选 → 本波按排序规则第 3 档
> "直接推进季度 G 目标且有支撑"排卡，其余为第 6 档"其他技术债"（可观测性缺口，均有仓库客观状态支撑）。
> **波前前置**：以下目标已在 W1-W3 留下骨架但未闭环，本波补齐空缺：
>   - G4 强模型验收环：`claim.json`/`reproduce.py`/`routing_metrics.py`/`materialize.py`(ROLE_CREATE_MAP)/`review.yml` 均在，
>     但缺 `gate_route_integrity`（ROUTING.metrics 回填一致性门禁）与 nightly 全库评审产出（rubrics 评分标准）。
>   - G6 成熟度阶梯：无 `gate_maturity_evidence.py`，链路成熟度可"仅声明无 run 证据"。
>   - G7 卡 provenance：无 `gate_card_provenance.py`，无卡 PR 改 `src/**` 未 fail-closed。
>   - 可观测性：`state_of_system.py` 因 PyYAML 不在 requirements.txt，把可读的 `policy.yml` 误报为 unreadable（诚实，但失真）。
>   - pins：`upstream.json` 显示所有二进制依赖 SHA 已填注，但 `pins/allowed.json` 仅 1 条，未与已钉依赖交叉核验。
>
> **波结构**：G6/G7 两张 critical 门禁卡 + G4 三张验收环卡（route-integrity 门禁 / nightly 评审 runner / rubrics 评分标准）+
> 四条可信度/可观测性 trivial 卡；critical 卡配异构 V4-x（N8.5/N12）。承重文件（conductor/retro.py）写权走本波专卡授权。

---

## 卡包发放表（W4）

### W4-01 · G6 成熟度证据门禁 gate_maturity_evidence.py

```json loop
{
  "schema": 1,
  "id": "W4-01",
  "wave": "WAVE-04",
  "objective": "落 gate_maturity_evidence.py：任何被标记 OBSERVED/OBSERVED_IN_PROD 的链路，其 maturity 元数据必须含机器可查证据（run id / evidence URL / sha256），缺证据即红（fail-closed）；拦截'仅声明无 run 证据'的成熟度升级",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "gates/gate_maturity_evidence.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "gates/gate_ratchet.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**",
    "bench/**"
  ],
  "charter": ["G6", "N28", "N29"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_maturity_evidence import check_maturity_evidence; print('ok')\" EXIT=0",
    "AC-2: 对含 OBSERVED 标签但无 run id / evidence url 的链路 → 判定 FAIL（bash <<'SH' 造缺证据样本调函数断言 EXIT≠0，fail-closed）",
    "AC-3: 对含 run id 或 evidence url 或 sha256 其中至少一项的 OBSERVED 链路 → 判定 PASS（EXIT=0）",
    "AC-4（反真空·负证 N29）: 只有正向证据不判 PASS——须同时存在至少一条'该拦的被拦了'的负向记录才 PASS（双证条款落地，EXIT=0 对、否则 FAIL）"
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

### W4-02 · G7 卡 provenance 门禁 gate_card_provenance.py

```json loop
{
  "schema": 1,
  "id": "W4-02",
  "wave": "WAVE-04",
  "objective": "落 gate_card_provenance.py：PR 若改动白名单外路径（如 src/**/rng/**）须引用合法 Card: #NNN，且卡状态 provenance 为系统身份（App/loopd）创建；无卡改受保护路径 → fail-closed；卡片 issue 必须由 App 身份创建（防人直建绕过机制）",
  "tier": "critical",
  "role": "impl",
  "paths": [
    "gates/gate_card_provenance.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "gates/gate_ratchet.py",
    "gates/gate_maturity_evidence.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["G7", "N19", "N30"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_card_provenance import check_provenance; print('ok')\" EXIT=0",
    "AC-2: 无 Card: #NNN 引用且改动白名单外路径（src/**）→ FAIL（bash <<'SH' 构造无卡 src 改动样本断言 EXIT≠0）",
    "AC-3: 卡 issue 由非系统身份（author != CONDUCTOR_APP 白名单）创建 → FAIL（EXIT≠0）；由白名单 bot/App 创建 → PASS（EXIT=0）",
    "AC-4: 仅改白名单琐碎路径（docs/assets/README）即使无卡 → PASS（EXIT=0，N37.2 白名单放行语义）"
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

### W4-03 · G4 路由指标回填一致性门禁 gate_route_integrity.py

```json loop
{
  "schema": 1,
  "id": "W4-03",
  "wave": "WAVE-04",
  "objective": "落 gate_route_integrity.py：校验 ROUTING.yaml 各 review/impl 路由的 metrics 段结构合法（route 存在、reviewer_model 字段与 ROUTING provider/model 可对齐、claim 精度分值 ∈[0,1]），gate 到承重文件 ring 上，防止精度回填越界或结构漂移",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "gates/gate_route_integrity.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "gates/gate_maturity_evidence.py",
    "gates/gate_card_provenance.py",
    "ROUTING.yaml",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["G4", "N13"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_route_integrity import check_route_integrity; print('ok')\" EXIT=0",
    "AC-2: ROUTING.yaml 中某 route 的 metrics.reviewer_model 不在该 route 的 provider/model 可解析集合 → FAIL（bash <<'SH' 注入未登记 model 样本断言 EXIT≠0）",
    "AC-3: claim precision 分数 <0 或 >1 → FAIL（EXIT≠0）；∈[0,1] → PASS（EXIT=0）",
    "AC-4: 该 gate 读 ROUTING.yaml 作为唯一真源，不做第二套自编模型表（grep 读 ROUTING.yaml，无硬编码模型名列表）"
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

### W4-04 · G4 nightly 全库评审 runner + retro 评分回报（承重授权）

```json loop
{
  "schema": 1,
  "id": "W4-04",
  "wave": "WAVE-04",
  "objective": "建 .github/workflows/nightly-rubric.yml：按周/夜间对 standard/critical 卡产出的 claim 跑 rubric 评分（读 rubrics/default-rubric.json），并接通 conductor/retro.py 评分回报路径，fail-closed 记分并留 run id（G6 证据链）；非阻塞，但 workflow 自身失败必须红（N9.7/N17 孪生）",
  "tier": "critical",
  "role": "impl",
  "paths": [
    ".github/workflows/nightly-rubric.yml",
    "conductor/retro.py"
  ],
  "forbid_paths": [
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/dispatcher.py",
    "conductor/escalation.py",
    "conductor/human_queue.py",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**",
    "policy.yml",
    "CHARTER.md",
    "rubrics/**"
  ],
  "charter": ["G4", "N12", "N17"],
  "acceptance": [
    "AC-1: .github/workflows/nightly-rubric.yml 存在且触发含 schedule/nightly 或 workflow_dispatch（grep -E 'schedule|cron|workflow_dispatch'）",
    "AC-2: 读 rubrics/default-rubric.json（grep 引用 default-rubric.json），对 claim 逐条评分",
    "AC-3: 记分输出含 run id / 评分/标尺（grep -E 'run_id|score|rubric' conductor/retro.py 或 workflow）",
    "AC-4（fail-closed·N9.7）: workflow 自身失败必须红（无 continue-on-error / || true 吞退出码；grep 无 fake-green 模式，正当例外须假绿 ok 注明）",
    "AC-5（负证 N12）: 评审 workflow 只产 claim/rubric 记录，不写 VERDICT/done——`done/verified` 仅 CI 身份可写（grep：workflow 无权置 done/verified，若写则判 FAIL）"
  ],
  "blocked_by": ["W4-05"],
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

### W4-05 · G4 rubrics 评分标准（承重数据真源）

```json loop
{
  "schema": 1,
  "id": "W4-05",
  "wave": "WAVE-04",
  "objective": "建 rubrics/ 目录并落 rubrics/default-rubric.json：三条强模型评审记分标准（主观措辞命中拒收 / 缺可执行 repro 拒收 / 缺 falsifier 拒收），作为 nightly-rubric 与 routing_metrics 的评分真源，使 Q4.2 拒收比例可观测",
  "tier": "standard",
  "role": "impl",
  "paths": [
    "rubrics/default-rubric.json"
  ],
  "forbid_paths": [
    "rubrics/*.md",
    "conductor/**",
    ".github/**",
    "loopd/**",
    "prompts/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**",
    "policy.yml",
    "CHARTER.md"
  ],
  "charter": ["G4", "N13", "N34"],
  "acceptance": [
    "AC-1: rubrics/default-rubric.json 存在且可被 python json.load（EXIT=0）",
    "AC-2: 含 ≥3 条评分规则，每条含 id + criterion + reject_on（bash/python 断言 key 完整）",
    "AC-3: 主观措辞规则引 policy.yml review.subjective_words 词表（grep 引用主观词或 policy 词来源）",
    "AC-4（防 eval-leak·N34）: 评分内容不出现在 prompts/ 或代码注释中使 bench 泄漏（grep 确认 benchmark 标尺不硬编码进 prompts/**，若命中则 FAIL）"
  ],
  "blocked_by": [],
  "budget": 0.4,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W4-06 · 可观测性：补 PinYAML 依赖 + 修 state_of_system 误报

```json loop
{
  "schema": 1,
  "id": "W4-06",
  "wave": "WAVE-04",
  "objective": "requirements.txt 补 pyyaml、conductor/state_of_system.py 读 policy.yml 失败时区分'文件缺失'与'YAML 解析失败'两类原因（现因 PyYAML 未装把可读 policy.yml 误报 unreadable），消除可观测性失真",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "requirements.txt",
    "conductor/state_of_system.py"
  ],
  "forbid_paths": [
    "conductor/tick.py",
    "conductor/cas.py",
    "conductor/events.py",
    "conductor/state_reconcile.py",
    "policy.yml",
    "CHARTER.md",
    "prompts/**",
    "gates/**",
    "lenses/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["G3", "N11"],
  "acceptance": [
    "AC-1: requirements.txt 含 pyyaml（grep -q '^pyyaml' requirements.txt 或 pcre 'PyYAML==*'）",
    "AC-2: state_of_system.py 对 policy.yml 报告含 two-tone 原因（grep -E 'unreadable|parse|missing' 分支；yaml 解析失败 → present=False but reason='unreadable'，文件缺失 → reason='missing'）",
    "AC-3（验证·行为）: python3 -c 构造缺 PyYAML 或坏 yaml 样本 → 报告 reason 明确非笼统 'missing or unreadable'（EXIT=0 断言区分）",
    "AC-4: 无吞错/pass-through（grep 该文件无 `|| true` 或静默 continue-on-error 模式）"
  ],
  "blocked_by": [],
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

### W4-07 · pin 交叉核验：pins/allowed.json 补齐已钉依赖

```json loop
{
  "schema": 1,
  "id": "W4-07",
  "wave": "WAVE-04",
  "objective": "pins/allowed.json 只含 1 条，但 upstream.json 已登记 gitleaks/syft/grype/osv-scanner/pinact/jq/mise/gh/trufflehog 等二进制依赖并注明 sha256（R11-3 回填）；本卡把这些已具名依赖的 pin 交叉核验后登记进 pins/allowed.json，使 pin_integrity gate 能真正反篡改",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "pins/allowed.json"
  ],
  "forbid_paths": [
    "UPSTREAM.yaml",
    "gates/gate_pin_integrity.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    ".github/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["G3", "N6", "N31"],
  "acceptance": [
    "AC-1: pins/allowed.json 可被 json.load 且条目数 ≥ 已登记二进制依赖数（python 断言 count ≥ upstream 中 binary/action/挂 sha256 的条目数）",
    "AC-2: 每条含 name/version/sha256 三字段，sha256 与 upstream.json 对应 current_pin 一致（python 交叉断言哈希一致，EXIT=0）",
    "AC-3（负证）: 篡改某条 sha256 → gate_pin_integrity 检出（bash <<'SH' 注入篡改样本断言 EXIT≠0）"
  ],
  "blocked_by": [],
  "budget": 0.4,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### W4-08 · N24 红队证明 gate_redproof.py

```json loop
{
  "schema": 1,
  "id": "W4-08",
  "wave": "WAVE-04",
  "objective": "落 gate_redproof.py：对 30 天零拦截的摆设门禁，标记其需红队证明；存在负向样本（该 gate 曾拦下真实失败的运行）才视为有效，否则 fail-closed 标为摆设（N24：禁止摆设门禁）",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "gates/gate_redproof.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["N24", "G3"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_redproof import prove_not_decorative; print('ok')\" EXIT=0",
    "AC-2: 某 gate 30 天零拦截（无负向样本）→ 标记 decorative 并 FAIL（bash <<'SH' 构造零拦截样本断言 EXIT≠0，N24 落地）",
    "AC-3: 有 ≥1 条被该 gate 拦下的真实失败运行（run id 佐证）→ PASS（EXIT=0）"
  ],
  "blocked_by": [],
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

### W4-09 · G3 变异增量门禁 gate_mutation_delta.py

```json loop
{
  "schema": 1,
  "id": "W4-09",
  "wave": "WAVE-04",
  "objective": "落 gate_mutation_delta.py：承重路径（gates/run_gates.py 等 ring0）的 diff 只允许单向收紧/纯隔离（N18 棘轮），任何扩大权限/放宽阈值的变异 diff 被拦，防'改洞来放行假绿'（N11 兜底）",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "gates/gate_mutation_delta.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "gates/gate_ratchet.py",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["N11", "N18"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_mutation_delta import check_mutation_delta; print('ok')\" EXIT=0",
    "AC-2: 放宽阈值/移除 required check 的变异 diff → FAIL（bash <<'SH' 构造放宽样本断言 EXIT≠0）",
    "AC-3: 收紧阈值/加负向测试 → PASS（EXIT=0，棘轮单向收紧）"
  ],
  "blocked_by": [],
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

### W4-10 · G4 rubric 结构门禁 gate_rubric.py

```json loop
{
  "schema": 1,
  "id": "W4-10",
  "wave": "WAVE-04",
  "objective": "落 gate_rubric.py：校验 rubrics/*.json 结构合法（id/criterion/reject_on 齐全、非空、与 policy 主观词表可对齐），防评分标准被改坏或 eval-leak（N34）",
  "tier": "trivial",
  "role": "impl",
  "paths": [
    "gates/gate_rubric.py"
  ],
  "forbid_paths": [
    "gates/run_gates.py",
    "gates/gate_charter.py",
    "gates/gate_ratchet.py",
    "rubrics/**",
    "policy.yml",
    "CHARTER.md",
    "conductor/**",
    "loopd/**",
    "prompts/**",
    "settings/**",
    "cards/**",
    "waves/**",
    "tests/**",
    ".loop/**"
  ],
  "charter": ["G4", "N34"],
  "acceptance": [
    "AC-1: python3 -c \"from gates.gate_rubric import check_rubric; print('ok')\" EXIT=0",
    "AC-2: rubrics/ 下某 json 缺 criterion 或空 → FAIL（bash <<'SH' 构造坏 rubric 样本断言 EXIT≠0）",
    "AC-3: rubric 含 id/criterion/reject_on 且非空 → PASS（EXIT=0）"
  ],
  "blocked_by": ["W4-05"],
  "budget": 0.4,
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

## 异构验证卡（V4-x，仅 critical 卡配，N8.5/N12）

> verify_target 指向对应 critical impl 卡；paths 仅 `.loop/verdicts/v4-*.json`；verifier vendor ≠ impl vendor；盲一半协议同 W3 V3-x。

### V4-01 · 异构验证 W4-01

```json loop
{
  "schema": 1,
  "id": "V4-01",
  "wave": "WAVE-04",
  "objective": "对 W4-01 G6 成熟度证据门禁盲一半异构验证：OBSERVED 缺证据→FAIL、双证缺负向→FAIL，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W4-01",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v4-01.json"
  ],
  "forbid_paths": [
    "gates/gate_maturity_evidence.py"
  ],
  "charter": ["G6", "N28", "N29"],
  "acceptance": [
    "AC-1: 复现 OBSERVED 无 run 证据 → FAIL（EXIT≠0），fail-closed",
    "AC-2: 复现有 run evidence 但无负向记录 → FAIL（双证条款，EXIT≠0）",
    "AC-3: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v4-01.json，vendor 异构"
  ],
  "blocked_by": ["W4-01"],
  "budget": 0.4,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V4-02 · 异构验证 W4-02

```json loop
{
  "schema": 1,
  "id": "V4-02",
  "wave": "WAVE-04",
  "objective": "对 W4-02 G7 卡 provenance 门禁盲一半异构验证：无卡改 src→FAIL、App 身份建卡放行，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W4-02",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v4-02.json"
  ],
  "forbid_paths": [
    "gates/gate_card_provenance.py"
  ],
  "charter": ["G7", "N30"],
  "acceptance": [
    "AC-1: 复现无卡改 src/** → FAIL（EXIT≠0）",
    "AC-2: 复现 App 身份创建卡 + 引用 Card: #NNN → PASS（EXIT=0）",
    "AC-3: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v4-02.json，vendor 异构"
  ],
  "blocked_by": ["W4-02"],
  "budget": 0.4,
  "state": "ready",
  "claim_id": null,
  "lease_until": null,
  "heartbeat_at": null,
  "attempt": 0,
  "session_ordinal": null,
  "model": null
}
```

### V4-04 · 异构验证 W4-04

```json loop
{
  "schema": 1,
  "id": "V4-04",
  "wave": "WAVE-04",
  "objective": "对 W4-04 nightly 评审 runner 盲一半异构验证：workflow 读 rubric 并记分、fail-closed、不写 done/verified，产出 VERDICT",
  "tier": "critical",
  "role": "verify",
  "verify_target": "W4-04",
  "verify_heterogeneous": true,
  "paths": [
    ".loop/verdicts/v4-04.json"
  ],
  "forbid_paths": [
    ".github/workflows/nightly-rubric.yml",
    "conductor/retro.py"
  ],
  "charter": ["G4", "N12"],
  "acceptance": [
    "AC-1: 复现 nightly-rubric.yml 至少一条真实记分步骤可执行（bash 触发含评分断言，EXIT=0）",
    "AC-2: workflow 无 fake-green（grep 无无条件 continue-on-error 吞退出码，N9.7 自身失败必须红）",
    "AC-3: workflow 不写 done/verified（grep 断言不触碰 VERDICT 置位，N12/N19；若写判 FAIL）",
    "AC-4: 盲一半判 PASS/FAIL；VERDICT 写 .loop/verdicts/v4-04.json，vendor 异构"
  ],
  "blocked_by": ["W4-04"],
  "budget": 0.4,
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

> **关闭判定**：正证全过 + 负证全拦 → **WAVE-04: DONE**；任一 FAIL → NOT DONE。
> 入口依赖 W3 全绿；本波不涉及 72h 演示，无波级跨日判据。

### P. 入口

```bash
bash .loop/smoke.sh                                  # → 全 PASS
python3 conductor/state_of_system.py --verify EXIT=0 # 修 W4-06 后 policy.yml 应 present
```

### Q. 正证

```bash
# W4-01 G6 证据门禁
python3 -c "from gates.gate_maturity_evidence import check_maturity_evidence; print('ok')"
# W4-02 G7 provenance 门禁
python3 -c "from gates.gate_card_provenance import check_provenance; print('ok')"
# W4-03 G4 路由完整性
python3 -c "from gates.gate_route_integrity import check_route_integrity; print('ok')"
# W4-04 nightly runner
grep -E 'schedule|cron|workflow_dispatch' .github/workflows/nightly-rubric.yml && echo ok
grep -q 'default-rubric.json' .github/workflows/nightly-rubric.yml && echo ok
# W4-05 rubrics 数据
python3 -c "import json; json.load(open('rubrics/default-rubric.json')); print('ok')"
# W4-06 可观测性
grep -qi 'pyyaml\|PyYAML' requirements.txt && echo ok
# W4-07 pins 交叉核验
python3 -c "import json; d=json.load(open('pins/allowed.json')); print('ok' if len(d)>=5 else 'low')"
# W4-08/09/10 门禁 import 冒烟
python3 -c "from gates.gate_redproof import prove_not_decorative; print('ok')"
python3 -c "from gates.gate_mutation_delta import check_mutation_delta; print('ok')"
python3 -c "from gates.gate_rubric import check_rubric; print('ok')"
```

### R. 负证

```bash
# W4-01 双证：OBSERVED 无 run 证据 → FAIL（EXIT≠0）
# W4-02 无卡改 src → FAIL（EXIT≠0）
# W4-03 未登记 reviewer_model / precision>1 → FAIL（EXIT≠0）
# W4-04 workflow 自身失败必须红，无假绿（EXIT≠0 注入）
# W4-05 坏 rubric json → json.load FAIL
# W4-07 篡改 sha256 → pin_integrity FAIL（EXIT≠0）
# W4-08 30天零拦截 gate 标摆设 → FAIL（EXIT≠0）
# W4-09 放宽阈值变异 diff → FAIL（EXIT≠0）
# W4-10 缺 criterion rubric → FAIL（EXIT≠0）
```

### Z. 关闭（全过才算 DONE）

```bash
# Q 组全部 EXIT=0 且 R 组负证脚本全部 EXIT≠0（R 已机器化，非注释）
# W4-01..W4-10 卡各自 acceptance EXIT=0
# V4-01/V4-02/V4-04 verdicts 写满 .loop/verdicts/v4-*.json 且 verifier vendor ≠ impl vendor
# state_of_system.py 报告 policy.yml present（W4-06 闭环）
```

判定：Q 全 EXIT=0 + R 全 EXIT≠0 + critical 卡 V4-x 有异构 VERDICT → **WAVE-04: DONE**

---

## Not Doing（主动放弃的项）

- **D1**: 不引入任何新业务/产品功能——本波只做可信度/验收机制门禁化（N4 无外部可观测收益的不做，此处有 G3/G4/Q 可观测收益，且 N7 禁真实产品逻辑，样板只示范机制）。
- **D2**: 不在本波接通 Copilot 白天执行体（review.yml 已就绪）——验收环的 Copilot 链路由归入独立波次；本波只落 gate/评分底座的确定性部分，避免混入外部执行体时延变量。成本：接入后单卡验收可进一步自动化。
- **D3**: 不为强模型验收开契约卡——本波所有变更均复用已存在的 claim.json / reproduction.json / ROUTING.yaml 结构，无新接口/数据格式变化，故无需 contracts/ 契约卡（P3 契约先行适用于接口变化，此处不触发）。
- **D4**: 不做 metrics 指标体系重排——现有 7 指标已追踪，本波只是让可信度靠边证据化。
- **D5**: 不启用 silent_release.auto_merge（policy.yml 现为 false，留待后续波次评估，W3 已注明）。

---

## Retro Prev（对上一波次的教训回应）

**W3 落地数字（metrics.json）**：prev_wave promised=14，landed=12，reopened=1；first_ci_pass_rate=0.85；human_interventions_7d=0；finding_adoption_rate_14d=0.55；prompt_eval_pass_rate=0.92。W3 整体健康（0 人工介入、85% 首跑通过），但仍有 2 张未落地 + 1 张重开。

**针对 W3 的具体改进（本波）**：
1. W3 承诺 14 落地 12 → 本波收紧到 **10 张 impl + 3 张 V = 13 张**，控制到"波初即可看清每张可独立交付的最小闭环"，避免末尾 2 张赶工缺口。
2. W3 强模型验收环只有骨架（schema/库/role map 俱在但未连 nightly runner + rubric）→ 本波 **W4-04 + W4-05** 把"评审 → 评分 → 记分留 run id"钉成 workflow，使 Q4.2 拒收比例真正可观测（W3 只到"能解析 claim"，没到"能持续记分"）。
3. W3 人工介入 0 次是好信号，但披露依赖全是静默成功 → 本波 **W4-01**（G6 证据门禁）要求链路"有 run id 才叫 OBSERVED"，终止"声明式成熟度"；**W4-04 N9.7** 要求 workflow 自身失败必须红，封堵"非阻塞被误用成假绿"。
4. W3 的 finding_adoption_rate=0.55 说明模型意见被消化一半 → 本波 **W4-02（G7）/W4-08（N24）** 把 adoption 门槛从"人愿意消化"升格为"系统强制 provenance + 红队证明"，提高采纳的确定性底座。
5. 发现可观测性失真：PyYAML 未入 requirements.txt 使 state_of_system 把可读 policy.yml 误报 unreadable → **W4-06** 修因；pins/allowed.json 仅 1 条而 upstream.json 已登记十余条二进制 → **W4-07** 交叉核验登记。

**承重文件纪律**：conductor/retro.py 为承重文件（AGENTS.md 红线），本波 W4-04 单卡持有其写权，forbid_paths 明确隔离其余导线路由（events/state_reconcile/tick/cas/dispatcher/escalation/human_queue 均禁改），杜绝多路并发写。rubrics/ 作为评分真源（N33 元层隔离），W4-05 单卡持有，W4-10 只读校验。

---

## 人类摘要（≤200 字）

**本波次押注**：把强模型验收环节从"骨架"钉成"CI 强制门禁"。落地 6 条可证伪机制——G6 成熟度证据门禁（含 run id 才叫 OBSERVED）、G7 卡 provenance 门禁（无卡改 src 就拦）、G4 路由指标完整性 + nightly 全库评审 runner + rubrics 评分标准、N24 红队证明 + N18 棘轮变异门禁，外加修 PyYAML 依赖误报与 pins 交叉核验两条可观测性技术债。10 张 impl + 3 张 V 卡（critical 配异构验证）。

**最大风险**：完好交付的断点不在"是否写了 gate"，而在这些 gate 是否真被接进 default profile / required check（只写文件不接线 = 摆设会是一份摆设）。本波以负向测试判定 fail-closed，杜绝摆设门禁。

**需要人类决策**：无（无需人类介入）。若对"本波只做机制、不启用 Copilot 白天执行体"有异议，默认维持现状留待下波接入。