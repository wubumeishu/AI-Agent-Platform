# Agent Performance Analytics — 指标口径文档 (Phase 6 / P6AN-07)

> 任务卡：`t_1330e1cc` — Agent Performance：各 Agent 的对话量、转化率、满意度、活跃排名。
> 实现位置：
> - 服务：`backend/app/services/agent_performance_service.py`
> - Schema：`backend/app/schemas/agent_performance.py`
> - 路由：`backend/app/routers/agent_performance.py`（`/api/v1/analytics/agents/*`）
> - 对拍 SQL：`backend/_p6an07_duipai.py`（opt-in，真实 PG，84/84）
> - 单元测试：`backend/tests/test_agent_performance_p6an07.py`（44 用例）

本卡是 **P6AN-01 分析基础框架之上的「计算层」**：不新增数据表，全部指标都是
对既有实体（Agent / Conversation / Message / Lead）的**活体聚合**。因此无 Alembic
迁移（见任务卡 Out of Scope：Agent CRUD / 配置调优 / 前端排行 UI 均不在本卡）。

数据脊（data spine）：

```
agent ─< agent_customer_binding >─ customer
                                    ├─< conversation <─ message
                                    └─< lead
```

---

## 核心口径（caliber）

### 1. Agent 归属（agent scoping）
- 一个 Agent 的活动 = 其**存活绑定客户**（`agent_customer_binding.is_deleted = false`
  且 `customer.is_deleted = false`）活动之和。
- 若客户被 N 个 Agent 绑定，则该客户的活动**同时计入这 N 个 Agent**
  （attribute-to-all-live-bindings，不做唯一归属）。

### 2. 时间窗口（window）
- 所有**活动类**指标（conversations / messages / leads / sentiment / hour 直方图）
  按请求窗口过滤在源实体的 `created_at` 上。
- 预设 `range`：`7d / 30d / 90d / 365d`（相对 `now` 回推 N 天，闭区间
  `[now-Nd, now]`）；`all` = 不截断（全历史）。显式 `since` / `until`
  （ISO-8601，naive 视为 UTC）分别覆盖对应边界。
- **客户数**（`total_customers` / `active_customers`）是**全时**的（客户任期在
  短活动窗口内无意义，故不随窗口截断）。

### 3. 各指标定义

| 指标 | 口径 | 空数据行为 |
|---|---|---|
| `total_customers` | 该 Agent 全部存活绑定客户数（全时，`distinct customer_id`） | `0` |
| `active_customers` | 有 ≥1 条**存活且未成交**（`lead.lifecycle_stage_code != '成交'`）线索的客户数（全时） | `0` |
| `conversation_count` | 窗口内属于该 Agent 客户的存活会话数（`distinct`，防多消息重复计数） | `0` |
| `message_count` | 窗口内上述会话中的存活消息数（`message.is_deleted = false`） | `0` |
| `lead_count` | 窗口内为该 Agent 客户创建的存活线索数 | `0` |
| `converted_lead_count` | 窗口内**到达成交阶段**的线索数（`lifecycle_stage_code ∈ CONVERSION_STAGE_CODES = {成交}`） | `0` |
| `conversion_rate` | `converted_lead_count / lead_count`，值域 `[0,1]` | `null`（`lead_count == 0` 时，区分「无线索」与「0% 转化」） |
| `satisfaction_proxy` | 会话 `sentiment` 打分均值：`positive=1.0, neutral=0.5, negative=0.0`；只统计**带 sentiment 的会话** | `null`（窗口内无 sentiment 会话时） |
| `satisfaction_sample` | 窗口内带 sentiment 的会话数 | `0` |
| `sentiment_breakdown` | 窗口内 `{positive, neutral, negative}` 三桶计数 | 全 `0` |
| `active_hours` | 窗口内消息按 **UTC 小时**（`date_part('hour', timezone('UTC', created_at))`）分 24 桶的直方图 | 全 `0` |
| `peak_hour` | `active_hours` 中量最大的 UTC 小时（0-23） | `null`（窗口内无消息时） |

> **满意度 proxy 说明**：平台尚无显式评分体系，`Conversation.sentiment`
> （positive / neutral / negative，Phase-2 会话实体自带）即任务卡所称的
> "满意度 proxy"。若未来引入 1-5 星评分表，`SENTIMENT_SCORES` 与
> `satisfaction_proxy` 的取值域需同步扩展（本卡保持口径可替换）。

### 4. 排序 / 排行（leaderboard）
- `GET /performance` 返回**全部**匹配过滤条件的存活 Agent（空数据 Agent 也
  以 0 值出现、可排序），按 `sort` 排序（`order` 方向），确定性强
  （同分按 `agent_name` 再按 `created_at` tie-break），再分页。
- `sort` 取值：`conversations / messages / activity / conversion_rate /
  satisfaction / customers / name / created_at`。
  - `activity = conversation_count + message_count`（综合互动量）。
  - `conversion_rate` / `satisfaction` 在 null 时**替换为 0.0** 参与排序
    （保证可比较、不崩）；数值类直接取 metric 字段；`customers` 取
    `total_customers`。
  - 该「null→0.0 替换」只影响**排序键**，响应里 `metrics.conversion_rate`
    仍是 `null`（语义不被排序污染）。
- 过滤：`status`（精确匹配 active/inactive/paused）、`name`（模糊 ilike）。

---

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/analytics/agents/performance` | Agent 排行榜（`range` + `sort` + `order` + `status`/`name` 过滤 + 分页） |
| GET | `/api/v1/analytics/agents/performance/metrics/{agent_id}` | 单 Agent KPI 块（`range` + 可选 `since`/`until`） |

错误语义：
- `404` Agent 不存在 / 已软删。
- `422` 非法 `range` / `sort` / `order`，或 `since` / `until` 非 ISO-8601。
- 空数据 Agent **不是**错误：返回 0 值 / null 的 metric 块（验收标准 #3）。

---

## 实现要点 / 约定

- **只读**：服务不 commit；每个指标都是活体聚合。
- **集合式查询**：排行榜路径固定发出 ≈7 条 GROUP BY 查询（会话量 / 消息量 /
  线索量 / 成交线索 / sentiment 分桶 / 小时直方图 / 客户数），Python 内按
  Agent 合并 —— 无 N+1；Agent 数量不影响查询条数。
- **join 顺序**：message 相关查询先 join `conversation` 再 join `message`
  （ON 子句引用已存在的表），规避 PG "missing FROM-item" 报错。
- **时区**：`conversation`/`message`/`agent`/`binding` 是 aware `timestamptz`；
  `lead`/`customer` 是 naive `timestamp`。窗口边界以 aware-UTC 为规范，
  对 naive 列用 `_naive_utc()` 剥离 tzinfo（对 aware-UTC 输入精确），避免
  naive/aware 相减崩溃 + 跨会话 TZ 漂移。
- **对拍 SQL**（验收标准 #1）：`_p6an07_duipai.py` 在隔离 scratch PG
  `agent_perf_p6an07_scratch` 上种确定性数据，**手推期望值 + 独立 raw-SQL
  参考查询 + 服务结果** 三者一致（84/84），覆盖 all-time / 7d 窗口 / 排行
  排序 / 空数据 / 分页。

## 已知边界（非本卡 bug）
- 共享客户活动计入所有绑定 Agent（attribute-to-all），不做唯一归属 ——
  这是口径决策，若业务要求"唯一归属 Agent"需在 P6AN-07 后续卡明确。
- `active_customers` 用"有未成交线索"近似；若业务有独立"客户活跃"定义
  （如 N 天内有互动），可作为后续增量。
