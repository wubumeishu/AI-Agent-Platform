# Workflow-CRM Integration（线索跟进自动化）

> Task: `t_4f31af5e` · Module owner: `backend-engineer` · Phase: 4/5 integration
> Scope: CRM Action（创建/更新 Lead、添加 Tag、变更 Lifecycle Stage）+ Trigger 监听 Lead/客户标签状态变更 + Condition 检查标签/阶段 + Workflow 触发时自动关联 CRM 实体 + 集成测试。
> Out of scope: 复杂 CRM 规则引擎、双向 CRM 数据同步、跨平台客户聚合。

## 架构分层（符合架构分离原则）

```
CRM 服务层（lead / tag / lifecycle / customer）
   │  commit 之后发布领域事件（仅携带 entity 指针，不携带业务逻辑）
   ▼
app.events.DomainEventBus（进程内事件总线，V1 可换 Redis）
   │  订阅
   ▼
app.services.workflow_crm.WorkflowCrmExecutor（集成执行器）
   │  查活跃 Workflow → 匹配 Trigger → 评估 Condition（读 CRM 实体标签/阶段）
   │  → 执行 Action（复用 CRM service，业务规则留在 CRM 层）
   ▼
ExecutionLog（可观测性 / 审计，t_wf_005）
```

**关键原则：** CRM 服务不写 workflow 逻辑，workflow 层不写 CRM 业务规则；集成层只做"编排 + 转发"，所有业务规则（状态流转校验、标签计数、阶段审计日志）仍留在 CRM service。CRM 服务仅发布指针事件，执行器在匹配时**重新读取**当前状态，因此事件即便排队也不产生脏数据。

## 领域事件词汇（`app.events.domain_events`）

| 事件 | 发布方 | 触发时机 |
|------|--------|----------|
| `lead.created` | `lead.create_lead` | 新 Lead 落库后 |
| `lead.status_changed` | `lead.update_lead` | 状态实际变化（幂等：无变化不发） |
| `lead.stage_changed` | `lifecycle.transition_lifecycle_stage` / `lead.update_lead` | 生命周期阶段实际变化 |
| `lead.tags_changed` | `tag.add_tags_to_lead` / `remove_tag_from_lead` | 标签关联实际变化 |
| `customer.tag_changed` | `tag.add_tags_to_customer` / `remove_tag_from_customer` | 客户标签关联实际变化 |
| `customer.created` | `customer.create_customer` | 新客户落库后 |

事件携带 `event_type / entity_type / entity_id / payload`；payload 保持最小（`old_*`、`new_*`、`operator`），实体细节在执行器侧按需重读。

## 事件发布 / 触发 两条路径

1. **自动路径（请求级 autoflush）**
   - CRM service 在 commit 后调用 `get_crm_publisher().publish_nowait(event)` 把事件入队；
   - `main.py` 注册的原生 ASGI 中间件 `_WorkflowCrmAutoflush` 在**每个非流式响应**之后调用 `publisher.flush()` 派发事件；
   - SSE（`/messages/stream`）路径被显式跳过，避免中间件缓冲破坏流式响应。
   - 订阅者在独立 DB session 中执行，订阅者失败**永不**回滚/阻塞发布方请求。

2. **手动路径（`POST /api/v1/workflow-crm/trigger`）**
   - 不依赖事件总线，单次 HTTP 调用即可驱动 `match → condition → action → ExecutionLog` 完整链路，用于测试与运维。

## API 端点（`/api/v1/workflow-crm`）

> 注意：本仓库 CRM router 存在双前缀 quirk（`/api/v1/api/v1/crm/...`，见既有 `PHASE1-API-SPEC.md`），workflow-crm 端点使用单前缀 `/api/v1/workflow-crm/...`。

### POST `/api/v1/workflow-crm/trigger`
手动驱动 CRM 事件。
- 请求体（`WorkflowCrmTriggerRequest`）：
  - `event_type`（可选，缺省 `manual`）
  - `entity_type`（`lead` | `customer`，缺省 `lead`）
  - `entity_id`（必填）
  - `workflow_id`（可选，只跑该 workflow）
  - `force`（可选，跳过 trigger 事件类型匹配）
  - `payload`（任意 dict）
- 响应（`WorkflowCrmTriggerResponse`）：`status` ∈ `success|failed|skipped|no_match`、`matched/executed/failed/skipped` 计数、每个 workflow 的 `conditions[]`（表达式/求值结果/是否通过）与 `actions[]`（动作/结果/detail）、以及每次运行写下的 `execution_log_id`。

