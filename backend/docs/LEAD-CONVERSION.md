# P6AN-05 Lead Conversion 计算服务文档（计算规则 + API）

## 概述

`GET /api/v1/analytics/leads/conversion` 提供线索转化漏斗与平均转化周期。
纯读聚合，不写库、无新表：复用 Phase 3/4 的
`lead / agent / agent_customer_binding / customer / conversation /
lifecycle_stage_log` 六张既有表。

- 服务层：`app/services/lead_conversion_service.py`
  （`LeadConversionService.compute` + 纯函数 `compute_metrics` /
  `_stage_reached` / `_rates`，指标数学与 DB 解耦，可无库单测）
- 路由：`app/routers/analytics.py`（追加 1 条路由，router 自含
  `/api/v1/analytics` 前缀，`main.py` 无需改动）
- 响应 schema：`app/schemas/lead_conversion.py`
- 单元测试：`tests/test_lead_conversion_p6an05.py`（22 条）
- 真实 PG 对拍 E2E：`tests/_e2e_lead_conversion_p6an05.py`（35 条断言，
  opt-in，自建/自删 scratch 库 `p6an05_lead_scratch`）

## 漏斗定义

漏斗直接取 `lead.status` 状态机（与
`app/crm/services/lead.py:VALID_STATUS_TRANSITIONS` 对齐，不另起炉灶）：

```
new → contacted → qualified → converted(终态)
```

- `status_counts`：各 status 的**去重线索数**（`COUNT(DISTINCT lead.id)`）。
- `stage_reached_counts`：达到某阶段 = 该线索当前 status 的漏斗位次
  ≥ 该阶段位次（秩计数法）。回退态（qualified→contacted）只算到
  contacted。未知/遗留 status 位次 -1，计入 total_leads 但不计入任何
  stage_reached。
- `conversion_rates`：`step_rate = reached(后一阶段) / reached(前一阶段)`，
  另含 `new_to_converted` 总体转化率。分母为 0 时返回 **null**
  （“无数据”，前端不得渲染为 0%）。

## 转化周期

- 样本 = 当前 `status == "converted"` 的去重线索。
- 周期 = `created_at → 转化时刻`（天，`max(0, …)`，负值截 0）。
  转化时刻取该线索**最早一条** `lifecycle_stage_log(new_stage_code = "成交")`
  的 `created_at`；无日志（例如旧数据直接置 converted）时回退
  `lead.updated_at`。
- `avg_conversion_cycle_days` 为样本均值；无 converted 线索时为 null。
- 周期样本与应用了 Agent/渠道过滤的队列保持一致（同套 join + where）。
  双绑定线索在组内按组各计一次，在 `totals` 里按线索去重只计一次。

## Agent / 渠道归属

- **Agent 维度**：`lead.customer_id → agent_customer_binding → agent`，
  组名 = `COALESCE(agent.name, "unassigned")`。一客户绑多 Agent 时，
  线索在每个 Agent 组各计一次（组内去重按 lead.id）。
- **渠道维度**：仅 `source_type = "conversation"` 的线索有渠道
  （`lead.source_id = CAST(conversation.id AS text)`，左连接
  `conversation.channel`，组名 = `COALESCE(LOWER(channel), "direct")`）；
  非会话来源线索归 `direct`。`channel=` 过滤时非会话线索被排除。

## 时间窗口

`from_date` / `to_date` 作用于 `lead.created_at`（闭区间，UTC naive，
与表列语义一致），`filters.window_basis` 在响应中回显。

## 响应结构

```jsonc
{
  "filters": { "agent_id": "...|null", "channel": "...|null",
               "from_date": "...", "to_date": "...",
               "group_by": "overall|agent|channel",
               "window_basis": "lead.created_at" },
  "totals":  { "total_leads": 10,
               "status_counts": {"new": 5, "contacted": 3, "qualified": 1, "converted": 1},
               "stage_reached_counts": {"new": 10, "contacted": 5, "qualified": 2, "converted": 1},
               "conversion_rates": {"new_to_contacted": 0.5, "contacted_to_qualified": 0.4,
                                     "qualified_to_converted": 0.5, "new_to_converted": 0.1},
               "avg_conversion_cycle_days": 2.0 },
  "groups": [ { "key": "agent-one", "label": "agent-one", "metrics": { …同上… } } ]
}
```

## 查询计划

`compute()` 最多 3 条聚合 SQL（均带 `is_deleted = false`）：

1. 总体：`SELECT status, COUNT(DISTINCT id) FROM lead … GROUP BY status`
   （按需外连 binding/agent/conversation + where）
2. 分组：`SELECT group_key, status, COUNT(DISTINCT id) … GROUP BY 1,2`
   （仅 `group_by != "overall"` 时执行）
3. 周期：`SELECT lead.id, created_at, updated_at, MIN(lsl.created_at) AS stage_ts
   FROM lead LEFT JOIN lifecycle_stage_log lsl ON lsl.lead_id=lead.id
   AND lsl.new_stage_code='成交' WHERE status='converted' …`
   （与 1/2 同套过滤 join）

复杂度与线索表行数同阶，3 个既有索引（`idx_lead_status` /
`idx_lead_created` / `idx_lead_customer`）覆盖 where；V1 不做物化。

## 验证

- 单测 `tests/test_lead_conversion_p6an05.py` **22/22 通过**
  （纯数学：阶梯/回退/未知态/零分母/周期均值 + 路由注册/200 结构/
  参数 422/过滤回显 + canned-row 分组与 join 结构对拍）。
- 对拍 E2E `tests/_e2e_lead_conversion_p6an05.py` **35/35 通过**：
  隔离 scratch 库 `create_all` + 10 线索已知 fixture（双绑定客户、
  4 渠道、1 条 成交日志），服务输出逐条比对**独立裸 SQL**
  （`COUNT(DISTINCT …)` / 手工 join）与手算漏斗算术，含
  agent / channel 分组、agent+channel 组合过滤、空/满时间窗口、
  共享客户总体去重（组内 6+6，总体仍 10）。

## 遗留 / 说明

- 组内周期归属对「一线索多 Agent」会按组重复计样（组语义如此，
  `totals` 已按线索去重）——文档明示，无需改码。
- 「成交」阶段码硬编码 `"成交"`（与 `DEFAULT_STAGES` 同源）；若未来
  CRM 改名需同步 `CLOSED_STAGE_CODE`。
- 未做：成交金额/ROI（P6AN-09 范围）、线索 CRUD（Phase 4 已覆盖）。
