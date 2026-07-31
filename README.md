# loop — LOOP 体系控制面

> **loop 是控制面（机制），产品仓是数据面（内容）。**
> loop 仓持有全部机制——门禁、lens、conductor、loopd、提示词、settings——
> 产品仓只持有对 loop 的 pin 引用，不放任何机制副本（CHARTER N14）。

## loop 是什么

- **是**：LOOP 体系的控制面仓库。提供门禁（`gates/`）、确定性检查器（`lenses/`）、
  控制面大脑（`conductor/`）、沙盒守护进程（`loopd/`）、提示词（`prompts/`）、
  分支保护真源（`settings/`），以及产品仓样板（`templates/product-x/`）。
  产品仓的 CI/gates/review 全部经本仓的 reusable workflow 调用，本地零逻辑（CHARTER N10.2）。
- **不是**：真实产品仓库。`templates/product-x/` 只是样板，不在本仓塞产品逻辑（CHARTER N7）。
  本仓也不持有产品工单——产品工单的真源在产品仓 issues，`cards/` 已于 2026-07-30 冻结为只读归档（R10-5）。

## 目录地图

| 路径 | 作用 |
|---|---|
| `CHARTER.md` | 唯一人类可编辑真源（G 目标 / Q 指标 / N 红线 / U 需求） |
| `DECISIONS.md` | ADR 架构决策记录 |
| `policy.yml` | 控制面策略方向盘（audit/plan/execute/upstream/license/review 段） |
| `ROUTING.yaml` | 接缝 A 异构模型路由表 + 各 provider 的 `api_key_env` |
| `products.yml` | 产品仓注册表唯一真源（CHARTER N10.5，人类维护） |
| `UPSTREAM.yaml` | 本仓外部依赖登记（含 sha256，升级环消费） |
| `gates/` | 门禁实现（`gate_*.py` + `run_gates.py` + `lockdiff.py`） |
| `lenses/` | 确定性检查器（12 个 lens，不调用任何 LLM） |
| `conductor/` | 控制面大脑（`tick.py` / `materialize.py` / `claims.py` / `findings.py` / `retro.py` / `upgrade_ring.py` / `drift_check.py` 等） |
| `loopd/` | 沙盒守护进程（`loopd.py` + `bootstrap.sh` + `SPEC.md`） |
| `prompts/` | 提示词（`P-continue.md` 入口 + `P0`..`P12`） |
| `seam_a/` | 接缝 A 路由器（异构模型路由 + 强模型验收环入口） |
| `bench/` | 指标计算与重放（`metrics.py` + `replay/` + `baseline.json`） |
| `settings/` | 分支保护 ruleset 真源（与线上逐字一致，`gate/settings-roundtrip` 校验） |
| `templates/product-x/` | 产品仓样板（fork 后改 ≤5 处即可适配，CHARTER Q2.1） |
| `.github/workflows/` | CI 门禁与定时任务（含 `reusable-gates` / `reusable-product-ci` / `reusable-review`） |
| `.loop/schemas/` | claim / finding / reproduction / verdict 的 JSON schema |
| `cards/` | 已冻结的卡片归档（只读，状态不再有权威性，ADR-011） |
| `waves/` | 波次声明（本仓自身改造工单的物化来源，ADR-010） |
| `docs/` | 设计文档与归档（见下文索引） |
| `tests/` | 测试套件 |

## 从零到接单的最短路径

> 5 步。环境变量只需设下面 5 个，其余均有默认或可由配置推导（详见 `docs/环境变量清单.md`）。

```bash
# ① 设 5 个变量（每沙盒只改这 5 个；LOOP_REPO 换成你工作的仓）
export LOOP_SANDBOX_ID=impl-1 LOOP_ROLE=impl LOOP_MODEL=qwen3-max \
       LOOP_WS=/work/loop GH_TOKEN=<fine-grained PAT>

# ② 拉取并校验 bootstrap.sh（sha256 不匹配即 SHA_MISMATCH 退出），然后执行
python3 - <<'PY'
import urllib.request,os,hashlib,sys
u=f'https://raw.githubusercontent.com/Cloudbird-Software/loop/v0.2.0/loopd/bootstrap.sh'
d=urllib.request.urlopen(u).read()
h=hashlib.sha256(d).hexdigest()
sys.exit('SHA_MISMATCH '+h) if h!=os.environ.get('LOOP_BOOTSTRAP_SHA256','e886bc2dee0784a07ece948ca97ade4e7b4d9b698383a1cc393aa5de8c3b2b8e') else open('/tmp/bootstrap.sh','wb').write(d)
PY
sh /tmp/bootstrap.sh   # 装 gh/mise/jq → 落地 loopd → clone 仓 → 预热证据工具

# ③ 起守护进程
setsid nohup loopd --daemon --role "$LOOP_ROLE" >>/work/.loop/logs/loopd.log 2>&1 < /dev/null &
sleep 3

# ④ 自检
loopd status

# ⑤ 领卡（CAS 原子领卡 + 切 agent/<card_id> 分支 + 落 .loop/CARD.md）
loopd next
```

`bootstrap.sh` 做的四件事（完整脚本见 `loopd/bootstrap.sh`）：装 `gh`/`mise`/`jq`（校验 sha256）→
拉 `loopd.py` 落地 `/usr/local/bin/loopd` → clone 目标仓到 `$LOOP_WS`（对齐 `.tool-versions`）→
预热证据工具（zizmor/gitleaks/osv-scanner/syft/grype/opencode，全部校验哈希）。

> 旧的 `Trae沙盒填写卡.md`（七槽位逐字段值）已归档至 `docs/archive/Trae沙盒填写卡.md`，
> 其必需步骤已收敛进上面的最短路径；建沙盒不再需要照填七槽位。

## 设计文档索引（四份）

| 文档 | 定位 | 规格来源 |
|---|---|---|
| `CHARTER.md` | loop 自身章程（G0–G5 目标 / Q0–Q5 指标 / N3–N15 红线） | 全部卡片 charter 字段引用此处 |
| `docs/产品仓对齐架构.md` | loop ↔ product-x ↔ 未来产品仓的对齐架构（pin 而非副本） | WAVE-13 全部卡片，ADR-007/008/009 |
| `docs/强模型验收环.md` | review 环：可证伪断言 + 异构复现 + 固化为检查器 | WAVE-12 全部卡片，ADR-004/005/006 |
| `docs/审查裁决-2026-07-30.md` | 专家诊断 → 独立复现 → 最终裁决三轮存档（F-A~F-D） | WAVE-10/11/14 全部卡片 |

## 相关章程

- **CHARTER N11**：零假绿是红线——`|| true`、`set +e` 吞退出码、`continue-on-error`、
  探测不到即 SKIP 且 exit 0 一律禁止；正当例外必须写明 `fake-green-ok: <理由>`。
- **CHARTER N12**：不允许实现方自证——impl 不得给自己的卡产 VERDICT，评审模型不得给自己的 claim 做复现判定。
- **CHARTER N13**：不把模型的论断当作事实——不可证伪的一律拒收，未被独立复现的不得触发任何代码改动。
- **CHARTER N14**：不在产品仓复制 loop 的机制文件（gates/lenses/conductor/loopd/prompts/settings）。
- **CHARTER N15**：不把高权限凭证放进仓库级 secret——能用 GITHUB_TOKEN 的绝不用 PAT，能用 App 的绝不用 PAT。

进仓 AI 的唯一入口见 `AGENTS.md`。凭证清单见 `docs/密钥清单.md`。
