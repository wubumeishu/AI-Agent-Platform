# Analytics 基础框架 API 文档 (Phase 6 / P6AN-01)

> 任务卡：`t_e94a362e` — Analytics 基础框架 + Schema
> 目标：为 Dashboard、漏斗、指标、实验提供 schema / ORM / API 基础层。
> 实现位置：
> - 模型：`backend/app/db/models/analytics.py`（5 张表 ORM）
> - 服务：`backend/app/services/analytics_service.py`（CRUD + 实验状态机）
> - 路由：`backend/app/routers/analytics.py`（`/api/v1/analytics/*`）
> - Schema：`backend/app/schemas/analytics.py`
> - 迁移：`backend/alembic/versions/028_analytics_tables.py`
> - 测试：`backend/tests/test_analytics_p6an01.py`（42 用例，覆盖 schema/service/HTTP）

## 概述

P6AN-01 是 Phase 6 分析层的**定义层（schema + CRUD）**：落地 5 张分析
数据表 + ORM + Alembic 迁移 + 完整 CRUD API。指标**数值计算**（从会话、
执行日志、CRM 源数据聚合）属于后续 Phase-6 波次，本卡不含实时数据管道、
SQL 自由报表引擎（见任务卡 Out of Scope）。

## 数据模型（5 张表）

| 表 | 说明 | 关键约束 |
|---|---|---|
| `dashboard_widget` | 仪表盘可配置组件 | 软引用 `metric_code`/`funnel_code`（无 FK）；`account_id` FK SET NULL |
| `funnel_step` | 命名漏斗的有序步骤 | `(funnel_code, seq)` 部分唯一（live 行）；`entry_criteria`/`conversion_criteria` JSONB |
| `metric_definition` | 已注册指标（稳定 `code` + JSONB 规格） | `code` 部分唯一（live 行）；`formula` JSONB（无 SQL） |
| `experiment` | A/B / 策略实验生命周期 | `code` 部分唯一；状态机 `draft→running→[paused]→completed/terminated` |
| `experiment_result` | 实验某变体 + 指标的观测结果快照 | `experiment_id` FK → `experiment.id` **CASCADE**；`metric_value` NUMERIC(18,6) |

### 设计约定（与资源层模块对齐）

- **软引用而非硬 FK**：widget / experiment 引用指标、漏斗用 TEXT code，
  不建硬外键 —— 遵循 `channel_config.platform_code` 原则，分析定义可在被
  引用实体存在之前注册。唯一硬外键是 `experiment_result.experiment_id`
  （CASCADE）：两表由本迁移原子创建，fresh 与 legacy 生产库都安全。
- **account_id**：`FK account.id, SET NULL, nullable`，限定定义作用域；
  NULL = 平台级。`account` 自 002（fresh）/026（legacy）即存在。
- **感知时区 UTC 时间戳** + `is_deleted` 软删除 + JSONB 可演进配置
  （`workflow_runtime` / `channel_config` 先例，P2-1 aware-UTC 先例）。

## API（`/api/v1/analytics/*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST / GET | `/widgets` | 创建 / 列表（`widget_type`、`enabled` 过滤 + 分页） |
| GET / PUT / DELETE | `/widgets/{id}` | 详情 / 更新 / 软删 |
| POST / GET | `/funnel-steps` | 注册 / 列表（`funnel_code` 过滤） |
| GET / PUT / DELETE | `/funnel-steps/{id}` | 详情 / 更新 / 软删 |
| POST / GET | `/metrics` | 注册 / 列表（`category`、`enabled` 过滤） |
| GET / PUT / DELETE | `/metrics/{id}` | 详情 / 更新 / 软删 |
| POST / GET | `/experiments` | 创建（draft）/ 列表（`status` 过滤） |
| GET / PUT / DELETE | `/experiments/{id}` | 详情 / 更新 / 软删 |
| POST | `/experiments/{id}/status` | 状态机转换（非法 → 409，terminated 需 reason） |
| POST / GET | `/experiments/{id}/results` | 记录结果快照 / 列表（`variant_label`、`metric_code` 过滤） |
| GET / PUT / DELETE | `/experiment-results/{id}` | 结果详情 / 更新 / 删除 |

错误语义：404 缺失实体；409 唯一性冲突 / 非法状态转换；201 创建；204 删除。

---

## 认证与租户隔离（P6AN-16 / P1-1）

自 P6AN-16 起，**整个 `/api/v1/analytics/*` 表面（含 P6AN-02/03/04/05/06/07/08/09
各 router）都要求认证**——不再有匿名端点。实现位于
`app/security/analytics_access.py`（复用 ADR-011 的 `get_current_principal` /
HS256 Bearer，未新增 token 机制）：

