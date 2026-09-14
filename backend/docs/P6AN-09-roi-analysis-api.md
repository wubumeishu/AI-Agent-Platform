# ROI 分析 API 文档 (Phase 6 / P6AN-09)

> 任务卡：`t_46f3916b` — ROI 分析 API（投入产出 / Campaign ROI / Agent ROI）
> 目标：投入产出 ROI 计算，含 Agent / Campaign / 私域三个维度。
> 实现位置：
> - 服务：`backend/app/services/roi_analysis.py`
> - Schema：`backend/app/schemas/roi_analysis.py`
> - 路由：`backend/app/routers/roi_analysis.py`（自带 `/api/v1/analytics/roi` 前缀，在 `main.py` BARE 挂载）
> - 配置：`backend/app/config.py` → `roi_cost_rates()` / `_cents_env()`（成本 proxy 单价，env 可配）
> - 测试：`backend/tests/test_p6an09_roi_analysis.py`

## 概述

本卡是一个**只读聚合**端点：计算「投入产出」ROI 的三个维度（Agent /
Campaign / 私域）。**产出**侧 = 窗口内 `won` 成交金额（`deal_item.value`，
单位**分**）；**投入**侧 = 一个**可配置的运营成本 proxy**（对可观测的运营
活动量 × 单价求和）。**不写库、不建新表**——它骑在 P6AN-01 analytics 路由
前缀上，聚合已存在的 Phase-4 / Phase-5 源表，因此本卡无迁移。

- API：`GET /api/v1/analytics/roi`
- 查询参数：`dimension`（`agent` | `campaign` | `private-domain`，缺省
  `private-domain`）、`agent_id`（agent 维度过滤）、`account_id`（私域维度
  作用域）、`since` / `until`（UTC 窗口；缺省 = 最近 30 天）
- 依赖：P6AN-01 Analytics 基础框架（`t_e94a362e`）+ P6AN-06 私有域转化数据
  （`t_24e62012`，LTV proxy 口径沿用）+ Phase 4 CRM / Phase 5 成交数据

## 通用口径

### 窗口

`since`（含）.. `until`（不含），UTC。缺省（两者都不传）= 最近 30 天。
源表统一按记录 `created_at` 落在窗口内计入（窗口锚点 = `created_at`，非空、
易对拍；与 P6AN-06 一致）。

> 注意：`lead.created_at` 是**朴素** `timestamp`（无 tz），窗口边界在查询
> lead 时会被规整为朴素 UTC 墙钟（P6AN-07 同款处理）；其余源表为
> `timestamptz`，边界保持 aware-UTC。

### 产出（Output）

统一口径 = **窗口内 `won` 成交金额合计（分）**。各维度把成交归属到不同
实体：

| 维度 | 产出归属口径 | 对拍 SQL（金额/笔数） |
|---|---|---|
| `private-domain` | 全部（或指定 `account_id`）`won` 成交 | `SELECT COUNT(id), COALESCE(SUM(value),0) FROM deal_item WHERE status='won' AND is_deleted=false AND created_at>={since} AND created_at<{until} [AND account_id=:acct]` |
| `agent` | 归属到 agent 所绑客户的成交 | `SELECT b.agent_id, COUNT(d.id), SUM(d.value) FROM deal_item d JOIN agent_customer_binding b ON b.customer_id=d.customer_id WHERE d.status='won' AND d.is_deleted=false AND b.is_deleted=false AND d.created_at 窗口内 GROUP BY b.agent_id` |
| `campaign` | 该 campaign 的线索所引成交 | campaign = 去重 `lead.source_id`（`source_type='campaign'`）；`SELECT COUNT(id), SUM(value) FROM deal_item WHERE status='won' AND lead_id IN (该 campaign 线索 id 集)` |

> **LTV proxy（辅助，非 ROI 产出基准）**：`ltv_proxy_cents_per_reached` =
> 窗口内成交总额 ÷ 去重触达客户数（沿用 P6AN-06 口径）。私域维度会回传；
> agent / campaign 维度不拆到触达级，故此字段为 0（该维度的「触达」无法
> 可靠归属）。它仅作展示辅助，**不参与** ROI 计算（ROI 产出 = 总额）。

### 投入（Input）—— 运营成本 proxy（本期口径，非财务）

