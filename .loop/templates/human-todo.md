# HUMAN-TODO —— 每日四问（tick 自动生成）

> 本文件由 `python3 conductor/tick.py --generate-digest` 生成（建议每日运行；当前无 cron 自动触发，需人工或后续 workflow 接入）。
> 只列**AI 无法代做**的事项与系统真实现状。人工维护的长期清单见根目录 `HUMAN-TODO.md`。
> 生成时间：{{generated_at}}

---

## 一、卡在我这的（需要人决策/操作，AI 无权或无能力代做）

{{blocked_on_human}}

---

## 二、昨天放行的（最近 24h 合并的 PR）

{{released_yesterday}}

---

## 三、什么退化了（CI 连败 / 存活超期 / 新开 Incident）

{{degradations}}

---

## 四、花了多少（成本核算）

{{cost}}

> 成本列暂占位"未接入"——LLM 用量与 CI 分钟数的计量管道在 WAVE-12 落地前不接入。
> 当前仅记录结构占位，避免假数字。

---

## 附：liveness 期望周期（来自 .loop/liveness.yml）

{{liveness_table}}