- **两个 guard**：
  - `require_analytics_read` — 所有 **读** 端点（overview / funnel /
    conversations / leads / agents / roi / private-domain / 定义列表 / 详情）。
    最低 read 权：`ANALYTICS_ROLES`（viewer / operator / admin /
    platform_admin）。
  - `require_analytics_write` — 所有 **CRUD 写** 端点。最低 write 权：
    `WRITE_CAPABLE_ROLES`（operator / admin / platform_admin）；`viewer` 只读。
- **401**：缺失 / 无效 / 过期 / 非 UUID 账户的 Bearer token（`get_current_principal`
  上游产生）。**403**：角色低于对应底线；或未绑账户的普通 operator 试图做
  platform-wide（`account_id=NULL`）读——该跨租户读路径在 guard 层即关闭。
- **租户作用域**：读端点的 `account_id` 一律取自 **token**，绝不信任客户端参数。
  调用方只能看到本账户可见数据（经 `agent_persona_binding → agent_customer_binding`
  的 customer/agent 维度 + account-owned 源表）；`account_id=NULL` 的
  platform-wide 定义仅 `PLATFORM_WIDE_ROLES`（admin / platform_admin）可见。
- **CRUD 归属**：create 强制归属调用方账户（客户端 `account_id` 被 `resolve_create_account`
  覆盖/校验，跨租户 → `AccountOwnershipError` → 全局 403 handler）；跨租户按 id 读 /
  改 / 删 → 404（不泄漏账户存在性）。
- **缓存**：dashboard overview 的响应缓存键含租户，跨租户绝不别名。

> 调用方获取 token：`POST /api/v1/auth/token`（P0-1）mint 一个绑定
> `account_id` + `role` 的 operator token；platform-wide 场景由 admin /
> platform_admin 角色 token 承载。测试用 `override_analytics_auth(app,
> test_principal(...))` 直接注入主体（无需真实 JWT）。

---

## P6AN-08 增量（Strategy Experiment 策略实验）

> 任务卡：`t_98039e0f`。在 P6AN-01 定义层之上，把 experiment 的
> `variants`（分组）从自由 JSONB 收紧为**带流量分配规则的分组**，并新增
> 一个**结果统计 / 分组对比**端点。本卡是数据层（definition + 基础对比），
> 不做实验自动生效到 Agent 配置、不引入统计推断库（见任务卡 Out of Scope）。

### 数据模型（复用 P6AN-01 的 `experiment` / `experiment_result`，无新表）

- `experiment.variants` 仍是 JSONB list。P6AN-08 把每个分组规范为
  `{ "label": str, "share": 0..1, "config": dict }`（`share` 别名
  `traffic` / `traffic_share`；字符串数字自动转 float）。
- **分组流量分配规则（all-or-nothing）**：
  只要*任一分组*带了 `share`，提供的所有 share 之和必须 = 1.0（±1e-6）。
  校验发生在 service 层（`_validate_variants`），违例抛
  `AnalyticsConflictError` → HTTP 409。

  | 输入 | 结果 |
  |---|---|
  | 无 share（纯 label/config、纯字符串、P6AN-01 legacy 形态） | 原样放行（向后兼容） |
  | 单分组（`len < 2`） | 不触发求和规则，放行 |
  | 多分组 + share 和 = 1.0（±1e-6） | 接受，share 归一为 canonical `share` |
  | 多分组 + share 和不足 / 超 1 | 409（partial / over allocation） |
  | 任一 share 落在 `[0,1]` 之外 | 409（out-of-range） |
  | share 非数字（如 `"lots"`、`null` 之外的垃圾值） | 409（malformed） |

  理由：流量分配是实验*假设*的一部分——半分配（50% 实验 + 50% 无）或
  超分配都会让"分组指标对比"失去分母一致性，因此规则在写入（create）
  与修改（update）variants 时都强制执行，并在 409 消息里给出**实际求和
  值**便于定位。

- 基线（baseline）变体解析规则（`_baseline_variant_label`）：
  取 variants 里第一个 label 为 `control`（不区分大小写）的分组；否则取
  第一个带 label 的分组；否则无基线（此时不计算 lift）。

### API（在 P6AN-01 路由上追加 1 个端点）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/experiments` | 创建（draft）——P6AN-08 起对 `variants` 流量分配做校验，违例 409 |
| PUT | `/experiments/{id}` | 更新——`variants` 变更时同样校验流量分配，违例 409 |
| **GET** | **`/experiments/{id}/results/summary`** | **P6AN-08 新增**：按指标做分组对比（基础对比，无统计推断库） |

