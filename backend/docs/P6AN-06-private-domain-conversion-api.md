# Private Domain Conversion API 文档 (Phase 6 / P6AN-06)

> 任务卡：`t_24e62012` — Private Domain Conversion 私有域转化 API
> 目标：私有域客户从 触达 → 互动 → 成交 的转化与 LTV proxy。
> 实现位置：
> - 服务：`backend/app/services/private_domain_conversion.py`
> - Schema：`backend/app/schemas/private_domain_conversion.py`
> - 路由：`backend/app/routers/private_domain_conversion.py`（自带 `/api/v1/analytics/private-domain` 前缀，在 `main.py` BARE 挂载）
> - 测试：`backend/tests/test_p6an06_private_domain_conversion.py`（23 用例：纯数学 / 窗口 / API 层 / live-PG 对拍）

## 概述

本卡是一个**只读聚合**端点：把 Phase 5 私有域源表（`messages` /
`conversation` / `deal_item` / `nurture_step_execution` / `follow_up_task` /
`agent_customer_binding`）聚合成客户漏斗（reach → interact → convert）、
LTV proxy、NurturePlan 执行完成率、FollowUpTask 完成率。**不写库、不建新
表**——它骑在 P6AN-01 analytics 路由前缀上，依赖已存在的 Phase 5 ORM，因此
本卡无迁移。

- API：`GET /api/v1/analytics/private-domain/conversion`
- 查询参数：`agent_id` / `account_id` / `since` / `until`（均为可选）
- 依赖：P6AN-01 Analytics 基础框架（`t_e94a362e`）+ Phase 5 Private Domain 数据

## 指标口径（LTV proxy + 转化率，对拍 SQL）

窗口：`since`（含）.. `until`（不含），UTC。缺省（两者都不传）= 最近 30 天。
所有源表统一按记录 `created_at` 落在窗口内计入（窗口锚点 = `created_at`，
非空、易对拍）。

### 漏斗（按「去重客户数」计数）

| 指标 | 定义（口径） | 对拍 SQL |
|---|---|---|
| `base_customers` | 分母人群：指定 `agent_id` 时 = 绑定该 agent 的客户数；否则 = 全部 live 客户数 | `agent_id` → `COUNT(DISTINCT customer_id) FROM agent_customer_binding WHERE agent_id=:a AND is_deleted=false`；否则 `COUNT(DISTINCT id) FROM customer WHERE is_deleted=false` |
| `reached_customers` | 有 ≥1 条**出站**私域消息（`direction='out'` 且 `status IN (sent,delivered,read)`，排除 queued/failed）的客户数 | `COUNT(DISTINCT conv.customer_id) FROM messages m JOIN conversation conv ON conv.id=m.conversation_id WHERE m.direction='out' AND m.status IN ('sent','delivered','read') AND m.created_at>={since} AND m.created_at<{until} [AND m.account_id=:acct] [AND conv.customer_id IN (agent 绑定)]` |
| `interacted_customers` | 有 ≥1 条**入站**消息（`direction='in'`，客户回复）的客户数 | 同上，`direction='in'` |
| `converted_customers` | 有 ≥1 笔 `won` 成交的客户数 | `COUNT(DISTINCT customer_id) FROM deal_item WHERE status='won' AND is_deleted=false AND created_at>={since} AND created_at<{until} [AND account_id=:acct] [AND customer_id IN (agent 绑定)]` |

**速率**（百分比，保留 2 位；分母为 0 → 0.0，绝不除零）：
- 步骤率：`reach_rate = reached/base`，`interaction_rate = interacted/reached`，
  `conversion_rate = converted/interacted`
- 整体率：三者都 `x/base`
- `interaction_rate_percent` / `conversion_rate_percent` 可能 >100（步骤率相对
  上一阶段），这是刻意的；`*_overall_percent` 恒 ≤100。

### LTV proxy（成交金额 / 次数）

金额统一以 `deal_item.value`（**分**）计；`currency` 随结果 `currencies` 回传，
FX 归 P6AN-09 决定。

| 指标 | 定义 | 对拍 SQL |
|---|---|---|
| `won_deal_count` | 窗口内 won 成交笔数 | `COUNT(id) FROM deal_item WHERE status='won' AND is_deleted=false AND created_at>={since} AND created_at<{until} [AND account_id] [AND customer_id IN agent]` |
| `total_won_value_cents` | 窗口内 won 成交金额合计（分） | 同上 `SUM(value)`（COALESCE 0） |
| `avg_won_deal_value_cents` | **单次成交金额（金额/次数）** = total / won_deal_count | 纯计算 |
| `ltv_proxy_cents_per_reached` | **LTV proxy** = 窗口内每触达客户产生的金额 = total_won_value / reached_customers | 纯计算 |

> LTV proxy 口径：`total_won_value_cents / reached_customers`（触达客户分母）。
> `avg_won_deal_value_cents` 是「金额/次数」的更细 proxy。两者都回传，P6AN-09
> ROI 用哪个由其口径决定。

### 完成率

| 指标 | 定义 | 对拍 SQL |
|---|---|---|
| NurturePlan 执行完成率 | `success` 执行数 / 已执行数（`status NOT IN (pending,running)`）| `GROUP BY status` on `nurture_step_execution`，`created_at` 窗口 + `account_id`（step 行无客户/agent 关联，故只按 account 域）|
| FollowUpTask 完成率 | `completed` 数 / 窗口内全部任务数 | `GROUP BY status` on `follow_up_task`，`created_at` 窗口 + `account_id` |

**作用域规则（刻意、已文档化）**：客户漏斗 + LTV + follow-up 受
`agent_id`（经 `agent_customer_binding`）与 `account_id` 双作用域；NurturePlan
执行率 + follow-up 完成率**只**受 `account_id` 作用域（其源行无 agent 关联），
故 agent 过滤不影响这两个完成率。

## 响应结构

`PDCResponse`：`window` / `agent_id` / `account_id` / `funnel` / `ltv` /
`nurture_execution` / `follow_up` / `roi_inputs`。`roi_inputs` 回传 P6AN-09 复
算 ROI 所需的原始量（revenue 侧），本卡不算 ROI。

## 验证

- 单元测试：`tests/test_p6an06_private_domain_conversion.py` **23/23 通过**。
  - 纯层（无 DB）：`_pct` 除零/舍入、窗口解析、`assemble` 步骤率 vs 整体率、
    LTV proxy 数值、schema 形状。
  - API 层（TestClient）：200 + ISO 窗口解析、缺参缺省、坏 UUID 422、坏日期 422、
    agent_id 解析为 UUID 透传。
  - live-PG 对拍（`ai_agent_platform_test`）：种子全图后逐项 对拍 漏斗 /
    LTV / 完成率；agent 过滤、account 过滤、窗口越界排除，共 4 条。DB 不可达
    时自动 skip。

## 遗留 / 说明

- 共享测试库 `ai_agent_platform_test` 有 pre-existing 行：`base_customers`
  （无 agent 过滤）与全局 `deal_item` 聚合会被污染，故 live 对拍一律用
  `agent_id`（客户分母）+ `account_id`（account 源）限定，保证对拍数字干净。
- 无迁移、无新表；端点只读。NurturePlan 执行引擎（Phase 5 遗留）与前端图表
  （P6AN-11）不在本卡范围。
