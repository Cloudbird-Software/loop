# E2 僵尸交接测试 — 给 impl-2 沙箱 AI 的指示

你是 impl-2 沙箱。本文件是 E2 测试的唯一指令，按顺序执行即可。不要问问题。

## 背景（一句话）

product-x 上有一张卡 #35（e2-handoff）是僵尸态：`state=claimed, lease_until=1(已过期), claim_id=impl-1-fake`。模拟 impl-1 崩溃后留下的卡。你的 reaper 线程启动后应在 ~60 秒内把它从 claimed 回收到 ready。

## 执行步骤

### 第 1 步：确认你的 loopd 版本是 v0.1.5 且 reaper 在跑

```bash
loop status
```

输出应含 `sandbox: impl-2`、`daemon: alive`。如果报错或 daemon 没起，按填写卡第⑤格重启 `loopd --daemon`。

### 第 2 步：等 reaper 回收 #35（约 60-120 秒）

reaper 每 60 秒扫一次。等约 2 分钟后，查 #35 状态：

```bash
loop run gh.view.issue 35
```

如果上面返回 UNKNOWN_INTENT，直接用：
```bash
gh issue view 35 -R Cloudbird-Software/product-x --json body -q .body
```

看 body 里的 `json loop` 块的 `state` 字段：
- 启动前应是 `claimed`
- reaper 回收后变成 `ready`，且 `attempt` 从 0 变 1，`claim_id`/`sandbox`/`lease_until` 字段消失

**如果 3 分钟后 #35 还是 `claimed`**：说明 reaper 没生效。检查：
1. `grep reaper /work/.loop/logs/loopd.log` — 应有 `[reaper] #35 (e2-handoff) reclaimed` 行
2. 如果有 `[reaper] error`，多半是 GH_TOKEN 没有 Issues:write 权限

### 第 3 步：#35 变 ready 后，正常取卡实现

reaper 把 #35 回收到 ready 后，按 P0 流程取卡：

```bash
loop next
```

应取到 #35（e2-handoff）。卡片要求：
- 在 `e2/handoff/MARKER.md` 创建文件
- 首行含 `E2 handoff test`
- 含一行 ISO8601 时间戳（如 `2026-07-29T14:30:00Z`）

然后：
```bash
loop save "wip"
# 用编辑器创建 e2/handoff/MARKER.md，内容：
#   E2 handoff test
#   2026-07-29T<当前时间>Z
loop save "create MARKER"
loop verify
loop done
```

### 第 4 步：done 返回 OK 即 E2 全流程通过

done 成功后 #35 应变成 `in_review`，PR 在 `agent/e2-handoff` 分支创建。E2 结束。

## 成功标准

- [ ] #35 从 claimed → ready（reaper 回收，attempt 0→1）
- [ ] impl-2 取到 #35 并完成实现
- [ ] `loop done` 返回 OK，#35 变 in_review

## 失败时怎么办

不要硬试。把以下信息贴出来交给人类：
1. `loop status` 输出
2. `grep reaper /work/.loop/logs/loopd.log` 输出
3. `gh issue view 35 ... --json body -q .body` 输出（含 json loop 块）