`GET .../results/summary` 查询参数：`significance_threshold`（默认 0.05，
范围 `[0,1]`）——用于"显著"判注（不是置信区间 / 假设检验，只是把
已记录的 `p_value` 与阈值比较）。

响应 `ExperimentResultSummaryResponse`（要点）：

- `baseline_variant` / `significance_threshold`：基线与判注阈值。
- `metrics[]`：每个指标一条，`is_primary`（是否 `primary_metric_code`）。
  指标顺序 = 主指标 → 次指标（`secondary_metric_codes`）→ 其余按 code 排。
- `metrics[].variants[]`：该指标下每个分组的**最新一条**结果快照（同一
  分组×指标有多条时取 `computed_at` 最大；并列取后写入者），含
  `metric_value` / `sample_size` / `p_value` / `is_significant` /
  `lift_vs_baseline_percent`（相对基线，基线缺失或为 0 时为 null）。
- 排序：基线分组恒排第一，其余按 label 升序。
- `note`：纯文字说明——已记录 p_value 的分组按 `p < threshold` 给出
  "significant / not significant"；未记录 p_value 的分组注明"本波不做
  显著性评估（基础对比 only）"。**不引入 scipy / 推断库**（Out of Scope）。
- 顶部 `notes[]`：无结果快照 / 无法解析基线 时给出兜底说明。

错误语义（沿用 P6AN-01）：404 实验不存在；409 流量分配违例；200 正常。

### 代码落点

- 规则：`app/services/analytics_service.py` `_validate_variants` /
  `_variant_share` / `_variant_label`；基线 + 显著性 note：
  `ExperimentService._baseline_variant_label` / `_significance_note` /
  `summarize_results`。
- schema：`app/schemas/analytics.py` `ExperimentResultSummaryResponse` /
  `Metric` / `Row`。
- 路由：`app/routers/analytics.py` `GET /experiments/{id}/results/summary`
  + create/update 对 `AnalyticsConflictError` 返回 409。
- 测试：`tests/test_analytics_p6an08.py`（规则单测 + service + HTTP，
  复用 P6AN-01 fake-session 约定）。

### 遗留 / 后续

- **自动生效到 Agent 配置**：需要 Phase 3 Workflow 联动（本卡仅数据层 +
  基础对比，实验结果不会自动改 Agent 行为）。
- **统计推断**：`p_value` / `is_significant` 目前由调用方在记录
  `experiment_result` 时填入（本卡不计算）；正式的置信区间 / 样本量
  计算 / 功效分析留给后续 Phase-6 波次的统计模块（Out of Scope）。


## 迁移（028_analytics_tables）

- `down_revision = 027_seed_scheduler_queue`。
- **幂等 + 可重跑**：每个 `CREATE` / 索引保护都用 *live* 迁移 bind 查
  当前库态（`to_regclass` / `pg_indexes`），而非缓存的 `inspect(bind)` ——
  缓存 inspector 在 `create_table` 后在事务内是 stale 的，会在 fresh 库上
  静默跳过索引。
- upgrade：建 5 表 + 17 索引（含 3 个 `is_deleted=false` 部分唯一索引）。
- downgrade：按依赖逆序删索引 + 删表。
- 在隔离 scratch 库 `analytics_p6an01` 实测：stamp 027 → upgrade 028 →
  5 表全建；downgrade → 全删；再 upgrade → 幂等重建；FK + 部分唯一索引均在。

## 验证

- 单元测试：`tests/test_analytics_p6an01.py` **42/42 通过**（constants /
  schema 校验 / service CRUD+状态机+冲突 / HTTP 201/204/404/409/422，
  fake-session 隔离，符合本仓测试约定）。
- ORM 回环：在 028 迁移后的 scratch 库上，5 表真实
  INSERT/SELECT/UPDATE/软删 + JSONB/NUMERIC 回环 + 部分唯一索引拒重，
  全部通过（`_orm_roundtrip_p6an01.py`）。
- 实时 API 冒烟：起真 `app.main` 对 scratch 库，跑通全 5 实体 CRUD +
  实验状态机 + 结果记录 + 404/409/422（`_smoke_p6an01_api.py`）。

## P6AN-04 Conversation Metrics（`GET /api/v1/analytics/conversations`）

Phase 6 第二波：AI 对话质量与效率指标。只读聚合 `conversation` /
`message` / `intents` / `agent_customer_binding`（无写入、无 ORM 会话开销），
全部在数据库内完成（共享 `sc` CTE），不产生 10k 级 IN 列表。

