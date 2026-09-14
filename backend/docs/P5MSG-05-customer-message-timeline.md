# P5MSG-05 — 会话-消息数据集成 + 客户 360 消息视图 · API 说明

任务: **P5MSG-05** (t_d10eb610) · Roadmap Phase 2 Message/Conversation 增量（CRM 集成部分）
卡片池: P5MSG batch (t_6b5b88e5) · Owner: backend-engineer · 2026-09-14

本卡打通**消息流与 CRM 数据**：`conversation.customer_id` 关联（Phase 3 客户实体，
FK 已存在）、客户 360 页**消息时间线**查询、消息事件**幂等回写 CRM 活动**、
Phase 2 意图数据**落库到会话字段**。**不改** Phase 3 CRM 实体结构（仅消费其
API/实体），**不实现** Phase 5 Private Domain 的 Nurture/跟进任务。

---

## 1. 概念边界

P5MSG 池涉及两类"消息"（详见 P5MSG-01 文档）：

| 概念 | 表 | 角色 |
|------|----|------|
| 会话聊天稿 | `message`（单数） | AI 会话 user/assistant/system 消息 |
| 渠道投递记录 | `messages`（复数） | 渠道侧 发出/接收 投递记录 + 状态机 |

两者都挂在 `conversation.customer_id`（Phase 3 客户实体）下。P5MSG-05 的
**时间线视图把两类消息合并成一条倒序时间线**（`kind=chat|channel` 过滤），
并附带该客户最近的意图识别结果（Phase 2 输出）。

## 2. 新增 / 变更面（无表结构变更，无迁移）

| 文件 | 变更 |
|------|------|
| `app/crm/services/customer_messages.py` | **新增** 时间线聚合 service（两类消息合并 + 过滤 + 意图附加） |
| `app/crm/routers/customer_messages.py` | **新增** 路由骨架（`GET /{customer_id}/messages`） |
| `app/crm/services/message_crm_writeback.py` | **新增** 消息事件 → CRM ActivityLog 幂等回写（bus 订阅者） |
| `app/services/intent_conversation_lander.py` | **新增** 意图数据 → 会话字段落库（bus 订阅者） |
| `app/main.py` | 路由挂载 + 两个 bus 订阅者注册（**增量**，不动 P5MSG-01/02/04 的所有权文件） |
| `tests/test_customer_messages.py` | **新增** 35 测试（纯逻辑 + mock + live Postgres E2E） |

> `Conversation.customer_id` FK、`activity_log` 表、`intents` 表均已在 Phase
> 2/3 存在——本卡**无新表、无新列、无迁移**（因此不与 P5MSG-02 的
> `023_messages_receipt` 等迁移产生 alembic 多头冲突）。

## 3. 客户 360 消息时间线 API

`GET /api/v1/customers/{customer_id}/messages`

响应信封沿用 Customer 360 路由方言：`{"code": 0, "message": "success", "data": {...}}`。

| 查询参数 | 说明 |
|----------|------|
| `conversation_id` | 限定单个会话 |
| `kind` | `chat` \| `channel`（缺省 = 两类合并） |
| `channel` | 按渠道过滤（取 P5MSG-02 的 `MESSAGE_CHANNELS` 域） |
| `direction` | 渠道消息方向 `in` \| `out`（仅作用于 channel） |
| `status` | 渠道投递状态（仅作用于 channel） |
| `start_time` / `end_time` | 时间窗（UTC） |
| `skip` / `limit` | 分页（limit 1..200，默认 20） |

`data` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `customer_id` | string | 回显 |
| `total` | int | 时间线总条数（按 `kind` 过滤后） |
| `messages` | list | 合并后消息（chat + channel），**时间倒序** |
| `recent_intents` | list | 该客户最近 ≤20 条意图识别（Phase 2 输出） |
| `skip` / `limit` | int | 回显 |

单条 `messages[i]`：

- chat 来源：`kind=chat`, `id`, `conversation_id`, `channel`, `role`, `content`, `created_at`
- channel 来源：`kind=channel`, `id`, `conversation_id`, `channel`, `direction`, `status`, `provider_message_id`, `sent_at`, `received_at`, `created_at`

错误映射：

- 客户不存在 / 已删除 → `404` `{"detail": "客户不存在"}`
- 过滤值越域（`kind`/`channel`/`direction`/`status`） → `400` 带具体取值域
- 分页边界（`limit` 越界） → `422`（FastAPI 校验）

## 4. 消息事件回写 CRM（幂等）

`message.created` 事件（由 `app/routers/conversations.py` 在会话消息提交后发布，
in-process bus）→ **CrmMessageEventWriteback** 订阅者，把每条消息记成一条**只读**
CRM 活动（`activity_log`，`activity_type="chat_message"`），供 Customer 360 活动流展示。

**幂等**：`dedup key = "message.created:<message_id>"` 存于 `activity_log.metadata_["event_key"]`
（JSONB `->>` 查询）。命中即 no-op——**重复事件不重复写入**（验收项）。

bus-safe：回写失败只 log + rollback，绝不拖垮共享事件投递（与 `conversation_lead_bridge`
同款隔离）。独立 DB session，持有事务 0。

## 5. AI 意图数据落会话字段

`intent.classified` 事件（由 `app/routers/intents.py` 在识别成功后发布）→
**IntentConversationLander** 订阅者，把该会话**最新一次**识别结果写入
`conversation.metadata_["last_intent"]`（既有 JSONB 元数据字段，非新列）：

```json
{"intent_type": "callback_request", "intent_name": "请求回电",
 "confidence": 0.9, "classified_at": "2026-09-14T06:02:35Z"}
```

**幂等**：按稳定字段（`intent_type`/`intent_name`/`confidence`）比较；相同结果重放
不重写（`classified_at` 是易变时间戳，不参与比较）；不同结果自然覆盖。

时间线 API 通过 `recent_intents` 把这些意图数据**回带**给 Customer 360 视图（验收项
"AI 意图数据落入 conversation/message 字段"）。

## 6. 验收与测试

- `pytest tests/test_customer_messages.py -q` → **35 passed**（纯逻辑 + mock +
  live Postgres E2E，DB 不可达时 live 层自动 skip）
- 实机 E2E（boot 真实 app + TestClient）：时间线 200 信封 + 倒序 + 意图附加、
  `kind=channel` 过滤、404 未知客户、400 越域过滤 —— 全绿
- 实机 bus E2E（`main.startup()` 注册订阅者后发真实 `message.created` /
  `intent.classified` 事件）：CRM 活动**首写 1 行、重复投递仍 1 行**（幂等），
  `last_intent` 落库且重放不重写 —— 全绿

## 7. 已知边界（Out of Scope）

- 渠道发送执行（P5MSG-03 ChannelAdapter）、实时推送（P5MSG-04）
- 修改 Phase 3 CRM 实体结构 / 建 nurture 跟进任务
- Phase 6 Analytics 的 Conversation Metrics
