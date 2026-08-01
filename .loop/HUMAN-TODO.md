# HUMAN-TODO —— 每日四问（tick 自动生成）

> 本文件由 `python3 conductor/tick.py --generate-digest` 每日生成。
> 只列**AI 无法代做**的事项与系统真实现状。人工维护的长期清单见根目录 `HUMAN-TODO.md`。
> 生成时间：2026-08-01T07:11:07.624918Z

---

## 一、卡在我这的（需要人决策/操作，AI 无权或无能力代做）

- （当前无 needs-human 标签的 open issue）

**根 HUMAN-TODO.md 未勾选条目**（人工维护长期清单）：
- [ ] A1. 审定并签署 product-x 的 CHARTER.md
- [ ] A2. 把 product-x 设为 GitHub Template Repository
- [ ] B2. 密钥降权与轮换
- [ ] C2. product-x 的 required check 名单同步
- [ ] C3. 维护 `products.yml`
- [ ] D1. 通知通道选型
- [ ] D2. 7 天无人值守验收的时间窗

---

## 二、昨天放行的（最近 24h 合并的 PR）

- （最近 24h 无合并 PR）

---

## 三、什么退化了（CI 连败 / 存活超期 / 新开 Incident）

- **liveness 无 run**: template-sync 从未运行过（期望 ≤30h）
- **liveness 无 run**: audit 从未运行过（期望 ≤30h）
- **liveness 无 run**: upgrade 从未运行过（期望 ≤180h）
- **liveness 无 run**: tick 从未运行过（期望 ≤1h）
- **liveness 无 run**: canary 从未运行过（期望 ≤2h）
- **liveness 无 run**: drift 从未运行过（期望 ≤8h）
- **liveness 无 run**: scribe 从未运行过（期望 ≤30h）
- **liveness 无 run**: nightly-rubric 从未运行过（期望 ≤30h）
- **liveness 无 run**: policy 从未运行过（期望 ≤168h）

---

## 四、花了多少（成本核算）

- 未接入（LLM 用量与 CI 分钟数计量管道在 WAVE-12 落地）

> 成本列暂占位"未接入"——LLM 用量与 CI 分钟数的计量管道在 WAVE-12 落地前不接入。
> 当前仅记录结构占位，避免假数字。

---

## 附：liveness 期望周期（来自 .loop/liveness.yml）

| workflow | 期望周期 |
|---|---|
| template-sync | 30h |
| audit | 30h |
| upgrade | 180h |
| tick | 1h |
| canary | 2h |
| drift | 8h |
| scribe | 30h |
| nightly-rubric | 30h |
| policy | 168h |