### 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `agent_id` | UUID（可选） | 仅统计「客户绑定到该 Agent」的会话（`agent_customer_binding` live 行）。 |
| `range` | 字符串 | 时间窗，按 `conversation.created_at`：`1d/7d/30d/90d/365d`，缺省 `30d`；未知值回退 `30d`。 |
| `intent_type` | 字符串（可选） | 仅统计「至少含一条该类型 live 意图」的会话。 |
| `channel` | 字符串（可选） | 平台 / 渠道过滤（`conversation.channel`，如 wechat/web/douyin）。 |
| `accuracy_threshold` | float（0..1，默认 0.7） | 意图准确率 proxy 的置信度阈值。 |

> 过滤子句按条件拼接：某过滤值为 `None` 时**直接省略该子句与绑定**（asyncpg
> 无法推断裸 `NULL` 绑定类型 → `AmbiguousParameterError`）。

### 五个指标（公式文档化）

记 `C` = 范围内会话数（`sc` CTE 行数），`U` = user 消息数，`I` = live 意图数。

| 指标 | 公式 | 说明 |
|---|---|---|
| `avg_response_time_seconds` | 平均(助手消息 − 其前一条 user 消息的时间差) | 按会话用 `LAG(created_at)` 窗口函数，取「当前 role=assistant 且前一条 role=user」的行求均值；`EXTRACT(EPOCH FROM gap)` 转秒。无配对则 0.0。 |
| `avg_conversation_rounds` | `U / C` | 每轮用户发言计一轮；`C=0` 时 0.0。 |
| `intent_accuracy`（proxy） | 「confidence ≥ threshold **且** matched_action 非空」的意图数 / `I` | V1 无 ground-truth 标签，此为代理指标；`I=0` 时 0.0。 |
| `human_handoff_rate` | 含至少 1 条「升级意图」的会话数 / `C` | 「升级意图」= `intent_type ∈ {complaint, escalation, callback_request}`（与决策引擎 `ESCALATING_INTENTS` 一致）**或** `matched_action = 'escalate'`。`C=0` 时 0.0。 |
| `satisfaction_rate`（proxy） | positive 情感会话数 / 有情感标签会话数 | 用 `conversation.sentiment` 代理满意度（问卷系统 out of scope）；分母 0 时 0.0。 |

辅助 raw 计数一并返回（便于前端展示原始分子/分母）：`total_messages`、
`total_user_messages`、`total_intents`、`confident_intents`、`accurate_intents`、
`escalating_intents`、`handoff_conversations`、`positive_sentiment`、
`with_sentiment`、`avg_confidence`、`avg_duration_seconds`。

### 三个维度聚合

- `by_platform[]`：按 `conversation.channel` 分组（conversations / user_messages /
  avg_rounds / satisfaction_rate / avg_duration_seconds）。
- `by_agent[]`：会话 JOIN `agent_customer_binding` 按 Agent 分组（共享客户会在两个
  Agent 下各计一次，符合「该会话由这些 Agent 负责」的语义；受 `agent_id` 过滤时
  只列该 Agent）。
- `by_intent[]`：按 `intents.intent_type` 分组（total / accurate / avg_confidence /
  accuracy / is_escalating）。

### 空数据 / 性能

- **空范围安全默认**：`C=0` 时 `has_data=false`、五个指标全部 0.0、三个 breakdown
  为空数组——所有除法在纯函数 `_assemble` 内集中守卫，绝不 `ZeroDivisionError`。
- **P95 < 500ms @ 10k**：无 IN 列表，纯索引扫描 + 哈希聚合；10k 行实测见下节。

### 验证（P6AN-04）

- 单元测试 `tests/test_conversation_metrics.py`：**16/16 通过**。
  - 纯函数层：`_safe_ratio` 除零、`resolve_range` 各 token + 回退 + 大小写、
    `_assemble` 空数据默认值 / 指标计算 / 三维度派生字段、升级意图集与决策引擎一致。
  - 真实 PG **对拍**层（`ai_agent_platform_test`，种子确定性数据 + 手算期望值 +
    独立子查询 SQL 复核）：无过滤 / `agent_id` / `intent_type` / `channel` 过滤、
    空范围默认值、窗口边界（30d 排除 31 天前会话、1d 全空）。
- 指标计算文档即本节（DoD：指标计算文档化）。

## 遗留 / 说明

- 整站 `app.main` 启动会在最小 scratch 库上报 `workflow_task` 表缺失的
  后台调度 sweep 错误 —— 这是 **本仓 scratch 库只有分析表、缺 Phase
  1–5 全表** 的产物，与 analytics 模块无关；生产/全量库（含 `workflow_task`）
  不受影响。
- `main.py` 当前同时有并行安全任务（P0-1 `auth_router`）未提交的改动，
  `app.main` 导入态随该任务波动 —— 见看板 hotspot 评论。