**Out of scope**：财务系统对接、成本自动采集。本期投入 = 可观测活动量 ×
单价的 proxy，单价由 `app.config.roi_cost_rates()` 提供（env 可配）：

| 单价 key | env 变量 | 默认 | 含义 |
|---|---|---|---|
| `cost_per_outbound_message_cents` | `ROI_COST_PER_OUTBOUND_MESSAGE_CENTS` | 0 | 每条出站（已送达）私域消息的运营成本 |
| `cost_per_nurture_execution_cents` | `ROI_COST_PER_NURTURE_EXECUTION_CENTS` | 0 | 每次 nurture 步骤执行的运营成本 |
| `cost_per_followup_task_cents` | `ROI_COST_PER_FOLLOWUP_TASK_CENTS` | 0 | 每个跟进任务的运营成本 |
| `cost_per_active_agent_cents` | `ROI_COST_PER_ACTIVE_AGENT_CENTS` | 0 | 每个 active agent 的运营开销 |
| `cost_per_campaign_lead_cents` | `ROI_COST_PER_CAMPAIGN_LEAD_CENTS` | 0 | 每条 campaign 线索的获客成本 |

各维度的投入活动量（对拍 SQL）：

| 维度 | 投入活动量 | 对拍 SQL |
|---|---|---|
| `private-domain` | 出站消息数 + nurture 执行数 + 跟进任务数 + active agent 数 | 出站：`COUNT(id) FROM messages WHERE direction='out' AND status IN ('sent','delivered','read') AND 窗口内 [AND account_id]`；nurture：`COUNT(id) FROM nurture_step_execution WHERE status NOT IN ('pending','running') AND 窗口内 [AND account_id]`；跟进：`COUNT(id) FROM follow_up_task WHERE 窗口内 [AND account_id]`；agent：`COUNT(id) FROM agent WHERE status='active' AND is_deleted=false` |
| `agent` | 该 agent 出站消息数 + 自身 1 个 active-agent 开销 | `COUNT(id) FROM messages WHERE direction='out' AND status IN (...) AND agent_id=:a AND 窗口内` |
| `campaign` | 该 campaign 线索数 | `COUNT(id) FROM lead WHERE source_type='campaign' AND source_id=:c AND 窗口内` |

> **诚实默认**：所有单价默认 `0`。当全部单价为 0（未配置成本基准）时，
> `cost_basis_configured = false`，投入合计为 0，ROI 报 `None`（见下），
> 绝不伪造成本。部署方设置任一单价即激活 proxy。

### ROI 计算（分母为 0 的安全处理）

```
roi        = (产出 − 投入) / 投入
roi_percent= roi × 100          （2 位小数）
net_cents  = 产出 − 投入        （恒报，即使投入为 0）
```

**分母（投入）为 0 时**：`roi` 与 `roi_percent` 均为 `None`（「未定义」，
而非 0%）——这是验收项「分母为 0 时安全处理」的实现。`net_cents` 仍报
`产出`。

### 响应结构（三维度统一）

- `summary` — 请求作用域的聚合 ROI 块。`agent` / `campaign` 维度 = 各 item
  之和（`summary == Σ items` 不变式，产出与投入两侧都成立）；
  `private-domain` 维度 = 整体答案（单一聚合，`items` 为空）。
- `items` — 逐实体（逐 agent / 逐 campaign）ROI 单元；私域维度为空。
- `cost_rates` + `cost_basis_configured` — 回传本响应实际使用的成本 proxy
  单价，保证透明。

## 错误语义

- 未知 `dimension` / 无法解析的 `since` / `until` / 非法 `agent_id` /
  `account_id`（UUID）→ **422**（干净，绝不在 DB 调用中途 500）。
- 投入为 0（未配成本基准或无活动量）→ **不是错误**：`roi` / `roi_percent`
  为 `None`，响应仍带回产出与 `net_cents`。

## 对拍（live-PG）

测试 `backend/tests/test_p6an09_roi_analysis.py` 在 `ai_agent_platform_test`
上种出 Phase-4/5 源图（客户、agent 绑定、出站消息、成交、campaign 线索、
nurture / 跟进），对每个维度的产出 / 投入 / ROI 逐项手算对拍，并对
「未配成本 → ROI=None」「分母 0 安全」做纯数学层覆盖。