### POST `/api/v1/workflow-crm/dispatch-now`
把队列中自上次派发以来累积的所有 CRM 事件立即执行。返回 `{dispatched_events: int}`。自动路径已开启时通常为 0。

### POST `/api/v1/workflow-crm/register`
（重新）注册执行器为全部 CRM 事件类型订阅者，幂等。返回 `{subscribed_events: int}`。

### GET `/api/v1/workflow-crm/health`
自检：`subscriber` 是否已注册、`subscribed_events` 列表、当前 `active_workflows` 数量。

## Condition 求值

`WorkflowCondition.expression` 为 JSON：`{"field", "operator", "value"}`。
- 字段命名空间（点号路径）：
  - `event.<key>`：触发事件本身（`type`/`entity_type`/`entity_id` 或 payload 任意 key）
  - `lead.<field>`：重读该 Lead（`status`、`stage`（=lifecycle_stage_code）、`tags`（→标签名列表）、`customer`、`intent_score`…）
  - `customer.<field>`：重读该 Customer（`name`/`email`/`phone`/`company`/`tags`…）
- 算子（`CONDITION_OPERATORS`）：`eq neq gt gte lt lte in not_in contains regex`。
- 执行语义（V1，无表达式引擎）：**某 Condition 的 Action 当且仅当该 Condition 通过时执行**；存在 Condition 但全不通过 → trigger `skipped`；否则执行所有通过 condition 的 actions，任一 action 失败 → trigger `failed`。

## Action 词汇（复用 CRM service，不新建）

| action_type | 参数 | 底层调用 |
|-------------|------|----------|
| `tag` | `target`(lead/customer), `entity_id`, `tag_ids[]`, `operation`(add/remove) | `add_tags_to_lead/customer`、`remove_tag_from_lead/customer` |
| `status_change` | `entity_id`, `new_stage`（生命周期阶段）或 `new_status`（lead 状态） | `transition_lifecycle_stage` / `update_lead` |
| `create_lead` | `customer_id`, `source_type`, `status`, `intent_score`, `notes`, `operator` | `create_lead` |
| `update_lead` | `entity_id`, `updates{}`, `status`, `notes`, `operator` | `update_lead` |
| `custom` | `action`（上述子动作之一）+ 子动作参数 | 路由到对应子动作 |
| `message` / `conversation` / `notification` | — | V1 标记 `unsupported`（属于 AI/对话集成，不在本切片） |

## 测试（`tests/test_workflow_crm.py`，45 用例全绿）

- 事件总线：订阅/通配/异常隔离/nowait 队列/重置
- 纯算子求值（含缺失值、未知算子）
- 实体重读（event / lead / customer 字段、tags→名、缺失实体）
- Trigger 匹配（事件匹配、禁用、scheduled 排除、通配 `*`、force 语义）
- 每 Condition 执行（通过才跑、全不通过→skipped、无 condition→无条件、action 失败→failed）
- Action 路由（custom 子动作、unsupported、unknown）
- 订阅接线幂等
- **真实 Postgres 集成**（DB 不可达时自动 skip）：建 tag+lead → 建 active workflow（event trigger + condition + tag action）→ `update_lead` 触发 → 断言 tag 落库 + ExecutionLog 写入。

## 已知遗留 / hotspot（非本任务引入，需下游协同）

1. **迁移编号冲突**：`015_workflow_config`、`015_workflow_framework`、`016_scheduler_due_index`、`016_workflow_task` 多个 015/016 并存（并行任务各写一个），Alembic 单链假设被破坏，需统一编号或合并。
2. **`schemas/workflow.py` 双份**：t_wf_001 与 t_wf_002 均往同一文件追加 schema，存在重复/命名碰撞（本任务刻意只用 model 层，未 import 该 schema，规避了此冲突）。
3. **既有测试失败**（与本任务无关，已定位）：
   - `tests/test_tag_service.py` 4 例：mock `side_effect` 只喂 3 个结果，但双 tag 循环需 4+ 次 `execute`。
   - `tests/test_workflow_conversation_integration.py`：收集期 ImportError（t_cc6aa406 正在写，文件未定稿）。
   - `test_data_integrity.py` / `test_memory_api.py` / `test_phase2_integration_qa.py` / `test_tag_api.py`：共享库表未建 + 双前缀 404，属仓库整体状态。
4. **`create_lead` 500 修复**：`LeadCreate.tags` 默认 `None`，router 直接 `model_dump()` 进 ORM 构造器会 `TypeError: Incompatible collection type: None`。本任务在 `create_lead` 加了 3 行守卫（`tags is None` 时剔除该 key）解除验收路径阻塞；`create_lead_from_conversation` 因自构建 dict 无 `tags` 键、无需改。
