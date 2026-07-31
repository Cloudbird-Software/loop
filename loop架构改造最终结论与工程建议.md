# loop 控制面架构改造：最终结论与工程建议

> **文档性质**：终裁版。结论部分（Part I）回答"架构该怎么改"；工程建议部分（Part II）给出波次、波次内分工与客观不可证伪的完工验证方法。
> **事实基础**：五份设计文档（规格书 / 专家意见 / 工具建议A / 工具建议B / 落地方案）+ 七批次仓库实测（V-001…V-710，覆盖 loop 仓 HEAD `04181b2`→`4af34e6` 与产品仓 product-x HEAD `fb7a09c`，勘测时间 2026-07-31）+ 公开仓原文复核（reusable-gates.yml / policy.yml / upgrade_ring.py / gate_paths.py / gate_conformance.py / gate_verdict.py / 薄壳与 LOOP.yml 逐字内容）+ GitHub 平台能力核查（2026-07-31 官方文档快照）。
> **证据标准**：本文每一项"实测确认"都可由第一批次的验证命令在同一 HEAD 上复跑复核。

---

# Part I · 最终结论

## 1. 总裁决（一页版）

**五份文档的方向全部正确，但它们描述的仓库已经不存在了。** 实测表明：loop 仓在创建后 72 小时内（2026-07-29 创建）已经把专家意见和落地方案中约三分之一的"平台层建议"提前实现完毕——ruleset（bypass 列表为空）、merge queue（SQUASH/ALLGREEN）、6 项 required checks、64 条 `uses:` 全部钉 40 位 SHA、requirements.txt 哈希钉版、merge_group 触发、canary 链、drift 检测、ROUTING.yaml 静态路由、policy 双 App、CodeQL SARIF 上传、bench 四指标回放包、契约目录雏形、gate_conformance 六项检查。**这套控制面的"壳"远比文档假设的完整。**

**但同一组实测也证明了另一件事：这套系统迄今为止没有产出过任何一个机器驱动的完整证据工件。** 全仓 83 个 issue + 全部评论中，`json verdict` / `json claim` / `json finding` / `json reproduction` 四种块的出现次数是 **0**；产品仓 12 张已关闭卡全部由人类账号（randypanding）创建并关闭，`state=done`、`lease_until=null`、`model=null`；loopd CLI 在最新 HEAD 上仍然 `NameError: name 'LOOP' is not defined`（BROKEN-01 未愈）；template-sync 与 upgrade 两条链**从未运行过一次**；audit 链运行 3 次**全部失败**；conductor（tick）最近 4 次运行**全部失败**。

由此得到本次终裁的三句话：

1. **架构不需要再"加机制"，需要先把已有机制跑通一次。** 当前最大的风险不是缺某个 gate，而是"机制密度"已经远超"运行证据密度"——每加一个新机制，假绿表面积就扩大一分。
2. **专家的四条根因（R1 状态存于 issue / R2 被约束者持有约束写权限 / R3 断言即证据 / R4 记账自动化而干活未自动化）全部实测成立，且多了一个文档里没有的第五条：门禁系统的 fail-open 设计**——card 作用域的门禁（paths/verdict/diffsize 等）在无卡 PR 上一律 SKIP=放行，"卡 provenance"本身没有门禁把守。这是当前代码里最大的系统性洞。
3. **落地文档的"信号保真度层"（red-first proof、holdout+RHG、故障注入门禁召回率）是正确的改造中心；工具文档的确定性工具按"秘密 > 机制不变量 > 抑制控制 > 供应链 > 变异"的次序接入；AI 优化层（Meta-Harness/SkillOpt/ACRouter/Rubric）全部缓议**，只提前采纳其中两件：Pass^k 作为 e2e 就绪判据、schema 单一事实源 + 生成端约束（因为卡块方言漂移已经在实测中出现）。**BROKEN-02（Planner 自动调度）按落地文档的裁决：现在不修，它是仅剩的人类节流阀。**

---

## 2. 实测事实对账

### 2.1 链路真实成熟度重估

按专家文档的成熟度阶梯（DESIGNED → IMPLEMENTED → TESTED → EXERCISED → OBSERVED → OWNED），以运行证据（V-401 等）为准重估：

| 链路 | 规格书声称 | 实测证据 | 真实成熟度 |
|---|---|---|---|
| CHAIN-01 template-sync | ACTIVE；可运行 | **从未运行**（`gh run list` 返回 `[]`）；代码完整（OPEN_PR_ONLY 硬编码、shadow 检测、Incident 兜底齐全） | IMPLEMENTED |
| CHAIN-02 产品仓 CI 门禁 | ACTIVE | 产品仓薄壳就位且三方 pin 一致（V-703/704）；loop 仓侧 6 项 required checks 真实拦截中 | EXERCISED（loop 仓侧）/ IMPLEMENTED（产品侧） |
| CHAIN-03 升级环 | ACTIVE；已接线 | **从未运行**；代码确认无自动合并（开 PR 制 + 回退 PR 制）；bench 四指标回放包真实存在 | IMPLEMENTED |
| CHAIN-04 Planner→Materializer | PARTIAL | Planner 无调度（V-211）；materializer.yml 在 loop 仓就位（dry_run 默认 true）；48h silent dispatch 发送端在 tick.py:719，接收端在 product-x | IMPLEMENTED |
| CHAIN-05 Agent 领卡状态机 | **BROKEN** | **实测确认 BROKEN**：最新 HEAD 上 `python3 loopd/loopd.py help` 仍 NameError（V-105）；16 动词注册齐全但 main() 只起守护线程、无 argv 派发；无一条 subprocess 入口测试（V-303/304） | BROKEN（入口）/ TESTED（内部函数，绕过入口） |
| CHAIN-06 Audit→Finding | ACTIVE；已接线 | 运行 3 次**全部失败**；0 条 finding issue；state.json 不存在；采纳率不可算 | IMPLEMENTED（从未成功） |
| CHAIN-07 强模型验收环 | ACTIVE；已接线 | claims.py/claim_intake/reproduce 代码完整；review.yml + Copilot token 就位；**0 条 claim/verdict/reproduction 块发布过**；policy.yml review.required_check=false（设计如此） | IMPLEMENTED |
| CHAIN-08 Conductor tick | ACTIVE | 运行 10 次：前 6 次 success、**最近 4 次全部 failure**；11 步单进程串行确认 | EXERCISED（当前不健康） |

**结论：规格书中 6 条 "ACTIVE" 链路，实测只有 1 条达到 EXERCISED 且正处于故障状态；2 条从未运行；1 条从未成功；1 条从未产出工件；1 条入口损坏。** 规格书的 status 词汇表（专家 P2-10 的批评）实测成立：ACTIVE 被用来同时表示"代码写了"和"生产里跑通了"。

### 2.2 规格书已过时/已自愈项（文档断言 vs 实测）

| 文档断言 | 实测 | 终裁 |
|---|---|---|
| 专家 P0-7：upgrade cron `0 5 0 * *` 非法，链从未触发 | cron 已修为 `0 5 * * 0`（V-202 九条 cron 全 LEGAL）；但 upgrade **仍然从未运行**（V-401）——证明"修复 cron"不等于"链活着" | 专家问题本身已过时；其衍生建议（liveness 覆盖全链、按各自周期）实测更必要了 |
| smoke 14 PASS / 2 FAIL（f-a + g shadow-freshness） | 现为 15 PASS / 1 FAIL；g 测试已不存在；f-a 失败对象是**本地引用** `./.github/workflows/gates.yml`（V-302） | f-a 是误报性质的红，不是供应链 SEV；但"红着进 known-issue"的做法必须禁止 |
| gate_profiles: default=[charter,paths,verdict,heterogeneity] | 现为 default=10 门（+diffsize/license/minage/testown/upstream/lockdiff）、strict=11 门（+conformance）（policy.yml 原文） | 规格过时；门禁面比假设宽 |
| `.loop/audit/shards.yml`（4 片×3 lens） | 文件不存在；分片配置入 policy.yml（quota=8、floor=0.35、stale=21 实测确认） | 规格过时 |
| 状态集 ready/…/verified/failed | 实测状态含 `done`/`closed`；产品仓卡用 `state=done`；`verified` 未在代码中出现 | 状态词汇已漂移；声明式转移表缺失（V-606） |
| DATA_FLOW 五块 schema 在 `.loop/schemas/` | 4 个 schema 文件存在，**但代码从不加载它们**（V-602：FINDING_REQUIRED/VERDICT_REQUIRED 硬编码）；issue 上块字段与 schema 已不一致（lease_until/model 为 null） | "schema 存在"≠"schema 生效"；单一事实源缺失实测确认 |
| 落地 §6.1：merge_group 层缺失 | loop 仓 ruleset 已启用 merge_queue（SQUASH/ALLGREEN）+ 两个 workflow 有 merge_group 触发 | 该建议对 loop 仓已过时；对产品仓待确认（401） |
| 落地 P0-4：越界只有客户端检查 | gate_paths.py 在 CI 端、基于 merge-base diff 复算 | 部分过时；但 gate_paths 有 5 条 SKIP 逃生通道（见 §2.4） |
| 专家 P0-4：pin 未 pin 到内核 | 薄壳 `with: loop-sha` 与 `uses:` @SHA、LOOP.yml loop.sha 三方一致，均为 40 位硬编码，由升级环统一回填 | **基本已解决**；残余两个洞见 §2.4（P-6/P-7） |

### 2.3 仍然成立的结构性根因（实测逐条确认）

| 根因 | 实测确认证据 | 终裁 |
|---|---|---|
| **R1** 拿 GitHub Issue 当分布式数据库 | write_block CAS 实现确认（L117-130）；产品仓卡 lease_until 用 epoch 秒、loop 仓卡 lease_until=null——租约机未被真正使用；状态真相在 issue body，作者含 54 个人类账号直写 | 成立。git ref CAS（loop-state 分支）+ 意图收口仍是正确解，但**优先级下调**：先让状态机被真实使用，再谈它的原子性 |
| **R2** 被约束者持有约束的写权限 | loop 仓**根 CODEOWNERS 缺失**（V-501）；ruleset required_approving_review_count=0、bypass=[]——机制文件（gates/、policy.yml、prompts/）的 PR 只要 6 项 check 绿即可进 merge queue，无需任何人类评审；抑制/例外无登记机制 | 成立且是最优先修复项之一。**平台事实修正：push ruleset 路径限制在 public 仓任何 plan 下均不可用**（2026-07 官方确认，仅 Team+ 的 private/internal 仓可用）——public 仓的现实三件套是：**根 CODEOWNERS（机制路径 owner=人类）+ 分支 ruleset 评审数≥1（人类 CODEOWNER 评审）+ 棘轮门禁**；若未来转 private 再升级 push ruleset（记入 ADR） |
| **R3** 断言与证据混同 | `verdict["verifier_model"] = MODEL`（环境变量自报，loopd.py 实测）；gate_verdict 只校验块结构与 head_sha，**acs[].pass 照单全收**；acceptance 仅 ≥1 条（V-604）；acs[].id 与卡 acceptance 无交叉引用；blind_phase_commit/artifact_digest 无格式校验（V-603） | 成立。信号保真度层（redproof/holdout/RHG/fail→pass 证据）是唯一根治路径 |
| **R4** 自动化了记账，没自动化干活 | 0 条 verdict/claim/finding 工件；12 张产品卡由人类关闭；BROKEN-01 未愈；Planner 无调度 | 成立。但注意：产品仓 12 张 `canary:true` 卡证明**端到端通路在人类手动驱动下是通的**——缺的是"机器驱动 + 证据"的最后一公里 |
| **元问题**：332 tests pass 与 CLI 100% 不可用并存 | V-301（332 passed）与 V-105（NameError 复现）、V-304（无 subprocess 入口测试）同时确认 | 成立。入口契约测试是 W0 第一卡 |

### 2.4 实测新发现的问题（文档中没有，按严重度排序）

| # | 问题 | 实测证据 | 严重度 |
|---|---|---|---|
| **P-1** | **门禁 fail-open 体系**：gate_paths 有 5 条 SKIP=exit 0 通道（无 PR 上下文 / gh 失败 / PR body 无 `Card: #NNN` / 卡块解析失败 / 卡 paths 为空）；gate_verdict 同样 SKIP（无卡/trivial/verify.required=false）；diffsize 等卡作用城门禁同构。**无卡 PR 可以绕过全部租约与验收门禁**，而"卡必须由 conductor 创建"没有任何门禁把守（54 个人类直建 issue 就是证据） | gate_paths.py / gate_verdict.py 原文；V-404 作者分布 | **P0** |
| **P-2** | **gate 搜索顺序注入**：policy.yml `search_dirs: [gates, .loop/gates, ${LOOP_ROOT}/gates]`"先到先得"；reusable-gates.yml 以 `--root .`（产品仓根）执行 → 产品仓 PR 放置 `gates/gate_*.py` 可遮蔽/注入控制面门禁实现（专家 P0-3 的现役版本） | policy.yml 原文；reusable-gates.yml 原文（`--root .`） | **P0** |
| **P-3** | **audit 链从未成功 + conductor 近 4 连败**：链级健康无告警（liveness 只覆盖 canary/scribe/nightly-rubric/audit 且 26h 硬编码）；template-sync/upgrade 从未运行也无声响 | V-401 运行史 | **P0** |
| **P-4** | **secret scanning / push protection / dependabot 全关**：公开仓 + LLM 生成内容直发 GitHub，出站秘密扫描为零；出站过滤器（scrub_outbound）不存在。**平台事实：这三项对 public 仓全部免费，开启零成本** | V-410；V-411 secrets 引用面 | **P0** |
| **P-5** | **根 CODEOWNERS 缺失**：机制文件无人类所有权；ruleset 评审数=0（见 R2） | V-501；V-409 | **P0** |
| **P-6** | **conformance 门禁三个盲区**：(a) 只验 pin commit "可达"，不验是否 main 祖先（fork/已回滚 commit 可通过）；(b) check6 只比对 `uses:` 行，不解析 `with: loop-sha`——两者不一致时门禁从 B 执行而检查看到 A（PIN_SKEW-2）；(c) 不校验 `with: profile` 的值（strict→default 自降级丢 conformance 门） | gate_conformance.py 原文 | **P1** |
| **P-7** | **profile 由产品仓传参**：reusable-gates `inputs.profile` 默认 strict，产品仓薄壳可改传 default（唯一开关面）——虽只能 default/strict 二选，但 default 恰好丢 conformance | reusable-gates.yml 原文 | **P1** |
| **P-8** | **环境可改 diff 基线**：gate_paths 用 `LOOP_CI_BASE` 环境变量兜底 merge-base 基线，可被调用方环境影响 | gate_paths.py 原文 | P2 |
| **P-9** | **两条 CI 链当前红着**：conductor 4 连败、audit 3 连败，无人感知（无 needs-human issue） | V-401；V-403 | **P1** |
| **P-10** | **bench 基线过松**：baseline.json `first_ci_pass_rate=1.0`、`single_card_cost_yuan=0.0`——10 张 replay 卡全为合成卡，基线 trivially green，升级环的"不劣化"判据目前没有区分度 | V-307 | P2 |
| **P-11** | **双卡方言**：loop 仓卡（materialize.py 产物，字段缺 lease/model）与产品仓卡（state=done、canary、merged_pr、epoch 秒 lease）字段集不一致 | V-404 vs V-707 | P2 |
| **P-12** | **pin_back 对通用依赖是空操作**：劣化时只改 runner 本地 UPSTREAM.yaml，不提交不开 PR | upgrade_ring.py 原文 | P2 |
| **P-13** | **review.required_check=false 的取舍**：设计意图明确（模型不确定性不卡合并线），但与"判断型验证只有否决权"的落地 N19 之间存在语义缝——claim 永不阻断，意味着 CHAIN-07 的全部价值依赖 Finding→卡转化纪律，而该纪律无度量 | policy.yml 原文 | P2（接受设计，补度量） |
| **P-14** | **人类 PAT 痕迹**：secrets 引用含 `GH_TOKEN`×3、`SCRIBE_GH_TOKEN`×3——需确认这些是 App token 还是个人 PAT；issue 作者 randypanding 直建 54 条说明人类在用自己的身份做机器该做的事 | V-411；V-404 | P1 |

