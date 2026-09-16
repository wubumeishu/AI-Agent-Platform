# Workflow ↔ Conversation 集成 — 实现与 API 文档

**Task:** t_cc6aa406 · **Owner:** backend-engineer · **Date:** 2026-09-14
**Repo:** `H:/AI-Agent-Platform/backend`

## 目标

让工作流（Workflow）可以基于对话事件自动回复与跟进：对话/消息/意图事件
触发已配置的 event-trigger 工作流，经过条件判定后执行对话动作
（创建对话、发送 AI 回复、打标签），并把每次执行写入 ExecutionLog。

## 架构与分层

事件总线复用平台既有的 in-process 总线（`app/events/domain_events.py`，
t_4f31af5e 引入），本任务不重复造总线：

```
对话/意图 生产者 (routers)
   |  publish DomainEvent
   v
DomainEventBus (共享进程内总线)
   |  按 event_type 分发给对应域订阅者
   v
WorkflowConversationBridge (app/services/workflow_conversation_bridge.py)
   |  1. 找到 status=active 且 trigger.spec.event 匹配的工作流
   |  2. 评估每个 condition (field/operator/value)
   |  3. 通过条件的 actions: conversation / message / tag / notification
   v
ConversationService / AIResponder (默认 TemplateResponder)
   |
   v
ExecutionLog (观测: input/output/status/error/duration)
```

### 架构分离原则（本任务的关键约束）

- **事件词汇表按域拆分**（`app/events/domain_events.py`）：
  - `EVENT_TYPES` = CRM 事件（6 个），仅被 workflow-CRM 执行器订阅。
  - `CONVERSATION_EVENT_TYPES` = 对话事件（3 个），仅被本 bridge 订阅。
  两个执行器订阅**互不相交**的键集合，CRM 通配 trigger 不会误触发对话事件，
  反之亦然。`DomainEvent.entity_type` 作为二级判据，bridge 只处理
  `conversation | message | intent` 实体。
- **AI 供应商隔离**：bridge 依赖可注入的 `AIResponder`（默认
  `TemplateResponder`，确定性、零外部依赖）；OpenAI/Anthropic 适配可在
  不改动本模块的前提下替换。
- **平台隔离**：对话动作只通过 `ConversationService` 写对话，不涉及
  BitBrowser / 平台特定逻辑。
- **失败隔离**：总线 handler 异常不上抛（不拖垮发布者请求）；单个工作流
  执行异常不影响其它工作流；单个 action 异常记为 `failed` 记录而非中断
  后续 action；默认订阅者每个事件用独立 DB session，绝不持有发布者事务。
- **无敏感数据进总线**：事件 payload 只带 id、intent 类型/置信度、channel，
  从不带消息正文或凭据（ARCHITECTURE #16）。

## 对话事件（3 个）

| event_type             | entity_type | entity_id  | 发布者                          |
|------------------------|-------------|------------|--------------------------------|
| `conversation.created` | conversation | 对话 id    | `POST /conversations`          |
| `message.created`      | message      | 消息 id    | `POST /conversations/{id}/messages` |
| `intent.classified`    | intent       | 会话 id*   | `POST /intents/classify`（仅分类成功时）|

\* intent 的 `entity_id` 用 `conversation_id`（意图没有独立行 id 的实体，
用所属会话做实体锚点，与 CRM 侧 `entity_id` 语义一致）。

## 触发器配置（沿用 t_wf_002 模型）

event trigger 的 `spec`：

```json
{ "event": "message.created", "topic": "message" }
```

- `event`：匹配的事件名；`*` 或省略 = 该 trigger 匹配任何事件（通配）。
- `topic`（可选）：必须等于事件的 `entity_type` 才触发；省略 = 不限实体类型。

workflow 的 `config` 可放共享参数（action 上下文）：

```json
{ "persona_name": "小助手", "customer_id": "<uuid>", "channel": "wechat" }
```

## 条件（沿用 t_wf_002 模型）

`condition.expression` 是 JSON 表达式：

```json
{ "field": "intent_type", "operator": "in", "value": ["question", "greeting"] }
```

`field` 走点分路径解析 action 上下文（顶层键：`intent_type`、
`intent_confidence`、`customer_id`、`conversation_id`、`message_id`、
`channel`、`payload`...）；支持 `eq neq gt gte lt lte in not_in contains
regex`。未知字段严格判失败；空表达式视为恒通过。

## 动作（本任务实现）

| action_type | 行为 |
|-------------|------|
| `conversation` | 按 context 的 `customer_id` 创建对话（缺则跳过/失败） |
| `message` | 生成回复并追加到目标会话（`params.conversation_id` → 事件 payload 的会话 → 按 customer 新建）。`params.template` 优先；否则走 `AIResponder` |
| `tag` | 给 `customer_id` 打 `params.tag_name` 标签（自动建 Tag） |
| `notification` / `custom` | V1 仅记录到 ExecutionLog，延后到后续 wave |

## 新 API

### `POST /api/v1/workflows/{workflow_id}/triggers/fire`

手动/验收入口：把一个合成 DomainEvent 走一遍真实 trigger→condition→action
链路，无需等待真实消息。

```jsonc
// 请求
{ "event": "message.created",
  "entity_type": "message",        // 默认 "message"
  "entity_id": "<uuid>?",
  "payload": { "conversation_id": "<uuid>", "intent_type": "question" } }

// 响应 200
{ "fired": true, "workflow_id": "...",
  "execution_log_id": "...", "error": null }
```

错误：`404` workflow 不存在；`400` workflow 非 `active` 或无匹配 trigger
（`fired=false` + `error` 说明）。

## 默认订阅（`main.py` startup）

`register_workflow_conversation_subscriber()`（幂等）把 bridge 订阅到全部
3 个对话事件类型；每个事件独立 DB session。与 CRM 的
`register_workflow_crm_subscriber()` 并列注册，互不干扰。

## 测试

`tests/test_workflow_conversation_integration.py`（38 例，全通过）覆盖：

- 域总线投递语义（typed/wildcard 订阅、handler 失败隔离、reset、
  publish_nowait+dispatch 顺序）
- trigger 匹配（精确/通配/`topic` vs `entity_type`）
- 条件求值（全部 operator + 点分路径 + 未知字段/operator 严格判失败）
- 动作执行（显式模板 / AI responder / 自动建会话 / 跳过 / 失败捕获）
- 端到端：event → 工作流 → ExecutionLog（success / 条件阻断 / 失败）
- `handle_domain_event` 只处理对话实体类型（CRM 事件直接忽略）
- 生产者发布（conversation/intent 路由）与 `/triggers/fire` 契约
- 默认订阅注册幂等性

无阻塞性错误；无 AI provider 也能跑通全链路（确定性 TemplateResponder）。

## 范围外（后续 wave）

- 实时对话流处理、多轮对话状态管理、对话语义分析、质量自动评估
- 跨进程事件传输（Redis pub/sub 替换 in-process 总线，接口不变）
- `notification` / `custom` 动作的真实执行器
