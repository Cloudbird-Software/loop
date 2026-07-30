# loopd SPEC.md — 权威行为规格

> 覆盖：动词语义表、CAS 领卡协议、租约与心跳、僵尸回收约定、命令传输层、RETIRE 规则、错误码表。

---

## 1. 动词语义表

| 动词 | 语义 | loopd 内部真实动作 | handler |
|---|---|---|---|
| `next` | 阻塞取卡（最长 25 分钟） | 领卡（CAS）+ 切分支 + 落 `.loop/CARD.md` + 打印卡片正文 | `h_next` |
| `save "msg"` | 落盘一步 | add + commit + push（首次 push 自动开 draft PR） | `h_save` → `do_save` |
| `verify` | 本地验收 | 按仓库锁文件跑 `.loop/verify.sh`，日志入 `.loop/logs/` | `h_verify` |
| `done` | 交卡 | 终验 + PR 转 ready + 贴报告 + CAS 置 `in_review` + 清空当前卡 | `h_done` |
| `drop <path>` | 删除 | 移进 `.loop/trash/` | `h_drop` |
| `reset` | 回干净基线 | 丢工作区 + 重切分支到 `origin/main` | `h_reset` |
| `ask "..."` | 异步问人 | 卡片 issue 下留言 + 打 `blocked` 标签（不阻塞会话） | `h_ask` |
| `evidence <lens>` | 取证据 | 跑 lens 脚本，输出统一 JSON | `h_evidence` |
| `finding <file>` | 提发现 | 校验 schema + 指纹去重 + 配额检查后开 Finding issue | `h_finding` |
| `propose <file>` | 提波次 | 开波次 PR（只允许改 `waves/**`） | `h_propose` |
| `verdict <file>` | 交裁决 | 校验 head_sha 绑定后贴 VERDICT | `h_verdict` |
| `upstream <pkg>` | 登记依赖 | 查发布日期 → 过冷静期才返回 OK | `h_upstream` |
| `retire` | 结束会话 | 归档上下文 + 通知点击器重开 | `h_retire` |
| `status` | 自检 | daemon/token/租约/确认计数 | `h_status` |
| `help` | 打印动词表 | 原样输出动词表 | `h_help` |

---

## 2. CAS 领卡协议

卡片状态机：`ready` → `claimed` → `in_progress` → `in_review` → `done`（或回 `ready`）

领卡流程（`h_next`）：
1. 遍历所有 `state=ready` 的卡，按 `prio(blk)` 排序（trivial < standard < critical，同 tier 按 id 升序）。
2. 过滤：role 匹配、无 blocked_by、verify 异构（`verify.model != impl.model`）、impl 路径不交叉。
3. CAS 写入：`write_block(num, new_blk, expect_updated_at=it["updatedAt"])`。
   - 前置校验：issue 的 `updatedAt` 必须与读取时一致（乐观锁）。
   - 写后回读：`extract_block` 确认 `claim_id` 已生效。
   - 失败（被抢/网络错）→ 换下一张卡继续。
4. 成功后：`prepare_branch` 切到 `agent/<card_id>` 分支，落 `.loop/CARD.md`，更新 daemon state。

CAS 字段：`claim_id` = `{SID}-{uuid8}`，写入 card block 的 `claim_id` 字段。

---

## 3. 租约与心跳

- **租约**：领卡时 `lease_until = now + LOOP_LEASE_MIN * 60`（默认 45 分钟）。
- **心跳**：`heartbeat_thread` 每 `LOOP_HEARTBEAT_SEC`（默认 60 秒）刷新 `lease_until` 和 `heartbeat_at`，通过 CAS 写回 issue。
- **自动落盘**：`autosave_thread` 每 `LOOP_AUTOSAVE_SEC`（默认 180 秒）检查工作区是否有改动，有则 `do_save`。

---

## 4. 僵尸回收约定

僵尸卡 = `lease_until < now` 且 lease 期内无新 commit 的 `claimed/in_progress` 卡。

回收逻辑由 `conductor/tick.py` 执行（不在 loopd 内）：
1. 检查 `lease_until < now`。
2. 检查 lease 期内是否有新 commit（通过 PR commit 历史）。
3. 无新 commit → `state=ready`，`attempt+=1`，清 `claim_id`/`sandbox`/`lease_until`。
4. 升档策略：`attempt>=2` 换模型池，`attempt>=3` 升 tier，`attempt>=4` 关卡 + 开拆卡 Finding。

---

## 5. 命令传输层（#52/#53 已移除远程通道）