---

## 3. 五份文档逐条终裁

终裁口径：**采纳**（按原建议做）/ **修正采纳**（方向对，按实测修正后做）/ **已实现**（仓库里已有等价物，仅补差）/ **缓议**（方向对，但 gated 于前置条件）/ **不采纳**。

### 3.1 专家意见（文档2）终裁

| 条目 | 终裁 | 理由（实测依据） |
|---|---|---|
| P0-1 write_block 非 CAS（TOCTOU） | **修正采纳→W1** | 技术判断成立，但实测租约机根本没被使用（卡 lease=null）。先在 W1 让状态机被真实使用 + 意图收口（落地 P0-2 阶段B），git ref CAS 与单写者串行化**二选一**，取**单写者（intent.yml + concurrency group）**：改动小、与现有 POLICY 双 App 模式同构；loop-state 分支方案记入 ADR 备选 |
| P0-2 租约无 fencing | **修正采纳→W1** | epoch fencing 随意图收口一并落地；reaper 判据改"心跳判活、commit 判进展"直接采纳。前置是 CLI 修复（W0）让租约先被用起来 |
| P0-3 `.loop/gates` 搜索=注入 | **采纳→W0** | 实测确认（P-2）：搜索顺序 `[gates, .loop/gates, ${LOOP_ROOT}/gates]` + `--root .` 使产品仓可遮蔽门禁。W0 删除前两项、只留 `${LOOP_ROOT}/gates`，profile 改由控制面 products.yml 下发（与 P-7 同修） |
| P0-4 pin 未 pin 到内核 | **已实现→残余进 W3** | 三方 pin 已一致（V-703/704）；残余：pin 祖先校验、`with: loop-sha` 一致性、profile 值校验（P-6/P-7），并入 W3 的 gate_pin_integrity 强化 |
| P0-5 异构建立在自报身份上 | **修正采纳→W1/W4** | 实测：ROUTING.yaml 已是半外置（#134 修复），但 verdict.verifier_model 仍自报。W1 先把身份写进租约记录（dispatcher 派卡时写入，agent 只读）；HMAC 签名与 attestation 缓至 W4（团队 plan 下私有仓 attestation 受限，见研究附注） |
| P0-6 越界防护在客户端 | **修正采纳→W0/W3** | gate_paths 已有服务端孪生（merge-base diff）；真正的洞是 fail-open SKIP（P-1）与机制路径无人类所有权。**平台事实：push ruleset 路径限制 public 仓不可用**——W0 改为上根 CODEOWNERS + 评审数≥1（人类）+ settings as code 固化；W3 把 SKIP 语义改 fail-closed；转 private 后再启 push ruleset（ADR 备选） |
| P0-7 cron 错误 | **已实现** | 已修（V-202）。衍生项（liveness 全链覆盖、按链配周期、cron 语法门禁）→ W0 |
| P0-8 Materializer 无事务边界 | **采纳→W1** | 确定性幂等键 + upsert + materialize_repair；叠加实测发现的双卡方言（P-11）一并治 |
| P0-9 pull_request_target | **已实现（无此问题）→ 防回归** | 全仓零命中（V-205）。将其固化为 W0 的 diff 卫生规则（D9 常驻）+ workflow 权限最小化 lens |
| P1-1 pin 双写者打架 | **缓议→W3** | template-sync 与 upgrade 从未运行，冲突尚未发生；W3 合并为单一 reconciler（pin 所有权归升级环）随首次真实运行前完成 |
| P1-2 无漂移检测 | **已实现→补差** | drift.yml（6h）已在；缺"受管文件哈希 == 模板哈希"的 PR 级 fail 与 shadow 复制检测（jscpd），进 W2/W3 |
| P1-3 tick 11 步单体 | **采纳→W1** | conductor 4 连败证明隔离缺失的代价；supervisor + 独立步骤 + 步骤级 liveness |
| P1-4 API 配额未建模 | **缓议→W4** | 当前余量 4986/5000，单产品仓无压力；统一 GH 客户端封装随 dispatcher 一并做 |
| P1-5 无生命周期对账 | **采纳→W1** | products.yml 记数字 repo id（product-x id=1315634637 已测得）+ repo_lifecycle_reconcile |
| P1-6 merge 后无人推终态 | **采纳→W1** | 实测人类手动关卡的直接原因；merge-completion reconciler + 状态转移表 + reaper 限定 {claimed,in_progress} |
| P1-7 tier 由 Planner 声明 | **采纳→W3** | tier_hint vs computed_tier + 只升不降 + planner_tier_disagreement 指标；与 max_diff_lines 现存棘轮（300/600/400）对齐 |
| P1-8 "48h 沉默=同意" | **采纳（收缩）** | 实测 silent dispatch 已接线 product-x。W0 先把窗口 48h→168h 并加前置（全门禁绿+白名单+次数上限），W3 加 review-verdict AND 条件，W4 重评估 |
| P1-9 .verify.sh 由被验证方掌握 | **修正采纳→W2** | 实测产品仓用 tests/acceptance/run.sh（非 .verify.sh）。frozen_paths + 测试先行（T-card）+ fail→pass 证据全套进 W2 |
| P1-10 盲提交无时间戳 | **缓议→W4** | 评论时间戳校验成本低，但 blind 流程从未真实运行；随 CHAIN-07 激活一并做 |
| P1-11 bench 随机性按确定性判 | **修正采纳→W2/W4** | 实测 bench 无 LLM（确定性好），但基线 trivially green（P-10）。W2 先补基线区分度（真实历史卡 replay + mutation 第五指标）；统计判决（n≥5/序贯检验）随 bench 含 LLM 时再做 |
| P1-12 审计信号无地面真值 | **修正采纳→W2** | per-lens 记分卡/隔离降频/stale_close 前置条件采纳；指纹去 path 化**降优先级**：policy.yml 已写 normalized_path（实测）；人类月度抽标注随首次真实 finding 出现后做 |
| P1-13 race_mode 无可证伪择优 | **缓议→W4** | race 影子实现从未跑；W4 与 ACRouter 一并定义可计算 winner function（mutation delta 三元组） |
| P2-1 loopd 上帝对象 | **采纳（W0 先做最小修复，分层重构缓至 W1）** | 修正：W0 只做 argv 派发 + CFG 物化 + 契约测试（3 天）；loopd 分层（cli/usecases/domain/ports）放 W1 与状态转移表合并做，避免 W0 拖长 |
| P2-2 三方一致性（文档/HANDLERS/路由） | **采纳→W0** | 契约测试 + subprocess 入口测试（实测：prompts 里只出现 3 个 loopd 动词、16 动词注册、0 入口测试） |
| P2-3 h_reset/h_drop 数据丢失 | **采纳→W1** | wip 分支备份，成本极低 |
| P2-4 无统一事件流 | **修正采纳→W1** | append-only 事件日志（loop-events orphan 分支，JSONL+prev_hash 链）采纳；与 P0-1 的单写者共用同一写入点，一次落地 |
| P2-5 state.json 可变单例 | **缓议→W2** | 文件尚不存在；audit 首次成功后按"finding 自有属性存 finding、state.json 只留索引"设计 |
| P2-6 schema 版本化无迁移策略 | **采纳→W1** | 与单一事实源合并：代码生成 dataclass + 读者接受 {N,N-1} + SCHEMA_UNSUPPORTED 显式错误 |
| P2-7 Prompt 无 pin 无回归 | **修正采纳→W2** | prompt_sha 入卡与 VERDICT 采纳；promptfoo/ 已存在（实测），prompt 回归测试基于它建，不必新造 eval 框架 |
| P2-8 无成本核算 | **修正采纳→W2/W4** | LLM_GATEWAY_KEY 已存在（实测）——gateway 侧记账的接线点现成；W2 先在 trace 块留 receipt 字段，W4 强制 |
| P2-9 人类界面缺失 | **修正采纳→W0** | HUMAN-TODO.md 已存在（实测）——W0 把它升级为自动生成的每日 digest（四问：卡在我这的/昨天放行的/什么退化了/花了多少），不新建系统 |
| P2-10 状态词汇混淆成熟度 | **采纳→W0** | 成熟度阶梯写进 CHARTER（G 条款区），本文 §2.1 即首版 |
| §4.1 Canary Corpus | **修正采纳→W0/W1** | canary.yml + canary-chain.sh/survival.sh 已存在（实测）——不新建，而是**按 12 条故障用例扩充**并接通"未拦截即 page + 冻结放行"；W0 先上 5 条，W1 补全 |
| §4.2 Dispatcher | **缓议→W4** | 与落地文档裁决一致：信号保真度数字出来之前，自动派卡是漂移油门 |
| §4.3 Kill switch + 分环发布 | **修正采纳→W0/W3** | policy.yml freeze 布尔（W0，成本一行）；ring 灰度随升级环首次运行（W3） |
| §4.4 Charter 覆盖矩阵 | **采纳→W1** | 每个 gate/lens 声明执行的 charter 条款，零执行者条款=风险登记册；与 N16-N27 立法同步 |
| §4.5 主分支合并后验证+自动 revert | **修正采纳→W2** | merge queue 已有；main-guard.yml（深度套件+红自动 revert+冻结队列）进 W2 |
| §5.2 声明式状态转移表 | **采纳→W1** | TRANSITIONS 表 + 穷举性质测试；实测状态集（含 done/closed）以此立法 |
| §6 不变量清单 / §7 指标 SLO | **采纳→贯穿** | 作为各波次出口判据的组成条款直接引用 |

### 3.2 工具建议A（文档3：Outlines/codebase-memory-mcp/Meta-Harness/SkillOpt/Rubric/ACRouter/FastContext/SkillX/AGP）终裁

| 条目 | 终裁 | 理由 |
|---|---|---|
| W0 前置闸门：先修 BROKEN-01 | **采纳** | 实测仍未愈；修法与其骨架一致（CFG 物化 + argv 派发）+ 契约测试 |
| S1 Outlines 生成端约束 | **修正采纳→W1** | 前提先补"代码消费 schema"（实测不消费，V-602）：W1 先做 schema 单一事实源（加载 + dataclass 生成 + gate_schema_singlesource），Outlines 只接 loop 自调 LLM 的三个点（review.yml 信封、scribe、planner 输入打包）；外部沙盒手写块路径保持消费端校验（双保险）。**核查修正**：Outlines v1.3.2/Apache-2.0 活跃可用，但托管 API（Copilot/OpenAI 兼容端点）只享受服务端 JSON-Schema 子集约束，任意 regex/CFG 仅本地推理端成立——对 5 种 json block 而言 schema 子集足够；OpenRouter 非官方支持，接入前实测 |
| S2 codebase-memory-mcp | **缓议→W3 评估** | 产品仓当前极小（2 个测试文件），符号级影响面无现实负载；图缓存不进产品仓 git、降级 exit 4 等纪律预先采纳；W3 按并行卡数量再评估。**核查修正**：真实项目为 `DeusData/codebase-memory-mcp`（36.7k stars，MIT），能力为 158 种 tree-sitter AST + 约 10 种语言 LSP 级解析（文档3 所称"14 LSP+159 AST"数字不实，但 index/detect_changes/trace_call_path/get_architecture/query_graph 工具名全部属实，单静态二进制、无需 API key 属实） |
| S3 Meta-Harness | **缓议→W4+** | 其前置（BROKEN-01 已修 + ADR-014 达标）均未满足；评价信号不可信时跑元搜索=用噪声训练噪声。**核查修正**：论文真实（arXiv:2603.28052，消融数字逐字属实），但文档3 指定的 dkhanal 版与 angrysky56 fork **在 GitHub 上均不存在**——实现以官方 `stanford-iris-lab/meta-harness`（MIT）为准，tbench2-artifact 仓无许可证勿用；"拒绝 Required 非确定性 MCP 依赖"作为设计原则保留；SAFEGUARD-14/15/16 三阀先行——这些纪律现在写进 CHARTER |
| A1 SkillOpt + Sleep | **缓议→W4** | Sleep 挖掘是 BROKEN-02 的正确解法（ Planner 降为审批点），但必须晚于 RHG/召回率稳定（落地文档裁决优先，见 §3.5） |
| A2 comet Rubric 层 | **缓议→W4（shadow）**；**Pass^k 立即采纳→W2** | Rubric 多维评分 shadow mode 缓至 W4；**Pass^k 统计判据立即采纳**，W2 起用它替代 ADR-014 的"7 天"时长条件作为 e2e 就绪定义（与落地 §3.4 的门禁召回率并列） |
| A3 ACRouter | **缓议→W4** | ROUTING.yaml 静态路由已存在；W4 用 bandit（不训 LoRA）+ gateway 记账驱动；SAFEGUARD-19（硬约束可行集）写进 CHARTER |
| B1 FastContext | **不采纳（现形态）** | 自托管推理端引入非确定性运维面；**核查补充：论文真实（arXiv:2606.14066）但官方仓 microsoft/fastcontext 当前 404，仅社区镜像可用**——可接入性低坐实不采纳；若 W4 后 token 仍瓶颈，只取其协议（只读探索+回传路径行号）由 router 指派便宜模型执行 |
| B2 SkillX | **缓议→W4** | 与 SkillOpt 共用 skills/ 目录的纪律采纳；实体缓议 |
| B3 AGP RSPL/SEPL | **修正采纳→W4** | **核查修正**：出处为《Autogenesis: A Self-Evolving Agent Protocol》（arXiv:2604.15034；`DVampire/Autogenesis`，MIT）；RSPL=Resource Substrate Protocol Layer（非"单资源 pin 层"）；resource.yml 字段集系文档3 自拟（无公开出处）。裁决不变：只取纪律（资源注册化+单资源版本+可回滚+血缘审计），在资源数量足以独立回滚时落地（当前 lens 退化可整体回滚，痛点未现）；SEPL 五算子闭环（Reflect→Select→Improve→Evaluate→Commit）的 Reflect 由 Sleep 补（W4-5） |
| SAFEGUARD-14..21 八阀 | **采纳（立法先行）** | 作为 CHARTER N28-N35 现在立法，实体随各优化层上线时激活；SAFEGUARD-18（degraded≠pass，exit 4）与 gate 退出码扩展提前到 W2 |
| 4 波路线图（W1-W4 无条件先行） | **不采纳其时序** | 实测决定：先跑通证据链再谈优化层；采用本文 Part II 的 W0-W4 时序 |

### 3.3 工具建议B（文档4：Semgrep/gitleaks/jscpd/syft/osv/TruffleHog/Spectral/oasdiff/mutmut/Stryker/vulture/knip）终裁

四条公理（A1 可复算性决定挂载点 / A2 稳定 rule_id / A3 一缺陷类一真值源 / A4 净收益）与 R1-R8 横切规约**整体采纳为工具接入宪法**（写进 CHARTER）。逐工具：

| 工具 | 终裁 | 挂载与波次 | 理由（实测依据） |
|---|---|---|---|
| **gitleaks** | **采纳（最高优先）** | W0：Gate + 出站 scrub | 平台侧 secret scanning/push protection 全关（P-4），出站内容零过滤；公开仓+LLM 文本直发=现实风险 |
| **Semgrep CE（自研规则）** | **采纳** | W0：Gate（rules/loop/** 自研规则）；W2：Lens（通用安全集） | 机制不变量声明式化；`loop.dispatcher-orphan` 规则可静态拦截 BROKEN-01 同类缺陷。许可证约束成立：loop 仓 public，**官方规则不得 vendored**（N16 立法）；退出码翻译表（1=有发现≠引擎错）必须先写 |
| **vulture** | **采纳** | W2：conf=100 进 Gate，<100 进 Lens | loopd 951 行上帝对象 + "注册不可达"前科；白名单 CODEOWNERS 锁定 |
| **jscpd** | **采纳** | W2：跨仓机制复制（挂 drift.yml 遍历）+ prompts 去重 | N9/N14 的唯一可执行化路径；conformance check5 只查"存在性"，jscpd 补"相似度" |
| **Spectral** | **采纳** | W2：loop 契约治理（products.yml/policy.yml/ROUTING.yaml/LOOP.yml/shards） | 把 Python 硬编码校验降为数据；与 schema 单一事实源同波次协同 |
| **syft（SBOM 棘轮）** | **采纳** | W3 | requirements 已 hash-pin（基础好）；SBOM 锁 + verdict.artifact_digest 绑定随 holdout 一起 |
| **osv-scanner（离线库 pin）** | **采纳** | W3：Lens 起步，离线库快照随升级环托管后升 Gate | "扫描=f(SBOM, DB 版本)"纯函数化 + 升级环统一 bump 是正确形态；依赖面当前极小（PyYAML 单依赖）故排 W3 |
| **mutmut** | **采纳** | W2：先 bench 第五指标（不阻断）；W3：增量 delta gate | 断言层假绿是实测最大洞（332 pass 无信息）；runner ubuntu 满足 fork；缓存/超时/type_check 配置纪律采纳 |
| **TruffleHog** | **缓议→W4** | CHAIN-07 reproducer | 依赖 CHAIN-07 先激活（0 claim 现状）；届时 gitleaks→claim→TruffleHog 三态裁决接线 |
| **oasdiff** | **缓议** | 条件启用 | product-x 契约是 api-health.md（非 OpenAPI）；出现 openapi.{yaml,json} 时自动注册该 gate（GATE_SKIPPED 语义先行） |
| **Stryker / knip** | **缓议** | 按 profile 条件启用 | 现有产品仓为 Python；TS 产品仓出现时随 profile: node 启用 |
| R1 基线棘轮 | **采纳→W2** | 每新工具三步走 | audit 配额 8/天 + 0.35 throttle 是实测在册的保护对象 |
| R2 抑制即假绿 | **采纳→W0（立法）/W2（工具面）** | SAFEGUARD 升格 | 例外登记表 .loop/exceptions.yml + no-fake-green 模式表扩展 + 抑制趋势审计 |
| R3 规则单一副本 | **采纳→W2** | rules/ 只在 loop 仓 | Spectral 校验 LOOP.yml 不含规则 + jscpd 检测复制 |
| R4 工具版本升级环托管 | **采纳→W3** | tools.lock.yml + 升级环 bump | 与 osv 离线库快照同一通道 |
| R5 Lens 退出码翻译 | **采纳→W2** | 三分翻译表 | SAFEGUARD-13 误杀防护 |
| R6 分片重排+per-lens 采纳率 | **采纳→W2** | 随新 lens 上线 | 当前 0 finding，无历史包袱，正好重做 |
| R7 CI 时长≪租约 | **采纳→W2（测基线）** | p95<5min 硬约束 | lease 30min/reaper 60s 实测在册；心跳计"CI 运行中"为活跃 |
| R8 产物不落工作树 | **采纳→W2** | .loop/tools/ + artifact | SAFEGUARD-03 冲突预防 |

### 3.4 落地方案（文档5）终裁

| 条目 | 终裁 | 备注 |
|---|---|---|
| §0 诊断（形式门禁 ≠ 内容验证） | **实测确认** | V-603/604、gate_verdict 照单全收 acs.pass |
| P0-1 CLI 修复三件套（结构化输出/契约测试/文档漂移门禁） | **采纳→W0** | 派发骨架采纳；分层重构缓 W1（见 3.1 P2-1） |
| P0-2 状态存储自写（哈希链+意图收口） | **采纳→W1** | 阶段A 哈希链 + state_audit；阶段B intent.yml 单写者（与专家 P0-1 合并为单写者方案）；verified/done 只能 CI 身份写入立即立法 |
| P0-3 pin/profile 自降级（gate_pin_integrity） | **采纳→W3（强化版）** | conformance 已覆盖大半（已实现）；补祖先校验 + loop-sha 参数一致性 + profile 值校验（P-6/P-7） |
| P0-4 客户端阀门的服务端孪生（N17） | **采纳→W3** | gate_paths/verdict 已有孪生但 fail-open；核心是把 SKIP 改 fail-closed + gate_card_provenance（P-1） |
| P0-5 例外机制自助（EXC 登记 + N18 棘轮 + N26） | **采纳→W0 立法 / W1 实体** | .loop/exceptions.yml + gate_ratchet；两条红 smoke 处理纪律采纳（f-a 修规则非删测试） |
| §3.1 T-card + red-first proof | **采纳→W2** | 中心项；产品仓 tests/acceptance/ 是其落点 |
| §3.2 holdout + RHG | **采纳→W2** | **Bench 仓（org 内已存在，upgrade.yml 已在拉取它作为 holdout replay pack）就是 holdout 的天然存放地**——日志脱敏纪律必须同步 |
| §3.3 变异测试 delta 门禁 | **采纳→W2 bench / W3 gate** | 与 mutmut 终裁一致 |
| §3.4 故障注入 harness（门禁召回率） | **采纳→W2** | 与 canary 扩充合并：bench/faults/ 14 类题库 + gate_recall 周跑 + 召回率进升级环指标 |
| §3.5 flaky 治理 | **采纳→W2** | reaper attempt+=1 的结构性重试激励实测在册 |
| §3.6 元评估（gate_meta + placebo 检测） | **采纳→W2 立法 / W3 检测** | "每 gate 必有阳性拦截测试 + 必被 fault 引用"先立法 |
| §4.1 AC 机器可判定 | **采纳→W3** | acceptance≥1 实测确认不足（V-604）；schema 改造是最高杠杆点 |
| §4.2 契约推导依赖 | **采纳→W3** | contracts/ 雏形已存在（api-health.md）；depgraph + 禁手写 blocked_by |
| §4.3 对抗性规格评审（wave-review） | **采纳→W3** | 复用 review.yml 模式；silent_auto_release AND review-verdict 同波 |
| §4.4 卡片规模上限 | **修正采纳→W3** | max_diff_lines 已有（300/600/400，实测）；补 max_files/max_attempts 与"超限拆卡无 EXC" |
| §5.1 worktree 隔离/共享路径/分支寿命 | **采纳→W3** | 分支寿命上限 tick[13] 直接采纳 |
| §5.2 respec 状态 | **采纳→W3** | 与转移表立法一致 |
| §5.3 波次非分支（N20） | **采纳→W0 立法** | 实测无 wave 分支，现状合规，立法防回归 |
| §6.1 workflow 分层（含 merge_group） | **修正采纳** | merge_group 已有；reusable-deep/main-guard 进 W2；reusable-probe 缓 W4 |
| §6.2 diff 卫生 D1-D13 | **采纳→W3** | D1/D2/D12 已有雏形（paths/diffsize）；D9 实测无 target 但需常驻 |
| §6.3 traceability 块（spec_sha/gateway receipt） | **采纳→W3** | spec_sha 防"边做边改规格"是关键 |
| §6.4 可逆性三件套（flag/main-guard/双钥匙） | **修正采纳→W2/W3** | main-guard 进 W2；feature flag 与 risk_class 双钥匙进 W3 |
| §6.5 Ruleset 组织级 | **修正采纳→W0** | 仓级已有且 bypass=[]（好）；W0 补：根 CODEOWNERS、required check 增加项、产品仓侧对齐（401 待查项列入 W0 入口） |
| §7 八问矩阵新增 gate | **修正采纳** | security 面（CodeQL SARIF 已有，补 secret/dep-review/SBOM）W2-W3；observability/migration/budget gate 缓 W4（产品无 critical_path 负载） |
| §8 Playwright T1/T2/T3 | **缓议（T1 除外）** | T1=tests/acceptance/run.sh 已有雏形随 W2 强化；T2/T3 与 personas/jtbd 缓至有真实用户界面负载时 |
| §9.1 异构升 family/vendor 级 | **采纳→W1 立法 / W2 门禁** | model→family→vendor 映射入 policy.yml；spec-test≠impl 家族同立法 |
| §9.2 路由表 | **已实现→W4 数据化** | ROUTING.yaml 已存在 |
| §9.3 gateway 记账 | **修正采纳→W2 字段 / W4 强制** | LLM_GATEWAY_KEY 已存在 |
| §9.4 golden set | **采纳→W2** | bench/replay 10 卡是种子；补真实历史卡 |
| §9.5 影子模式 | **缓议→W4** | |
| §10 escalation.yml + 仪表盘 | **采纳→W1/W2** | ESC-01..12 求值器进 W2；HUMAN-TODO.md 升级 digest 进 W0；dashboard.json 已有种子 |
| §11 持久记忆 | **修正采纳→W1** | DECISIONS.md 已存在；补 memory/rejected.yml 与 P3 检索强制 |
| §12 N16-N27 | **采纳（修订后立法）** | 见 §4 结论八；N21 与现有 max_diff_lines 对齐数值 |
| §14 W-00..W-07 时序 | **修正采纳** | 采用本文 Part II 波次（重排：平台止血与 CLI 同在 W0；信号层 W2 不变；自动调度最后） |
| §15 三不要（不修 Planner 调度/不扩 silent/不留自动合并） | **采纳** | BROKEN-02 不修（节流阀）；silent 收缩为 168h+前置；实测无自动合并，立法禁止 |

### 3.5 冲突点裁决汇总

| 冲突 | 裁决 | 理由 |
|---|---|---|
| BROKEN-02 修不修（工具A 修 vs 落地 不修） | **不修** | 落地理由实测更强：RHG 与门禁召回率两个数不存在之前，自动造卡=漂移油门；且人工触发在实测中确实是唯一稳定的人类节流点 |
| Meta-Harness/SkillOpt 时序（工具A W1-W4 vs 落地 信号层优先） | **落地优先** | 0 条 verdict/claim 工件 + 基线 trivially green 的实测下，元优化无信号可吃 |
| Outlines 时序（工具A W1 先行 vs schema 不消费现状） | **schema 单一事实源先于生成端约束** | 代码不加载 schema 时，生成端约束只会制造第二份"看似生效"的契约 |
| 48h silent（规格现状 vs 落地 收缩） | **收缩** | 168h + 前置条件 + W3 加 review-verdict AND |
| CAS 方案选型（专家 git ref CAS vs 单写者） | **单写者优先，git ref CAS 入 ADR 备选** | 与现有 POLICY 双 App/intent 模式同构、改动小；loop-state 分支在跨仓规模上来后再评估 |
| TruffleHog/oasdiff/Stryker/knip/S2/Meta 层 | **条件启用制** | 以"出现对应负载/前置达标"为启用条件，不排日历 |

---

## 4. 架构该怎么改：十条最终结论

> 每条给出：结论 → 依据 → 明确不做什么。这十条是终裁，后续波次（Part II）是它们的施工展开。

**结论一：停止扩充机制总量，把"一张由机器端到端完成、且证据链完整的卡"（下称 FMC-E）作为全系统的北极星。**
依据：机制密度已远超证据密度（17 个 workflow、13 个 gate、16 个 lens，但 0 条 verdict/claim/finding 工件；§2.1）。继续加机制只会扩大假绿表面积。FMC-E 的定义：materializer 建卡 → agent 经 CLI 领取 → 在租约内完成 → CI 门禁全绿（无 SKIP）→ verdict 由 CI 身份发布且 head_sha 绑定 → merge queue 合入 → 卡自动进入终态 → 事件日志与投影对账为零。第一张 FMC-E 出现之前，不启动任何新子系统。
不做：不在 W0-W1 新建任何与 FMC-E 无关的机制。

**结论二：改造顺序固定为六步，不得调换——入口 → 契约 → 状态 → 证据 → 规格 → 自治。**
依据：CLI 入口坏（P-元问题），则一切 agent 交互是假的；schema 不被代码消费（V-602），则一切"按 schema 校验"是名义的；状态机无转移表、无单写者、无 fencing（R1/P-1），则一切状态结论可被覆写；没有证据层（R3），则门禁只查形式不查内容；规格不可判定（V-604），则并行与路由都没有地基；前五者不立，自治（dispatcher/优化层）就是给漂移装油门（§3.5）。
不做：不把任何 W2+ 的工作提前到 W0-W1；不在证据层达标前修 BROKEN-02。

**结论三：安全确权用一天时间补齐"免费且现成"的平台项 + 人类所有权，这是全案 ROI 最高的一步。**
依据：secret scanning / push protection / dependabot 对 public 仓全部免费而当前全关（P-4）；根 CODEOWNERS 缺失且评审数=0（P-5/R2）；gate 搜索注入（P-2）一行配置可消除。push ruleset 路径限制在 public 仓不可用（2026-07 平台事实），故所有权落法是 CODEOWNERS + 评审数≥1 + settings as code，转 private 才升级 push ruleset。
不做：不为"更安全的错觉"把仓转 private——public 换来自由 Actions 分钟、免费 attestation、免费 merge queue、免费秘密扫描，经济账上明显划算；代价是机制公开，用"秘密零出站 + 签名/租约外置"对冲。

**结论四：消灭 fail-open——全部卡作用城门禁改 fail-closed，并给"卡"本身上 provenance 门禁。**
依据：gate_paths/gate_verdict 的 5+3 条 SKIP 通道（P-1）使无卡 PR 畅行；"卡由谁创建"无门禁（54 个人类直建 issue）。规则：无卡 PR 默认只能触白名单琐碎路径（docs/assets）；其余一律需要有效卡引用且卡 issue 作者 ∈ App 白名单；SKIP 语义废除，条件性门禁用显式 GATE_SKIPPED（exit 5）且绝不属于 required check 集合；required check 列表里的每个门禁禁止任何形式的 skip-pass。
不做：不搞"宽进严出"的过渡态——fail-closed 一刀切，例外走 EXC 登记。

**结论五：信号保真度层是改造中心，且 holdout 的家就是已有的 Bench 仓。**
依据：R3 实测成立；落地 §3 的三个传感器（red-first proof / holdout+RHG / fault injection）与本仓结构完美契合：产品仓 tests/acceptance/ 是 T1 落点，org 内 Bench 仓（upgrade.yml 已在拉取它作为 holdout replay pack）是 holdout 的天然存放地——agent 对 Bench 仓无写权限，天然满足"实现方不可见"。RHG>0.15 阻断并自动转 CHAIN-07 裁决（复用现成三态流水线）。ADR-014 的"7 天"判据作废，改用 Pass^k + 缺席率/崩溃率/回收率/RHG 的统计判据（可计算、受保护、不可被优化器篡改）。
不做：holdout 不进产品仓 git（含缓存）；日志脱敏不做则 holdout 不上线。

**结论六：确定性工具按固定次序接入：gitleaks(W0) → Semgrep 自研规则(W0) → vulture/jscpd/Spectral(W2) → syft/osv 离线(W3) → mutmut(W2 bench → W3 gate)；TruffleHog/oasdiff/Stryker/knip 一律条件启用。**
依据：秘密面是全关状态（P-4）且出站零过滤；机制不变量需要声明式化（dispatcher-orphan 这类规则可静态拦截 BROKEN-01 同类）；断言层假绿是 332-pass 无信息的根因；供应链当前只有单依赖（PyYAML hash-pinned），故 syft/osv 排 W3。全部工具受 R1-R8 宪法约束（基线棘轮/抑制即假绿/规则单副本/版本升级环托管/退出码翻译/per-lens 采纳率/CI 时长≪租约/产物不落工作树）。
不做：不接 Semgrep Cloud、不 vendored 官方规则集（loop 仓 public，许可证禁止）；不让任何非确定性输出进 required check。

**结论七：AI 优化层（Meta-Harness/SkillOpt/ACRouter/Rubric/FastContext/SkillX/AGP）全部缓议到 Pass^k 达标并保持 30 天之后；但其八条红线（SAFEGUARD-14..21）现在立法。**
依据：0 条 claim 工件 + 基线 trivially green（P-10）= 元优化无信号可吃；彼时 FastContext 类自托管推理端是负资产，故其现形态不采纳。立法先行的内容：元层不可自证（评价器排除在可写面外）、评估三分+holdout 哈希封存、自进化产物必须走 PR、judge 异构、degraded≠pass（exit 4）、router 不越硬约束可行集、技能变更学习率、概念漂移看门狗。
不做：不在 W4 之前引入任何"训练/优化自己"的组件；不引入任何把非确定性推理服务标为 Required 的外部依赖（文档3 所指 angrysky56 fork 经查不存在，该原则保留）；不引入 comet 状态机。

**结论八：CHARTER 增补三组条款（修订版 N16-N27 + 优化层红线 N28-N35 + 成熟度阶梯 G6-G7），作为唯一宪法层。**
依据：现有 N10-N15 运行良好但覆盖不足。修订点：N16 产品仓禁改 .github/**、LOOP.yml、CODEOWNERS、contracts/**、.loop/**、flags.yml、exceptions.yml、UPSTREAM.yaml；N17 沙盒检查必有 CI 孪生且孪生 fail-closed；N18 棘轮（阈值只许收紧，含 required check 集合只许扩）；N19 判断型验证只有否决权，done/verified 仅 CI 身份可写；N20 波次是标签非分支；N21 卡 diff 上限无 EXC 通道；N22 测试与实现异 agent 异家族、实现方对 tests/** 无写权、holdout 对实现方不可见；N23 深层失败默认 respec；N24 禁止摆设门禁（30 天零拦截须红队证明否则删除）；N25 不可逆动作人类批准；N26 例外具名+TTL+人类署名+ADR；N27 成本只采信 gateway receipt；N28-N35 即结论七的八条红线；G6 成熟度阶梯立法（只有 OBSERVED 以上的链可被依赖）；G7 卡 provenance（卡必须由 App 身份创建，无卡 PR 白名单制）。
不做：不让任何条款处于"零执行者"状态——每条立法必须同波附带执行者（gate/lens/ruleset）与 canary。

**结论九：保留并收缩三处人类节流阀，把"人类只做批准、不做创作"制度化。**
依据：Planner 手动触发在 RHG/召回率有数前不修（§3.5）；silent_auto_release 从 48h 收缩到 168h + 前置条件（全门禁绿+路径白名单+周配额+观察窗），W3 起 AND review-verdict PASS；review.required_check=false 保留（模型不确定性不卡合并线）但补 claim→finding→修复转化率度量，否则 CHAIN-07 的价值无账可查。人类界面用现成的 HUMAN-TODO.md 升级为每日 digest（四问：卡在我这的/昨天自动放行的/什么退化了/花了多少）。
不做：不在 W4 前扩大任何自动放行范围；不给 silent 放行加任何新 tier。

**结论十：升级环、template-sync、audit、review 四条"从未成功"的链，按"首次点火"标准重新验收；pin 所有权合并为单一 reconciler。**
依据：template-sync/upgrade 从未运行、audit 从未成功、conductor 连败（P-3/P-9）；pin 有两个写者（专家 P1-1）尚未爆发但必然爆发；pin_back 对通用依赖是空操作（P-12）。处置：W0 修 liveness 并诊断连败根因；W3-W4 合并 template-sync 与 upgrade 为单一"产品仓 reconciler"（pin 唯一决定者是升级环，template-sync 只补缺失与纠漂移且保留现有 pin）；升级环首跑采用 canary 仓先合→24h 观察→扇出；pin_back 改 PR 化。
不做：不给升级环加自动合并（实测无此行为，立法禁止）；不在首跑通过前接新产品仓。

---

# Part II · 工程建议

## 5. 总则与验证协议

### 5.1 三条总原则

1. **证据密度 > 机制密度**：每一波新增的机制数 ≤ 该波新增的可验证证据工件数。任何波次结束时，"机制总数/已验证机制数"的比例必须下降。
2. **先跑通、再优化**：只有达到 OBSERVED 成熟度（连续 14 天运行证据 + 指标）的链路才允许被其他链路依赖（CHARTER G6）。
3. **人类只做批准，不做创作**：人类的全部动作收敛为 5 类批准（见 §8.1）；一切"人类写 YAML/写卡/写规则"的入口都改为"系统生成 PR → 人类点 merge"。

### 5.2 完工验证协议（客观不可证伪标准）

每一波次的每一条出口判据，必须同时满足以下六点，缺一不可，否则视为未完工：

1. **机器可复核**：判据是一条（或一组）可在干净环境复跑的命令，输出为布尔或数值，不接受人工截图、口头确认、"已检查"声明。
2. **原始输出留档**：命令的 stdout/stderr/EXIT 码全文存入该波次的 `waves/WAVE-XX/evidence/` 目录，文件以 `<判据ID>.out` 命名并附 sha256；CI 侧判据给出 **run ID + URL**（`gh run view <id>` 可复核）。
3. **基线钉死**：判据的期望值在施工开始前写入波次文件（含基线 HEAD 与测量时间），完工复核在同一 HEAD 或由该 HEAD 衍生的合并提交上执行。
4. **破坏性验收**：每个 W0-W3 波次末尾设 `WAVE-XX-REDTEAM`：由与实现者不同厂商/家族的强模型扮演攻击者，按该波指定的攻击清单实际尝试绕过/伪造；**每一次成功的绕过 = 一条新 fault 入 `bench/faults/` + 该波不得关闭**。红队的每次尝试留 PR/run 链接。
5. **独立复核**：完工证据由不参与该波实现的 verifier 角色按 §5.2-1 逐条复跑；复核输出同样留档。verifier 与实现者的 model family 必须不同（CHARTER N22 同源纪律）。
6. **阴性证明显式化**：凡"X 不存在/不再发生"类判据，必须给出证明阴性的命令与输出（grep 无命中 + EXIT=1、API 返回空数组等），与第一批次的证据规则一致。

> 本协议与第一回合的《施工前仓库实测验证要求表》同构：同一套"四件套 + 否定证明 + ACCESS_DENIED + UNKNOWN 优于猜测"标准，直接沿用为施工验收标准。

### 5.3 波次治理

- 每波一张 `waves/WAVE-XX.md`：入口条件、卡包清单（每张卡含 paths/tier/acceptance/验证命令）、出口判据（期望值预先写死）、冻结条件、回滚方式。
- 波次内全部工作以**卡**为单位下发，遵循现有 materializer → 领卡 → 门禁 → 合入通路（W0 前期因 CLI 未修，允许"人类代驾"执行，但每张卡仍须走完整 PR 门禁——这是过渡期内人类唯一被允许的代行）。
- 波次出口判据未全绿 → 不进入下一波；入口条件被破坏（如某 required check 变红超 24h）→ 当前波冻结。

## 6. 波次总表

| 波次 | 名称 | 工期 | 目标 | 入口条件 | 核心出口判据（摘要，详见 §7） | 回滚 |
|---|---|---|---|---|---|---|
| **W0** | 止血与确权 | 3–5 天 | CLI 可用；注入面关闭；秘密面上锁；机制归人类所有；liveness 全链 | 冻结新波次；固定基线 HEAD；产品仓保护规则 401 项澄清 | 16 动词 subprocess 契约测试绿；注入 canary 被忽略；secret scanning 三项 enabled；CODEOWNERS+评审≥1；conductor/audit 转绿；红队 20 次绕过全拦 | 逐卡 revert |
| **W1** | 单一事实源与状态硬化 | ~1 周 | schema 被代码消费；状态机有转移表/单写者/epoch/哈希链；merge 后自动终态；事件日志对账 | W0 全绿 | 手写字段列表=0；第一张 FMC-E 卡诞生；篡改注入三试验全部被抓；事件-投影 diff=0 | 逐卡 revert；状态写路径可切回本地 CAS |
| **W2** | 信号保真度层 | 1–2 周 | redproof/holdout/RHG/故障注入/flaky/mutation 五传感器上线且有数 | W1 全绿；Bench 仓写权限配置完成 | T→I→V 全流程演示；14 类 fault 召回≥0.75；flaky<2%；Pass^3 管线出数；RHG 有窗口值 | 传感器全部只读化（关开关即回到 W1 判定面） |
| **W3** | 规格层与合入闸门 | 1–2 周 | fail-closed；AC 机器可判定；pin/profile 控制面化；D1-D13；契约推导；对抗规格评审 | W2 全绿且 RHG 窗口均值 <0.15 | 无卡 PR 拦截演示；pin 三故障注入全红；一波次 blocked_by 100% 推导；D1-D13 红队全拦；语义冲突被 merge_group 拦 | 每门可独立降级为 warn（除 provenance/pin 外） |
| **W4** | 自治化与优化层 | 2–4 周 | dispatcher 闭环；升级环首跑+分环；router/rubric shadow；Sleep 草案；红线激活 | **Pass^3(critical)≥θ1 且缺席率=0 且崩溃率≤θ2 且回收率≤θ3 且 RHG 窗口均值<0.10 且召回≥0.85，且持续 30 天** | 48h 无人类 N 张 trivial 卡自动闭环；升级环首跑报告+24h 观察；成本看板出数；优化器产物 100% 走 PR | 停 cron / 阈值归零 / freeze 布尔 |
| **WT** | 永久轨道 | 持续 | 红队常驻；canary 夜跑；placebo 检测；抑制趋势；漂移看门狗；月度人类抽标注 | W2 起 | escape count 月报；召回率只升不降 | — |

**θ 初始值建议**（W2 出口前用真实数据校准后写死进 policy.yml）：θ1=0.6（critical 类 Pass^3 下限）、θ2=0.02、θ3=0.10。这些值在 W2 结束时有第一批真实分布后再定稿——先定值是猜测，后定值是测量。

---

## 7. 波次详表

### 7.1 W0 · 止血与确权（3–5 天）

**目标**：消灭全部"已知的假绿与失控点"；CLI 可用；机制所有权回到人类；四条病链转绿。
**入口条件**：冻结新波次与新卡；固定基线 HEAD（记录 `git rev-parse HEAD`）；澄清两个遗留 UNKNOWN：产品仓 main-protection ruleset 详情（V-709 401）、`GH_TOKEN/SCRIBE_GH_TOKEN` 实为 App 还是个人 PAT（V-411/P-14）。

**波次内分工（8 个卡包，角色→路径→产出）**：

| 卡包 | 内容与产出 | 角色 | paths | 依赖 |
|---|---|---|---|---|
| W0-1 | **loopd CLI 修复（critical，建议 race 双 impl）**：`loopd/cli.py` argparse 派发（verb→HANDLERS[verb]）；入口显式 `CFG()` 物化全局；16 动词统一结构化 JSON 输出（`{ok,verb,card,error}`）；`tests/test_cli_contract.py`：16 动词 ×（`--help` exit 0 + 一条成功路径 + 一条拒绝路径）全部 subprocess 真入口；`gates/gate_doc_drift.py`（P-continue/prompts 动词 ↔ HANDLERS ↔ 路由三方一致）。产出：可用 CLI + 契约测试进 required checks | impl×2（race）+ verify | `loopd/**`、`tests/test_cli_contract.py`、`gates/gate_doc_drift.py` | 无 |
| W0-2 | **gate 搜索注入消除**：policy.yml `search_dirs` 只留 `${LOOP_ROOT}/gates`；run_gates 启动打印各 gate 解析后的绝对路径与其文件 sha256；启动完整性断言（`.loop-control` 存在、`run_gates.py` 存在、HEAD == inputs.loop-sha，否则 exit 3）；profile 过渡双读：inputs.profile ≠ products.yml[repo].profile → fail（W3 彻底改控制面单读）。产出：注入不可能 + 可审计日志 | impl + verify | `policy.yml`、`gates/run_gates.py`、`products.yml` | 无 |
| W0-3 | **平台确权（人类执行，1 天内）**：开启 secret scanning + push protection（repo 与 org 两级）+ dependabot（`github-actions` + `pip` 双生态，周频）；新增根 `.github/CODEOWNERS`：`gates/ conductor/ loopd/ lenses/ policy.yml products.yml prompts/ settings/ bench/ UPSTREAM.yaml ROUTING.yaml CHARTER.md DECISIONS.md .github/workflows/ .loop/schemas/ .loop/exceptions.yml` → `@human`；ruleset `main-protection` 评审数 0→1 且 require_code_owner_review=true；全部变更落 `settings/*.json`（settings as code）后 API 应用。产出：平台侧人类所有权闭环 | **人类 H**（机械操作可由 agent 生成 PR，人类 merge） | `.github/CODEOWNERS`、`settings/**` | 无 |
| W0-4 | **gitleaks gate + 出站过滤（SAFEGUARD-14）**：`gates/gate_secrets.py`（PR diff 范围 `gitleaks git --log-opts`，pin **≥8.30.1**）；`conductor/outbound.py` `scrub_outbound(text)` 插进 materialize/findings/loopd 全部写 GitHub 路径，内部用 **`gitleaks stdin`**（新语法），命中→拒发+Incident（不静默 redact）；`.gitleaks.toml` allowlist 入 CODEOWNERS；本 gate 不接受任何 `fake-green-ok:` 豁免。产出：秘密零出站 | impl + verify | `gates/gate_secrets.py`、`conductor/outbound.py`、`conductor/materialize.py`、`conductor/findings.py`、`loopd/loopd.py`（写路径调用点）、`.gitleaks.toml` | 无 |
| W0-5 | **Semgrep 自研规则 v1（引擎选型含 Opengrep 评估）**：`rules/loop/` 9 条——`unpinned-uses`（放行 `./` 本地引用，直接治愈 smoke f-a）、`silent-swallow`、`nondeterminism-in-conductor`、`cas-bypass`（绕过 write_block 的直写）、`env-direct-read`（CFG 之外的 os.environ）、`dispatcher-orphan`（注册不可达，静态拦截 BROKEN-01 同类）、`mechanism-in-product`、`lens-missing-strict`（缺 pipefail）、`subprocess-shell-true`；`gates/gate_semgrep.py`：**必须 `--error`**（默认有 finding 也退 0 是陷阱）+ 退出码翻译表（1→FAIL；2/3/4/5/7/8/13/99→ERRORED）；自研规则-only，不接 Cloud、`--metrics off`；评估 Opengrep 作为引擎备选（决策入 ADR）。产出：机制不变量声明式化第一批 | impl + verify | `rules/loop/**`、`gates/gate_semgrep.py` | 无 |
| W0-6 | **立法包**：CHARTER 增补 N16-N27（按 §4 结论八修订文本）+ N28-N35（优化层红线）+ G6/G7；`.loop/exceptions.yml` 空表（schema 先行，CODEOWNERS=人类）；`gates/gate_ratchet.py`（阈值/必填检查集合/评审数只许收紧，对比 base vs head 配置）；no-fake-green 模式表扩展（`gitleaks:allow`、`# nosemgrep`、`# pragma: no mutate`、stryker-disable、jscpd ignore、spectral except、`# noqa`、`@ts-ignore` 等抑制语法一律纳入，例外必须引用有效 EXC-id）；smoke f-a 规则修正（允许 `./` 本地引用）且 **smoke 红=阻断合并，禁止 known-failure 状态**；actionlint + pinact 进 CI（workflow 静态检查 + pin 校验，cron 语法门禁由 actionlint+自定义规则承担）。产出：宪法层 + 棘轮 + 例外制度 | impl（文本）+ **人类 H（批准）** | `CHARTER.md`、`.loop/exceptions.yml`、`gates/gate_ratchet.py`、`lenses/no-fake-green.sh`、`.loop/smoke.sh`、`.github/workflows/pr-ci.yml` | W0-3 |
| W0-7 | **liveness 与病链修复**：`.loop/liveness.yml` 全链登记期望周期与阈值（template-sync 30h/audit 30h/upgrade 180h/tick 1h/canary 2h/drift 8h/scribe 30h/nightly-rubric 30h），liveness 改读配置；诊断并修复 conductor 4 连败与 audit 3 连败（根因写入波次报告，禁止"重启就好了"式关闭）；audit 修复后跑出**首次成功**并产出真实 finding 流程空转验证（允许 0 finding，但状态文件/日志/配额记账必须落盘）；HUMAN-TODO.md 改为 tick 自动生成 digest（四问）。产出：全链可观测 + 病链转绿 | impl + verify | `.loop/liveness.yml`、`conductor/tick.py`、`conductor/findings.py`（如涉根因）、`.github/workflows/audit.yml`（如涉根因）、`conductor/scribe_report.py` | 无 |
| W0-8 | **供应链基线**：dependabot 首批 PR 走完整门禁验证；`actions/create-github-app-token` v1.10.0/v1.12.0 → v3.x 的升级经升级环通道登记（UPSTREAM.yaml 入册，min_age 7 天）；确认 `GH_TOKEN`/`SCRIBE_GH_TOKEN` 身份性质，个人 PAT 一律替换为 App token。产出：依赖更新自动化 + token 身份清白 | impl + **人类 H（换 token）** | `UPSTREAM.yaml`、`.github/dependabot.yml` | W0-3 |

**W0 出口判据（机器可验证，逐条按 §5.2 协议留档）**：

| # | 判据 | 验证命令（复核方式） | 期望值 |
|---|---|---|---|
| E0-1 | CLI 契约 | `python3 loopd/loopd.py help; echo EXIT=$?` + `pytest -q`（含 ≥16 条 subprocess 入口用例）+ CI run ID | EXIT=0，16 动词列出；测试全绿 |
| E0-2 | 注入关闭 | 注入 canary：产品仓 PR 放 `gates/gate_evil.py` 与 `.loop/gates/gate_evil.py` → 两 PR 的 gates job 日志 | 两文件均未出现在解析清单；日志含告警；job 红或按设计忽略（以设计文本为准） |
| E0-3 | 平台确权 | `gh api repos/Cloudbird-Software/loop --jq .security_and_analysis`、`cat .github/CODEOWNERS`、`gh api repos/.../rulesets/20052299` | 三项 enabled；机制路径 owner=@human；评审数≥1 且 code_owner=true |
| E0-4 | 秘密拦截 | canary PR 植入测试密钥 + 出站 scrub 演示 | gate 红 run ID；拒发 Incident issue 链接 |
| E0-5 | Semgrep 规则 | `semgrep --config rules/loop --error --json` 对故障样本库（W0-5 附带）与 main | 样本库 9/9 命中；main 0 误报 |
| E0-6 | 立法生效 | `grep -c '^N[0-9]' CHARTER.md`、ratchet canary（阈值下调 PR） | N16-N35 在册且 last-human-edit≠PENDING；canary 红 run ID |
| E0-7 | 病链转绿 | `gh run list --workflow=conductor.yml --limit 20`、`gh run list --workflow=audit.yml --limit 5` | conductor 连续绿 ≥48h；audit ≥1 次 success |
| E0-8 | **红队验收** | `WAVE-00-REDTEAM`：20 次"最短路径让门禁变绿而不真实现"尝试（异家族模型） | 20/20 被拦（每次：尝试 PR + 拦截 check 链接）；任何一次绕过 → 新 fault 入库 + W0 不得关闭 |

**回滚**：每卡包独立 revert；W0-6 立法包回滚 = CHARTER revert PR；W0-3 平台项无回滚必要（属纯增益）。

---

### 7.2 W1 · 单一事实源与状态硬化（约 1 周）

**目标**：schema 成为唯一事实源；状态机获得转移表、单写者、epoch fencing、哈希链完整性；merge 后自动终态；事件日志与投影对账。
**入口条件**：W0 八条判据全绿。

| 卡包 | 内容与产出 | 角色 | paths | 依赖 |
|---|---|---|---|---|
| W1-1 | **schema 单一事实源**：`.loop/schemas/*.json` 用 datamodel-code-generator 生成 `conductor/schema_types.py`（CI 校验生成物与源一致）；loopd/conductor/gates 全部改从生成物读；`gates/gate_schema_singlesource.py`（禁手写字段列表，V-601 那 9 个字段为首批监控）；读者接受 {N, N-1}，未知版本 → `SCHEMA_UNSUPPORTED` 显式错误；**统一双卡方言**（P-11）：字段集并集立法 + 旧卡迁移脚本（loop 仓与产品仓存量 issue 一次性重写）。产出：一份 schema，处处生效 | impl + verify | `.loop/schemas/**`、`conductor/schema_types.py`、`loopd/loopd.py`、`conductor/*.py`、`gates/gate_schema_singlesource.py` | W0-1 |
| W1-2 | **声明式状态转移表**：`loopd/domain/transitions.py` TRANSITIONS（含实测状态 ready/claimed/in_progress/in_review/done/closed/unconfirmed/race_lost + 新增 respec/stalled/orphaned）；每转移带 guards；非法转移 `IllegalTransition`；穷举性质测试（states × events 全空间有定义）；README 自动生状态图。产出：非法转移物理不可发生 | impl + verify | `loopd/domain/**`、`tests/test_transitions.py` | W0-1 |
| W1-3 | **意图收口（单写者）**：新 App `AGENT_APP`（权限：contents:write 限 `refs/heads/card/*` + pull_requests:write；**issues:read-only**）；`.github/workflows/intent.yml`（repository_dispatch `loop-intent`）：接收 agent 意图 → CONDUCTOR_APP 执行状态写 → agent 轮询结果；loopd 全部状态写改意图提交（保留本地 CAS 为快速失败）；**done/verified 只能由 CI 身份写入**（h_done 上限 in_review）。产出：状态写路径唯一身份 | impl + verify + **人类 H（建 App）** | `.github/workflows/intent.yml`、`loopd/loopd.py`、`conductor/intent*.py` | W1-2 |
| W1-4 | **epoch fencing + 哈希链**：卡增 `lease_epoch=attempt`；分支命名 `card/<id>/e<epoch>`；每次写携 epoch，写前校验否则 `StaleLeaseError` 自杀；`gates/gate_epoch.py`（PR head 分支 epoch ≠ 卡 epoch → fail + 自动关 PR）；卡块增 `integrity:{seq,prev,writer,nonce}`；`conductor/state_audit.py`（timeline/userContentEdits 重放校验，断链/非法 writer → quarantined + 冻结 sandbox + Incident）；tick 增 state_integrity_audit 步。产出：被回收者写不进、篡改必现形 | impl + verify | `loopd/loopd.py`、`gates/gate_epoch.py`、`conductor/state_audit.py`、`conductor/tick.py` | W1-3 |
| W1-5 | **merge-completion reconciler**：订阅 `pull_request.closed(merged)` 与 merge queue 结果：merged → 卡置 done + 记 merged_sha + 触发 unblock_deps；被踢出 → ready(attempt+=1, note)；reaper 的 any→ready 限定 `{claimed,in_progress}`。产出：卡终态自动化（人类不再手动关卡） | impl + verify | `conductor/tick.py`、`conductor/materialize.py` | W1-2 |
| W1-6 | **append-only 事件日志**：`loop-events` orphan 分支，每条一行 JSONL（actor/card/epoch/event/before/after/cause/prev_hash）；tick 每跑做事件-投影对账，diff≠0 → Incident。产出：回放/取证/指标底座 | impl + verify | `conductor/events.py`、`conductor/tick.py` | W1-3 |
| W1-7 | **loopd 分层重构**：`cli.py / usecases/ / domain/（纯函数零 IO）/ ports.py / adapters/`；迁移期间由 W0-1 契约测试守护行为不变；完成后 loopd.py 退役为薄入口。产出：上帝对象拆解 | impl + verify | `loopd/**` | W0-1、W1-2 |
| W1-8 | **身份外置第一步**：materializer/派卡时把 `model/family` 写入租约记录（agent 只读）；policy.yml 增 `models: {id→family→vendor}` 映射；gate_heterogeneity 改读租约记录 + 升 family/vendor 级（critical 要求 vendor 不同，spec-test≠impl family 立法入 N22）；`verifier_model` 从租约取而非 env。产出：异构不再吃自报字符串 | impl + verify | `conductor/materialize.py`、`gates/gate_heterogeneity.py`、`policy.yml`、`ROUTING.yaml` | W1-3 |
| W1-9 | **materializer 事务化**：卡 ID 内容派生 `CARD-<wave>-<idx>-<sha8>`；upsert 语义（先搜后建）；`materialized.json`（expected/created/completed_at 最后写）；tick 增 materialize_repair；`gate_wave_immutable`（已物化 wave 文件禁改）。产出：波次不再静默残缺 | impl + verify | `conductor/materialize.py`、`conductor/tick.py`、`gates/gate_wave_immutable.py` | W1-1 |
| W1-10 | **tick supervisor 化**：Step 注册表（deps 拓扑排序 + 独立超时 + 独立异常捕获 + 每步 last_success_at 指标）；liveness 改步骤级；任一步失败 `TICK_STEP_ERRORED` 且整体 exit 1（不静默）。产出：一步死不连坐 | impl + verify | `conductor/tick.py` | W0-7 |

**W1 出口判据**：

| # | 判据 | 验证方式 | 期望值 |
|---|---|---|---|
| E1-1 | schema 单源 | `grep -rn 'lease_until\|fingerprint\|occurrences' --include='*.py' loopd/ conductor/ gates/ | grep -v schema_types | wc -l` | 手写字段列表=0；CI 校验生成物 hash 一致 |
| E1-2 | 转移表 | `pytest -q tests/test_transitions.py` | 全空间有定义；非法转移全抛 IllegalTransition |
| E1-3 | **FMC-E 首卡** | 一张 standard 卡：materializer 建 → agent CLI 领 → 干活 → done → CI verify → merge queue 合入 → 自动终态，全程录 run ID 链 | 全流程无人类触碰；verdict 由 CI 身份发布且 head_sha 绑定；**这是全案最重要的一条判据** |
| E1-4 | 篡改三试验（破坏性） | (a) agent 身份直改 issue state；(b) 旧 epoch push；(c) 绕 CLI 直接 gh 写 | 三试验全部被 quarantine/fail/对账告警（run ID×3） |
| E1-5 | 事件-投影一致 | tick 对账日志 | diff=0 连续 72h |
| E1-6 | tick 隔离 | 人为注入一步异常 | 其余步骤正常完成；该步 TICK_STEP_ERRORED 上报；整体 exit 1 |
| E1-7 | 身份外置 | 篡改沙盒 LOOP_MODEL env 后领 verify 卡 | 领卡/门禁判定不受影响（读租约）；run ID |

**回滚**：意图收口可整体切回本地 CAS（feature flag `LOOP_INTENT_MODE=local|remote`）；其余逐卡 revert。

---

### 7.3 W2 · 信号保真度层（1–2 周）

**目标**：装上五个传感器——red-first proof（测试是真的）、holdout+RHG（实现是真的）、fault injection（门禁是真的）、flaky 治理（重试是真的）、mutation（断言是真的）——并全部产出第一批真实读数。
**入口条件**：W1 全绿；Bench 仓（org 内已存在）配置好"holdout 存放 + agent 不可写"的权限；`LOOP_INTENT_MODE=remote` 稳定 72h。

| 卡包 | 内容与产出 | 角色 | paths | 依赖 |
|---|---|---|---|---|
| W2-1 | **T-card 配对 + redproof**：materializer 对 standard/critical I-card 自动配对 T-card（`blocked_by` 写入）；T-card paths 只含 `tests/**`，I-card `forbid_paths` 自动含 T 卡 paths；`json redproof` 块（base_sha/tests[]/exit_code/assertion_line/runs≥3/runner_image/model_family）；`gates/gate_redproof.py`：在 base 上独立重跑，断言确实失败且失败原因为断言失败（非 import/语法错——假红同样拒）。产出：空洞测试三类（写完即过/无断言/环境错红）结构性拦截 | spec-test 角色立法 + impl + verify | `conductor/materialize.py`、`gates/gate_redproof.py`、`.loop/schemas/redproof.json`、`loopd/loopd.py`（h_done 要求块） | W1-1、W1-9 |
| W2-2 | **holdout 入 Bench 仓**：`loopd holdout-submit`（agent 无 Bench 写权，CONDUCTOR_APP 代写 `Bench/holdout/<product>/<card_id>/`，manifest 含 sealed_at/author_family）；reusable-gates 增独立 holdout job：checkout Bench@pin 只取对应目录，**输出脱敏**（CI 界面只回显 `HOLDOUT FAIL: AC-3 (1/4 assertions failed)` 聚合行，全量日志入权限受控 artifact）；`conductor/holdout_quality.py`（holdout 与可见套 AST 相似度+分支覆盖差异，不足则 T 卡打回）；gate 校验 `sealed_at < I-card.claimed_at`。产出：实现方不可见的第二套判据 | impl + verify + **人类 H（配 Bench 权限）** | `loopd/loopd.py`、`.github/workflows/reusable-gates.yml`、`conductor/holdout_quality.py`、`gates/gate_holdout.py` | W2-1 |
| W2-3 | **RHG 指标**：`RHG = visible_pass_rate − holdout_pass_rate` 写 `.loop/metrics/rhg.jsonl`，按 model/family/tier 聚合进 plan inbox；分档动作（≤0.05 放行 / 0.05–0.15 `rhg-watch` 标签 / **>0.15 阻断并自动生成 claim 进 CHAIN-07** / 模型窗口均值 >0.10 → ESC-08 升档）。产出：奖励攻击的第一个量化读数 | impl + verify | `conductor/holdout_quality.py`、`.loop/metrics/**`、`conductor/tick.py`、`escalation.yml`（新） | W2-2 |
| W2-4 | **故障注入题库 + 门禁召回率**：`bench/faults/` 14 类（删断言/hardcode 期望/特判分支/mock 留壳/跳测试/降阈值/越界/吞错/删日志/迁移不可回滚/并发竞态/N+1/硬编码密钥/测试路径特化）+ manifest（expect_caught_by / must_not_be_caught_by）；`.github/workflows/gate-recall.yml` 周跑：patch→canary 仓临时分支→全量门禁→统计 overall/by_class/by_gate/zero_catch/false_positive；召回率进升级环**第五指标**（召回下降=劣化→pin_back）；`gate_meta.py` 立法：每 gate 必有阳性拦截测试 + 必被至少一个 fault 引用；tick `placebo_gate_detector`（30 天执行≥100 且拦截=0 → Incident，7 天内红队举证否则删除，N24）。产出：唯一"可证门禁够用"的数 | impl + redteam 角色立法 | `bench/faults/**`、`.github/workflows/gate-recall.yml`、`conductor/gate_recall.py`、`gates/gate_meta.py`、`conductor/tick.py` | W1 |
| W2-5 | **mutmut 进 bench（不阻断）**：配置 `[tool.mutmut]`（only_mutate=conductor/loopd/gates、do_not_mutate=tests、type_check_command=mypy 或 pyrefly、timeout 显式）；nightly 全量 + PR 复用缓存增量；**自写结果解析**（mutmut 无内建阈值退出语义——读 `mutants/` 结果 JSON 算分）；产出 mutation_score 作 bench 第五指标与 `assertion_gap`（断言缺失类存活体）计数；timeout→ERRORED 不算 fail/pass。产出：断言有效性的不可表演标量 | impl + verify | `pyproject.toml`（或 setup.cfg）、`.github/workflows/nightly-rubric.yml`（挂入）、`bench/metrics.py` | 无 |
| W2-6 | **flaky 治理**：`.github/workflows/flaky-detect.yml`（nightly 对 main 同 SHA×5 跑）→ `.loop/flaky/quarantine.yml`（≤14 天 + 自动开修复卡）；`gates/gate_flaky_budget.py`（flaky 率>2% → 冻结 merge queue）；verdict 块必须记录全部 attempt（runs[]），gate_verdict 校验与 CI 实际 run 数一致（隐藏失败=造假→claim）；同 head_sha 手工重跑>2 次 → `rerun-abuse`。产出：重试激励被定价 | impl + verify | `.github/workflows/flaky-detect.yml`、`.loop/flaky/**`、`gates/gate_flaky_budget.py`、`gates/gate_verdict.py`、`loopd/loopd.py` | W1-1 |
| W2-7 | **新 lens 上线包（R1/R5/R6/R8 宪法执行）**：vulture（conf=100 进 gate，注意**退出码 3=有发现**；80-99 进 lens；`.vulture-whitelist.py` CODEOWNERS 锁定）、semgrep-security lens（通用集运行时按 pin 拉取，不 vendored）、jscpd 跨仓机制复制（挂 drift.yml 遍历，`.jscpd.json` 的 ignore 数组——**无 .jscpdignore**，先做单仓实测再跨仓）+ prompts 去重；每新工具：全量扫描→指纹冻结进 `.loop/audit/baseline/<tool>.json`（accepted_debt）→只报新指纹；lens 退出码三分翻译表（无发现=[] exit 0 / 有发现 exit 0 / 崩溃或缺失 exit 1）；per-lens 记分卡与隔离降频（替换全局 throttle）；产物一律 `.loop/tools/<tool>/` 或 artifact（R8）。产出：审计面第一次真实扩张且不雪崩 | impl + verify | `lenses/*.sh`、`gates/gate_vulture.py`、`.github/workflows/drift.yml`、`.loop/audit/**`、`conductor/findings.py` | W0-5、W1 |
| W2-8 | **golden set 扩充 + Pass^k**：bench/replay 加入 ≥10 张真实历史卡（含失败卡与 reaper 回收卡）；基线重算（修 P-10 的 trivially green）；`bench/passk.py` 实现 Pass^k（critical 类 Pass^3）；bench 四指标→五指标（+mutation_score，W2-5 接入）。产出：有区分度的基线 + 统计判据管线 | impl + verify | `bench/**` | W2-5 |
| W2-9 | **例外登记实体化 + 抑制审计**：exceptions.yml 生效（EXC 不存在/过期/非人类署名 → 对应豁免失效）；tick `suppression_audit`（抑制总数趋势，单调升→finding）；单 PR 新增抑制>3 → tier 强制 critical。产出：例外成为稀缺资源 | impl + verify | `.loop/exceptions.yml`、`gates/gate_exceptions.py`、`conductor/tick.py` | W0-6 |
| W2-10 | **main-guard.yml**：`push: main` → 深度套件（全量测试+mutation 增量+canary 核心集）；红 → CONDUCTOR_APP 自动 revert PR + 自动合入 + Incident + 设 `MERGE_FROZEN=1`（required check `merge-not-frozen` 读取）。产出：main 薛定谔态终结 | impl + verify | `.github/workflows/main-guard.yml`、`.github/workflows/pr-ci.yml`（加 check） | W1 |
| W2-11 | **prompt 治理**：领卡写 `prompt_sha` 入卡并带入 VERDICT；基于现成 `promptfoo/` 建 P-continue/P3 关键指令回归套件（夜间跑）；prompts/ 已在 CODEOWNERS（W0-3）基础上升格为"prompt 变更必须附回归结果"。产出：prompt 变更可复现可归因 | impl + verify | `promptfoo/**`、`conductor/materialize.py`、`loopd/loopd.py` | W1 |

**W2 出口判据**：

| # | 判据 | 验证方式 | 期望值 |
|---|---|---|---|
| E2-1 | T→I→V 全流程 | 一张 standard 卡完整走：T 卡 redproof 在 base 失败（run ID-A）、I 卡合入后同测试通过（run ID-B） | A 失败原因=断言失败；B 通过；两 run ID 钉入波次证据 |
| E2-2 | holdout 脱敏 | 脚本+人工双查 holdout job 的 CI 界面输出 | 无断言内容/用例名/diff 泄漏；仅聚合行 |
| E2-3 | 门禁召回率 | `gh run view <gate-recall run>` + `bench/faults/report.json` | overall≥0.75；by_class 无 0；zero_catch_gates=[]；**任一漏拦 → W2 不得关闭** |
| E2-4 | flaky | `.loop/flaky/report.json` | flaky 率<2%；quarantine 条目带卡号 |
| E2-5 | 基线棘轮 | 新 lens 首跑：存量指纹全部冻结，第二日起只报新指纹 | finding 数 ≤8/日；baseline 只减不增 |
| E2-6 | Pass^k 与 RHG | `bench/passk.py`、`rhg.jsonl` | Pass^3(critical) 出数；RHG 窗口值出数（此时不定阈值，先观测） |
| E2-7 | mutation | `bench/metrics.py compare` | mutation_score 进指标表；assertion_gap 计数出数 |
| E2-8 | **红队验收** | 20 次偷懒提交（hardcode 期望/删断言/特判输入/mock 留壳，异家族模型） | 20/20 被 redproof/holdout/mutation/gate 之一抓住（链接×20） |

**回滚**：五个传感器全部只读化设计——关闭开关即回到 W1 判定面，无状态污染。

---

### 7.4 W3 · 规格层与合入闸门（1–2 周）

**目标**：fail-closed 一刀切；AC 机器可判定；pin/profile 收归控制面；D1-D13 全量；契约推导依赖；对抗规格评审；供应链 SBOM 棘轮。
**入口条件**：W2 全绿且 RHG 窗口均值 <0.15（高于此值说明证据层未稳，先修证据层）。

| 卡包 | 内容与产出 | 角色 | paths | 依赖 |
|---|---|---|---|---|
| W3-1 | **fail-closed 改造（P-1 根治）**：枚举全部 gate 的 SKIP 分支并分类：真条件不适用 → 显式 `GATE_SKIPPED`（exit 5，且该 gate 不得属 required 集合）；其余一律 FAIL；`gates/gate_card_provenance.py`：卡 issue author ∈ App 白名单（CONDUCTOR_APP/materializer bot）否则 FAIL；无 `Card: #NNN` 的 PR 仅允许白名单琐碎路径（`docs/**`、`assets/**`、README）+ `no-card` 标签，其余 FAIL；`LOOP_CI_BASE` env 兜底删除（P-8）。产出：无卡代码 PR 物理不可合 | impl + verify | `gates/gate_*.py`（SKIP 分支）、`gates/gate_card_provenance.py`、`policy.yml` | W2 |
| W3-2 | **AC 机器可判定**：acceptance schema 升级（id/statement/kind: exec\|holdout\|judgment/test_ref/must_fail_before/holdout_ref）；`gates/gate_ac_binding.py`（test_ref 可 collect；must_fail_before 须有 redproof；standard/critical 禁 judgment-only；≥1 条 holdout AC；孤儿 AC 拒）；materializer 物化时前置校验。产出：验收标准先可判定，再谈实现 | impl + verify | `.loop/schemas/**`、`conductor/materialize.py`、`gates/gate_ac_binding.py` | W2-1、W2-2 |
| W3-3 | **pin 完整性强化（P-6 三盲区）**：gate_conformance 增补——(a) 祖先校验：`git merge-base --is-ancestor <sha> origin/main`（在 .loop-control 内执行）；(b) 解析薄壳 `with: loop-sha` 并与 `uses:` SHA、LOOP.yml loop.sha 三方比对；(c) `with: profile` 值白名单校验（∈ products.yml 下发值）；`pins/allowed.json`（发布流程写入，CODEOWNERS 守护，pin 必须在白名单）。产出：自降级三条路全部封死 | impl + verify | `gates/gate_conformance.py`、`pins/allowed.json`、`.github/workflows/template-sync.yml`（发布写白名单） | W0-2 |
| W3-4 | **profile 控制面化（P-7 根治）**：products.yml 每条写死 profile；reusable-gates 从控制面读取并忽略产品侧任何声明；薄壳 `with: profile` 与 products.yml 不一致 → FAIL；LOOP.yml 删 `gates.profile` 字段（模板与 product-x 迁移）。产出：被审者不再选择审查强度 | impl + verify | `products.yml`、`.github/workflows/reusable-gates.yml`、`templates/product-x/**`、迁移 product-x | W3-3 |
| W3-5 | **diff 卫生 D1-D13**：`gates/gate_diff_hygiene.py` 全量实现（D3 改测试文件非 T 卡拒；D4 新抑制无 EXC 拒；D5 无 issue 号 TODO 拒；D6 阈值下调；D7 依赖非 allowlist；D8 action 未 pin；D9 pull_request_target+checkout head；D10 未声明最小 permissions；D11 未登记 secret；D12 超 tier 上限无 EXC；D13 二进制入库）；与既有 paths/diffsize/license 门去重（A3 公理：一缺陷类一真值源，合并而非并列）。产出：CI 配置即攻击面的立法执行 | impl + verify | `gates/gate_diff_hygiene.py`、`gates/gate_paths.py`（合并）、`gates/gate_diffsize.py`（合并） | W3-1 |
| W3-6 | **traceability 块**：PR body 强制 `json trace`（card/wave/spec_sha/ac_map/models/prompt_versions/attempts/usage/gateway_receipt 预留）；`gates/gate_traceability.py`（spec_sha 与控制面卡内容哈希比对——抓住"边做边改规格"）。产出：端到端归因 | impl + verify | `gates/gate_traceability.py`、`conductor/materialize.py` | W1-8、W2-11 |
| W3-7 | **契约推导依赖**：产品仓 `contracts/`（openapi/events/pacts/fixtures）规范化（lead 卡专属路径）；卡 schema 增 consumes/produces（contract:// 引用）；`conductor/depgraph.py`（推导 blocked_by + 环检测 + 孤儿契约检测；手写 blocked_by 与推导不一致 → 拒物化）；`gates/gate_contract.py`（契约变更须版本 bump+ADR+label+ESC-03；双跑期禁删旧版）。产出：contract-first 并行 | lead + impl + verify | `conductor/depgraph.py`、`gates/gate_contract.py`、`templates/product-x/contracts/**`、`conductor/materialize.py` | W3-2 |
| W3-8 | **对抗性规格评审**：`.github/workflows/wave-review.yml`（waves/** PR 触发）：确定性段（AC 可判定/契约冻结/diff 预算/回滚独立/路径不交叉/共享路径归属）+ 异家族强模型 checklist 段（复用 review.yml 的 Copilot 通道，输出 `json review-verdict` 绑 head_sha）；materialize 前置：无 PASS 且 sha 匹配的 review-verdict → 拒物化；**silent_auto_release 改为 AND review-verdict PASS**（窗口已从 W0 起 168h）。产出：AI 写的规格不再无人复核 | impl + verify | `.github/workflows/wave-review.yml`、`conductor/materialize.py`、`conductor/tick.py`、`prompts/P3-review.md` | W3-2 |
| W3-9 | **共享路径与分支寿命**：products.yml 增 `shared_paths`；非 lead 卡 diff 命中 → FAIL 且错误信息给"先提 lead 前置卡"指引；tick `branch_staleness`：`card/*` 分支 24h 未更新强制 rebase、48h 回收卡+删分支。产出：并行卫生自动化 | impl + verify | `products.yml`、`gates/gate_diff_hygiene.py`、`conductor/tick.py` | W3-5 |
| W3-10 | **供应链工具包**：syft SBOM 棘轮（`syft dir:. -o cyclonedx-json` → `jq -S` 规范化并剔除 timestamp/serialNumber → `.loop/sbom/<product>.lock.json`；新组件必须卡显式声明；syft pin ≥2026-03-19 版）；osv-scanner 离线（`--offline` + `--download-offline-databases` 快照入升级环托管；退出码映射含 **128=无包单独处理**；`--licenses` 联网，仅放 Lens 不进 Gate）；Spectral 契约治理（`rules/spectral/loop-contracts.yaml`：tier=critical≥2 AC、卡 paths 禁机制目录、products.yml 必填字段、shards lens 存在性预检；CI 屏蔽 scarf 遥测）；mutmut 增量 delta gate（改动文件 score ≥ baseline−5pt；新文件 ≥ floor；先看 killed 绝对数防删代码刷分）；`tools.lock.yml` 全部工具钉容器 digest，升级环统一 bump。产出：供应链与阈值单向性闭环 | impl + verify | `gates/gate_sbom.py`、`gates/gate_vuln.py`、`rules/spectral/**`、`gates/gate_mutation_delta.py`、`tools.lock.yml` | W2-5、W2-7 |
| W3-11 | **可逆性**：`gates/gate_flag.py`（`user_visible: true` 卡 diff 必须含 flags.yml 新条目：owner/expiry/default off；过期 flag tick 自动开清理卡）；卡增 `risk_class`（payment/auth/migration/external-comm/data-deletion）→ 双钥匙（异厂商 verify + staging 观察窗 + ESC-04 人类批准）。产出：高风险动作的制度化减速带 | impl + verify | `gates/gate_flag.py`、`flags.yml`（模板）、`conductor/materialize.py`、`escalation.yml` | W2-3 |

**W3 出口判据**：

| # | 判据 | 验证方式 | 期望值 |
|---|---|---|---|
| E3-1 | fail-closed | 无卡 PR 尝试改 `src/**`（红队）+ 无卡 docs PR | 前者 FAIL（run ID）；后者放行 |
| E3-2 | AC 绑定 | judgment-only standard 卡 + 孤儿 AC 卡 + 无 holdout AC 卡 | 三种全部拒物化（dry_run 日志×3） |
| E3-3 | pin 三注入 | pin 到非祖先 commit；`uses:`≠`loop-sha:`；profile 改 default | 三个 PR 全红（run ID×3） |
| E3-4 | 推导波次 | 一个完整波次走通 | blocked_by 100% 由 depgraph 推导；wave-review PASS 记录绑 head_sha |
| E3-5 | D1-D13 | 红队逐条绕过尝试 | 13/13 拦截（run ID×13） |
| E3-6 | 语义冲突实验 | 两卡各绿、合并语义冲突 | merge_group 层拦截（run ID）；main-guard 未触发即证明队列层有效 |
| E3-7 | SBOM 棘轮 | 新增未声明依赖 PR + 声明后 PR | 前者红；后者绿且锁文件同步 |
| E3-8 | **红队验收** | "攻击规格层"专项：改 AC 文本降标准、手写 blocked_by 伪造依赖、改 spec 后追认 | 全部被抓（trace spec_sha / depgraph 不一致 / wave-review 拒） |

**回滚**：除 provenance/pin 两门不可降级外，每门可独立降为 warn（policy.yml 单开关）；波次文件不可变，回滚=新波次。

---

### 7.5 W4 · 自治化与优化层（2–4 周，硬门控）

**目标**：dispatcher 闭环；升级环首次真实运行 + 分环发布；router/rubric shadow；SkillOpt-Sleep（Planner 审批点化）；优化层红线实体化。
**入口条件（全部硬指标，由 W2/W3 的测量管线产出，缺一不可）**：
- `Pass^3(critical) ≥ θ1`（建议 0.6，W2 数据校准后定稿）
- gate 缺席率（exit=2）== 0；gate 崩溃率（exit=3）≤ θ2（建议 0.02）
- reaper 回收率 ≤ θ3（建议 0.10）
- RHG 窗口均值 < 0.10
- gate 召回率 ≥ 0.85 且 placebo 清单为空
- 上述指标**连续保持 30 天**（防止冲线式达标）

| 卡包 | 内容与产出 | 角色 | paths | 依赖 |
|---|---|---|---|---|
| W4-1 | **dispatcher**：`conductor/dispatcher.py`——eligibility filter（角色/异构读租约/路径租约/依赖/预算/并发）；控制面写 `assignments/<sandbox>.json`（单写者消竞态），沙盒拉取执行；scoped token：`create-github-app-token` **v3**（`client-id` + `owner`/`repositories` 收窄到单仓，1h 过期，post 自动吊销）；背压（max_concurrent_sandboxes、每仓并发、API 令牌桶、日预算熔断）。产出：MANUAL-04/05 消解，系统首次自转 | impl + verify + **人类 H（建 App/配额度）** | `conductor/dispatcher.py`、`.github/workflows/dispatch.yml`、`policy.yml` | W3 全绿 |
| W4-2 | **升级环首跑 + 分环 + reconciler 合并**：canary 仓（product-x）先合 bump → 观察 24h（main-guard 无红 + T2 通过）→ 扇出其余仓；template-sync 与 upgrade 合并为单一"产品仓 reconciler"（pin 唯一决定者=升级环；template-sync 只补缺失/纠漂移且**保留现有 pin**；`concurrency: group=product-sync-${{ repo }}`）；pin_back 改 PR 化（修 P-12）；通用依赖升级从"只报告"升级为开 PR。产出：版本环第一次真实闭环 | impl + verify | `.github/workflows/upgrade.yml`、`.github/workflows/template-sync.yml`、`conductor/upgrade_ring.py` | W4-1 |
| W4-3 | **ACRouter（bandit 版，不训 LoRA）**：`conductor/router.py` 四接入点（会话启动 LOOP_MODEL/h_next 择优/race 互补双模型/reproducer 可行集内择优）；`memory.jsonl`（键=charter/tier/rule_id/语言/卡型，值=model/成本/结果/attempt/耗时）；SAFEGUARD-19 实体（硬约束可行集先行，择优只在集内；选择结果写卡并入 verdict 可审计）；KPI 三件套（单卡成本/critical 首过率/attempt 均值）。产出：模型选择从人工到数据驱动 | impl + verify | `conductor/router.py`、`.loop/router/**`、`ROUTING.yaml` | W4-1 |
| W4-4 | **Rubric shadow→拦截**：`rubrics/{task,wave,skill,claim}.yml`；verdict schema 扩 `rubric:{version,dims,scores,judge_model}`（schema 生成物先行）；`gates/gate_rubric.py`：shadow 2 周只记录，阈值达标后转拦截；SAFEGUARD-17（judge≠impl≠verify family）；`rubrics/claim.yml` 替换主观词表硬拒（改评分制+min_confidence 联动）。产出：二值验收多维化 | impl + verify | `rubrics/**`、`gates/gate_rubric.py`、`.loop/schemas/verdict.json` | W4-1 |
| W4-5 | **SkillOpt-Sleep（Planner 审批点化）**：基于 `microsoft/SkillOpt`（MIT，含 Sleep Preview；机制逐项核实：Validation Gate/文本学习率/负反馈缓冲区均属实）自建 `.github/workflows/skill-sleep.yml` 夜间挖掘 `.loop/archive/` + gripes.json → (a) skill 编辑候选 PR (b) **波次草案 PR**；人类早上审草案（48h silent 仅对 trivial 子集且 AND review-verdict）；`gates/gate_skill_delta.py`（单 PR skill 段落编辑数上限+必带负反馈记录）；`skills/` 三层目录（planning/functional/atomic，SkillX 纪律共用同一目录；注意 SkillX 论文自述弱模型过度模仿风险，技能注入量由 gate_skill_delta 封顶）。**Sleep 隐私纪律（核查新增）**：官方明示真实后端会把会话摘录外发且不保证脱敏——必须 harvest 后人工审查置 `reviewed:true` 才放行，或全程走自建 gateway 脱敏代理。产出：BROKEN-02 以"审批点化"方式消解——这是它被允许修复的唯一形态 | impl + verify | `.github/workflows/skill-sleep.yml`、`skillopt/**`、`skills/**`、`gates/gate_skill_delta.py` | W4-1 |
| W4-6 | **优化层红线实体化**：SAFEGUARD-14 `META_MUTABLE_PATHS` 白名单（排除 run_gates/bench/rubrics/policy 评分字段，复用角色阀门模式）；SAFEGUARD-15 评估三分 + holdout 哈希封存 + `lenses/eval-leak.sh`（bench 内容出现在 prompts/skills/注释 → 红）；SAFEGUARD-16 自进化产物必须走 Wave→Card→PR 全套（复用 OPEN_PR_ONLY 模式）；SAFEGUARD-21 tick 漂移看门狗（bench 指标与线上通过率背离超阈 → Incident）。产出：元层法律实体 | impl + verify | `gates/gate_meta_mutable_paths.py`、`lenses/eval-leak.sh`、`conductor/tick.py`、`CHARTER.md`（已在 W0 立法，此为执行体） | W4-4、W4-5 |
| W4-7 | **attestation（public 仓免费红利）**：verify 动作在 Actions 内跑并用 `actions/attest` 对 verdict 签名（predicate=自定义 verdict 类型，OIDC claim 绑 repo/workflow/commit/event）；`gates/gate_verdict_attestation.py` 验签（`gh attestation verify --owner`）；盲提交时序证据：blind_phase_commit 由控制面 workflow 以评论发布，gate 校验 `comment.created_at < test_run.started_at`。产出：身份与盲提的平台级证明（P0-5/P1-10 终局形态） | impl + verify | `.github/workflows/reusable-gates.yml`、`gates/gate_verdict_attestation.py` | W3 |
| W4-8 | **Meta-Harness 启动评估（决策点，非承诺）**：以前 7 个卡包的产物为输入做可行性评审：`meta/domain_spec_loop.md` 草案 + **官方 `stanford-iris-lab/meta-harness`（MIT）骨架适配**（核查修正：文档3 指定的 dkhanal 版与 angrysky56 fork 均不存在；tbench2-artifact 仓无许可证禁用）+ Pareto 第二维=（单卡成本/attempt/reaper 率/人类介入次数）；**单独 ADR 批准才启动**；硬性约束：演化循环不依赖任何 Required 非确定性外部推理服务。产出：一份 ADR | lead + **人类 H** | `meta/**`、`DECISIONS.md` | W4-6 |

**W4 出口判据**：

| # | 判据 | 验证方式 | 期望值 |
|---|---|---|---|
| E4-1 | 无人类闭环演示 | 48h 观察窗：dispatcher 自动完成 ≥5 张 trivial 卡 | 每张卡证据链完整（FMC-E 全项）；人类介入次数=0（事件日志复核） |
| E4-2 | 升级环首跑 | `gh run list --workflow=upgrade.yml` + bump PR + 24h 观察记录 | 首跑成功；canary 仓先合记录；扇出记录；无自动合并（PR 列表复核） |
| E4-3 | 成本看板 | gateway receipts 对账 | 每类卡 `usd_per_solved_task` 出数；receipt 与 trace 块 100% 对得上 |
| E4-4 | router/rubric 合规 | memory.jsonl + rubric shadow 报告 | router 选择 0 次越可行集（SAFEGUARD-19 审计）；judge 异构 100% |
| E4-5 | 红线审计 | 优化器产物全清单 | 100% 经 PR 合入（SAFEGUARD-16）；eval-leak 0 命中 |
| E4-6 | **30 天保持** | 入口六指标日度快照 | 30 天无回退；任一破线 → W4 冻结回到 W3 判定面 |

**回滚**：停 cron（dispatcher/skill-sleep/meta-search 各独立开关）；rubric/router 阈值归零=等价关闭；`policy.yml freeze.all=true` 一键全停（kill switch）。

---

### 7.6 WT · 永久轨道（W2 起持续运行）

| 轨道 | 内容 | 节奏 | 健康判据 |
|---|---|---|---|
| 红队常驻 | 角色 `redteam`：KPI=escape count（门禁放过的真实缺陷数）；每个逃逸缺陷必须回送一条新 fault 入 `bench/faults/`（召回率棘轮只升不降） | 持续 | escape count 月报下降或稳定低位 |
| canary 夜跑 | 12 条故障用例对真实门禁 runner 夜跑；未拦截 → page 人类 + 冻结自动放行 | 每晚 | 拦截率 100% |
| placebo 检测 | 30 天零拦截门禁 → Incident → 红队 7 天举证否则删除（N24） | 每周 | 零拦截清单为空或有 ADR |
| 抑制趋势审计 | 抑制总数/单 PR 新增数趋势 | 每 tick | 单调不升 |
| 漂移看门狗 | bench 指标 vs 线上真实通过率背离 | 每日 | 背离<阈值（SAFEGUARD-21） |
| 人类抽标注 | 每月随机 20 条 finding 人工标注，校准 per-lens precision/adoption | 每月 | 每 lens adoption>0.35 |
| 月度对账 | 事件日志 vs 投影 vs issue 状态三方对账 | 每月 | diff=0 |

---

## 8. 组织分工与预算

### 8.1 人类职责清单（全部职责，无第六项）

| # | 职责 | 形式 | SLA |
|---|---|---|---|
| H1 | products.yml 变更批准 | 系统生成 PR → 人类 merge | 24h |
| H2 | EXC 例外签发与续期 | exceptions.yml PR（CODEOWNERS 强制人类） | 24h |
| H3 | CHARTER/宪法层修订 | 人类 PR + last-human-edit 标记 | 无（主动行为） |
| H4 | risk_class 双钥匙批准 | ESC-04 通知 → 批准/否决 | 24h，超时停机 |
| H5 | 每日 digest 阅读（四问） | HUMAN-TODO.md 自动生成 | 15 分钟/日 |

超时纪律：`on_sla_breach: freeze_merge_queue`——系统等待人类时停机，不继续产出。

### 8.2 agent 角色矩阵（波次内分工原则）

| 角色 | 职责 | 模型档 | 关键约束 |
|---|---|---|---|
| plan | 波次拆分、卡规格 | frontier | 只能提波次 PR（角色阀门）；规格必过 wave-review |
| lead | 契约/共享路径 | frontier | 独占 contracts/**、shared_paths |
| spec-test | T 卡/验收测试/holdout | workhorse，family≠impl | 对 tests/** 之外的 paths 无写权 |
| impl | 实现 | workhorse（trivial 可 cheap） | 对 tests/**、机制路径无写权；epoch 绑定分支 |
| verify | 验收判断 | frontier，vendor≠impl（critical） | 只有否决权（N19）；verdict 必须 CI 身份发布 |
| reviewer/reproducer | claim 生产/复现 | frontier，互异 | 三态裁决；不可自证 |
| redteam | 攻击验收 | frontier，异家族 | KPI=escape count |
| mechanism | loop 自身机制卡 | workhorse + 人类 CODEOWNER 评审 | meta profile 门禁全集 |

### 8.3 预算护栏

- 卡级：`budget:{max_attempts, max_tokens, max_usd, max_wall_min}` 任一超限 → respec 或 escalate（按 tier）。
- 组织级：日预算 → ESC-05 freeze_all；API 配额余量 <20% → 自动降级非关键步骤。
- 记账：一律 gateway receipt（N27）；trace 块只引用 receipt id。
- runner 经济：public 仓 Actions 免费是当前最大红利；W4 若上 self-hosted dispatcher，注意 private 仓 self-hosted 自 2026-03 起有平台费——公开仓不受影响，预算时按实际仓属性核算。

---

## 9. 风险登记册与"不做"清单

### 9.1 风险登记册（前 8 项）

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R-1 | **机制公开**：public 仓使攻击者（含未来失控的 agent）可读全部规则 | 中 | 秘密零出站（W0-4）；身份/租约外置（W1）；签名与 attestation（W4-7）；年度复评是否转 private（届时 push ruleset 可用，ADR 已留位） |
| R-2 | 单产品仓样本过小：RHG/Pass^k/recall 早期统计功效不足 | 高 | θ 值先在 W2 用 replay+注入数据校准；所有比率指标附样本量，<min_samples 不决策（沿用 R12-7 纪律） |
| R-3 | GitHub 定时任务不可靠（延迟/丢弃） | 中 | liveness 按事件时间判定（W0-7）；关键语义不依赖"每天必跑"（配额/轮转容忍缺跑） |
| R-4 | Team plan 功能边界（push ruleset 不可用于 public；attestation 私有仓受限） | 低 | 已在各波次按 public 现实设计；转 private 决策点入 ADR |
| R-5 | Copilot premium 限额限制 review 吞吐（max_reviews_per_day=6 的背景） | 中 | review 不卡合并线（required_check=false）已是正确设计；W4 router 把 review 纳入成本优化 |
| R-6 | 并发上来后 API 次级限流 | 低 | dispatcher 令牌桶（W4-1）；GraphQL 精选字段；当前余量 4986/5000 |
| R-7 | W1 状态收口迁移期双写不一致 | 中 | `LOOP_INTENT_MODE` 开关 + 对账告警 + 72h 观察窗（W2 入口条件） |
| R-8 | 红队自身成本（每次验收 20 次攻击 ≈ 20 张 frontier 卡） | 低 | 攻击清单模板化；canary 仓隔离；红队卡走 cheap 档+frontier 复核 |

### 9.2 不做清单（终裁，十条）

1. **不修 BROKEN-02**（Planner 自动调度）——W4-5 以"审批点化"消解，此前人工触发是特性。
2. **不给 silent_auto_release 扩围**——只收缩（168h+前置+review-verdict AND+观察窗+周配额）。
3. **不给升级环加自动合并**——实测无此行为，立法禁止（canary 先合+24h 观察+扇出是唯一形态）。
4. **不接 Semgrep Cloud、不 vendored 官方规则**（public 仓许可证禁止；自研/Opengrep 评估）。
5. **不引入任何 Required 级非确定性推理服务依赖、不引入 comet 状态机、不引入 FastContext 自托管推理端**（官方仓 404，仅镜像）。
6. **不在 Pass^k 达标前引入任何自优化组件**（Meta-Harness/SkillOpt/ACRouter 训练态）。
7. **不让任何非确定性输出进 required check**（LLM 评审永不卡合并线，只行使否决与 Finding）。
8. **不允许"已知失败"状态存在**（smoke/test/gate 红只有两条路：修，或删并开 ADR）。
9. **不在产品仓落地任何机制副本或图缓存**（N14 无例外；图缓存只走 Actions cache/artifact）。
10. **不让 agent 持有规则/白名单/阈值/例外的写权限**——这些路径全部 CODEOWNERS=人类，无例外通道（N21 是其中唯一连 EXC 都不设的）。

---

## 10. 附：引用与外部事实核查备注

本文涉及的外部工具与平台能力均以 2026-07-31 的公开资料核查为准，关键条目：Semgrep CE v1.172（`--error` 必需；Rules License v1.0 内部专用；Opengrep 为 LGPL 分叉备选）；gitleaks ≥v8.30.1（CVE-2026-63728；`gitleaks git/dir/stdin` 新语法；维护转入安全补丁模式）；jscpd v5（Rust 重写；ignore 用 `.jscpd.json`）；syft ≥2026-03-19（解压炸弹 CVE；CycloneDX 输出需 `jq -S`+剔除 volatile 字段规范化）；osv-scanner v2.4.0（`--offline`+`--download-offline-databases`；exit 128=无包；`--licenses` 依赖 deps.dev 联网）；TruffleHog v3.96（AGPL；`--results=verified --fail`→exit 183；verified 必须联网）；Spectral v6.16.2（scarf 遥测需屏蔽）；oasdiff ≥v1.26.1（注入口 CVE；`review:false`）；mutmut v3.7.0（活跃；无内建门禁退出语义需自解析；需 fork）；Stryker v9.6.1（`break` 默认 null 必配）；vulture v2.16（exit 3=有发现）；knip v6.27（depcheck/ts-prune/unimported 均已归档）；actionlint v1.7.12 / pinact v4.0.0。

AI 层项目核查（2026-07-31）：Outlines v1.3.2（Apache-2.0，活跃；托管 API 仅 JSON-Schema 子集约束）；codebase-memory-mcp 真实项目为 `DeusData/codebase-memory-mcp`（MIT；158 AST+约 10 LSP 级，文档3 数字已修正）；Meta-Harness 论文 arXiv:2603.28052（消融数字属实），官方实现 `stanford-iris-lab/meta-harness`（MIT；tbench2-artifact 无许可证），**文档3 指定的 dkhanal 版与 angrysky56 fork 均不存在**；SkillOpt 为 `microsoft/SkillOpt`（MIT，含 Sleep Preview；真实后端外发会话摘录须人工审查 `reviewed:true`）；comet 为 `rpamis/comet`（MIT beta；Pass^k= k 次全过，文档3 的 rubric 四维系自拟）；ACRouter 论文 arXiv:2606.22902（代码+CodeRouterBench+LoRA 权重开源，权重 Apache-2.0，仓库 LICENSE 待确认）；FastContext 论文 arXiv:2606.14066（**官方仓 404**，仅社区镜像）；SkillX 为 `zjunlp/SkillX`（MIT；弱模型过度模仿可致负收益）；AGP 实为《Autogenesis》arXiv:2604.15034（`DVampire/Autogenesis`，MIT；resource.yml 字段系文档3 自拟）；TextGrad 已停更（2025-07 最后推送，仅作后端参考）。

GitHub 平台：push ruleset 路径限制仅 Team+ private/internal（public 任何 plan 不可用）；artifact attestation public 免费（GHEC 私有仓可用）；merge queue org public 免费；secret scanning+push protection public 免费（org 新建 public 仓需手动开）；OIDC immutable sub claim 2026-07-15 起新仓默认；`job.workflow_sha` 是 reusable workflow 自指 checkout 的官方变量（注意是 `job.` 前缀）；`create-github-app-token` v3.2.0（client-id + owner/repositories 收窄；1h token；post 吊销）；public 仓 Actions 分钟免费；Team 仓 3,000 分钟/月；private 仓 self-hosted 自 2026-03 起 $0.002/分钟平台费（public 不受影响）。

**第一批次的全部仓库实测证据**（七批次报告 + 公开仓原文复核）已于 2026-07-31 留档，任何"实测确认"条目均可用相同命令复核；随仓库演进，本文结论应以新的对账实测刷新（建议每个波次结束时重跑批次 0-6 的子集）。