> **历史**：原设计有两条未鉴权的远程命令通道——
> - **Shim 模式**（`LOOP_IO_MODE=shim`）：`loop` shim 把请求写到 `.loop/relay/inbox/{id}.json`，轮询 `.loop/relay/outbox/{id}.json`。
> - **File 模式**（`LOOP_IO_MODE=file`）：agent 写 `.loop/IN.json`，`filemode_thread` 检测 mtime 后投递到 relay inbox，结果覆盖写 `.loop/OUT.md`。
>
> 两者都允许任何能写 `.loop/relay/` 或 `.loop/IN.json` 的进程执行白名单命令（含 `run <intent>` 的 shell 兜底），是不鉴权的命令执行面。#52/#53 已删除 `relay_thread` / `filemode_thread` / `load_intents` / `h_run` / `loop` shim / `intents.yaml`，并停止创建 `.loop/relay/` 目录。
>
> **现状**：loopd 仅作为守护进程运行（`main()` 启动心跳 / 自动落盘 / 僵尸回收线程），状态持久化在 `.loop/daemon.json`。暂行期 agent 不经 loopd CLI 取卡，直接用 gh/git 按 `cards/WORKFLOW.md` 推进；正式 loopd 体系的命令传输层待后续以鉴权方案重建（见 `docs/issue去留裁决-2026-07-30.md` #52）。往 `.loop/IN.json` 或 `.loop/relay/inbox/` 丢 JSON 不会被消费（见 `tests/test_loopd_no_remote_intents.py`）。

---

## 6. RETIRE 规则

- 每个 session 最多 `LOOP_MAX_CARDS_PER_SESSION` 张卡（默认 6）。
- `h_next` 在 `session_ordinal >= max` 时立即返回 `RETIRE`，不取卡。
- agent 收到 RETIRE → 执行 `loop retire`。
- `h_retire`：归档 daemon state 到 `.loop/archive/`，写 `.loop/session-ended` 标记，重置 `session_ordinal=0`，清空当前卡。
- 点击器巡检发现 `session-ended` → 新建会话 → 粘贴 P0 → 新 session 开始。

---

## 7. 错误码表

| 退出码 | 含义 | 触发条件 |
|---|---|---|
| `0` | OK | handler 正常返回 |
| `1` | 业务失败 | verify 失败、no active card、not found 等 |
| `64` | UNKNOWN_VERB / UNKNOWN_INTENT | 未注册的动词或意图 |
| `70` | LOOPD_ERROR | handler 内部异常 |
| `75` | LOOP_TIMEOUT | （历史）shim 轮询超时；#52/#53 移除 shim 后不再产生 |

`75` 原由 `loop` shim 在轮询 `.loop/relay/outbox/` 超时时返回；shim 与 relay 通道已于 #52/#53 移除，该退出码不再出现。

---

## 8. 待裁决（AI 补完时未明确的细节）

以下细节手册未明确，AI 选了最小实现，列出待人类裁决：

1. **prio 排序策略**：当前 trivial < standard < critical（简单卡优先快速消化）。是否改为 critical 优先？
2. **`loop --help` vs `loop help`**：手册说 `loop --help` 打印动词表，但 shim 将 `--help` 作为 intent 传给 daemon（会返回 UNKNOWN_VERB）。当前 smoke test 用 `loop help` 测试。是否需要在 shim 里加 `--help → help` 映射？
3. **`loop status` 的 token 检查**：当前只检查环境变量是否存在，不做有效性验证（避免每次调用消耗 API 配额）。是否需要偶尔做一次 `gh api user` 探活？
4. **`loop finding` 的配额检查**：手册提到"配额检查"但未给阈值。当前未实现配额限制，只做指纹去重。配额阈值待 policy.yml 的 `audit.max_new_findings_per_day` 落地后接入。
5. **`loop upstream` 的发布日期查询**：当前只检查包是否在 UPSTREAM.yaml 登记，不查真实发布日期。冷静期检查留给 W2 的 `upgrade.yml` workflow 实现。
6. **`loop drop` 的真删时机**：手册说"移进 .loop/trash/，loopd 真删"。当前只移进 trash，不主动删除 trash 内容。是否需要定期清理 trash？
7. **shim 中 `sys.exit 75` 语法笔误**：手册 1.3 节原文为 `sys.exit 75`（Python 语法错误），已修正为 `sys.exit(75)`。
8. **`main()` 中 `time.sleep 3600` 语法笔误**：手册 5.1 节原文同上，已修正为 `time.sleep(3600)`。
9. **heartbeat/autosave 线程无异常保护**：手册 5.4 的线程函数内部无 try/except，gh 调用失败会导致线程崩溃（但 daemon 进程不亡，因为 daemon=True）。是否需要加 try/except 包裹？
