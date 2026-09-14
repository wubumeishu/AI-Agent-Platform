# P5MSG-01 — Message 消息系统后端框架与数据 Schema · API 说明

任务: **P5MSG-01** (t_672cfca8) · Roadmap Phase 2 Message/Conversation 增量
卡片池: P5MSG batch (t_6b5b88e5) · Owner: backend-engineer · 2026-09-14

本卡建立 Message 模块的**后端基础**: `messages` 表 + Alembic 迁移 + FastAPI
路由骨架 + Pydantic schema + 标准响应信封。**不含**查询/发送实现
(P5MSG-02)、渠道适配器 (P5MSG-03)、实时推送 (P5MSG-04)。

---

## 1. 概念边界(重要)

本模块引入的 **`messages` 表(复数)** 是**渠道消息投递/分发记录**, 与既有
**`message` 表(单数, Phase 2 AI 会话聊天稿, role + text, 009_conversation_message)
是两个不同概念、两张不同的表**, 通过 `conversation_id` 共同挂接在
`conversation` 下, 但字段语义完全不同:

| 概念 | 表 | 职责 |
|------|----|------|
| 会话聊天稿 | `message` (单数) | AI 会话内 user/assistant/system 消息, 角色 + 文本 + 编辑次数 |
| 渠道投递记录 | `messages` (复数) | 渠道侧 发出/接收 的投递记录, 生命周期状态 + provider id + 时间戳 |

`Conversation` 模型因此有两条关系: `messages` (聊天稿) 与 `channel_messages`
(渠道投递记录, `ChannelMessage`), 二者互不干扰。

## 2. 数据 Schema — `messages` 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| conversation_id | UUID | **FK → conversation.id, NOT NULL, ON DELETE CASCADE** | 消息必须挂接真实会话 (验收项) |
| account_id | UUID | FK → account.id, SET NULL, 可空 | 渠道账号; 历史投递记录在账号删除后保留 |
| agent_id | UUID | FK → agent.id, SET NULL, 可空 | 执行 Agent |
| channel | varchar(50) | NOT NULL, 默认 `web` | 渠道代码 |
| direction | varchar(10) | NOT NULL, 默认 `out` | `in`/`out` |
| status | varchar(20) | NOT NULL, 默认 `queued` | `queued/sent/delivered/failed/read` (状态机 P5MSG-02) |
| content | JSONB | NOT NULL, 默认 `{}` | 结构化载荷 (文本/媒体引用/平台字段) |
| provider_message_id | varchar(200) | 可空 | 平台侧消息 id |
| sent_at / received_at | timestamptz | 可空 | 发送/接收时间 |
| error | JSONB | 可空 | 失败详情 |
| created_at / updated_at | timestamptz | NOT NULL | |
| is_deleted | boolean | NOT NULL, 默认 false | 软删除 |

索引: `idx_messages_conversation`, `idx_messages_conversation_status`,
`idx_messages_channel`, `idx_messages_created`。

- P5MSG-02 追加的 `receipts`(JSONB) / `last_receipt_at`(timestamptz) 由
  `023_messages_receipt` 迁移承载, 同样挂在 `ChannelMessage` 模型上(共享契约)。

## 3. 迁移 (Alembic)

- **`022_messages_channel`** (P5MSG-01): 创建 `messages` 表 + 4 索引 + 3 FK。
  可独立升/降级; 已在一个干净 PostgreSQL(预置 conversation/account/agent)上
  实测通过 `upgrade` → 校验列/索引/FK/FK 完整性 → `downgrade` → 重新 `upgrade`。
- **`023_messages_receipt`** (P5MSG-02): 追加回执列; 同时把
  `022_lead_conversation_dedup_index` 与 `022_messages_channel` 两个并行
  head **merge 成单一 head**(沿用 `019_linearize_heads` 线性化先例)。

> 已知约束(非本卡引入, 由 `019_linearize_heads` 记录): 迁移链自绝对 base
> 从零不可跑通(`001_crm_lifecycle` 引用了尚未创建的 `customer` 表)。
> 生产库为 legacy 旁路 `create_all` 后 `stamp` 到 head, 仅前向接收后续迁移。
> 本卡的"干净 PostgreSQL"验收 = 预置 Phase 1/2 前置表(即 stamp 到 021)的库。

## 4. 路由骨架

均挂载于 `/api/v1` 前缀下(避免 `/api/v1/api/v1` 双前缀缺陷):

- `GET/POST /api/v1/messages...` — P5MSG-01 骨架, **现由 P5MSG-02 实现**
  (查询/发送/状态机/回执)。
- `GET/POST /api/v1/channels` — P5MSG-01 渠道配置骨架, **P5MSG-03 实现**。
  当前未实现端点统一返回 **4001** 信封。

## 5. 标准响应信封 `{code, message, data}`

沿用 PHASE1-API-SPEC 通用契约 (与 CRM 各路由 `_ok`/`_to_error` 一致),
P5MSG-01 在 `app/schemas/messages.py` 提供共享工具:

- 成功: `{"code": 0, "message": "success", "data": ...}`
- 未实现骨架: HTTP 501 + `{"detail": {"code": 4001, "message": "...: not implemented yet (P5MSG-01 skeleton)", "data": null}}`
- 参数错误: HTTP 400 + `code 4002`

业务错误码: `0` 成功 / `4001` 未实现·资源缺失 / `4002` 参数错误 /
`4003` 非法状态转换(P5MSG-02) / `4004` 资源不存在。

## 6. Pydantic Schema (`app/schemas/messages.py`)

`MessageSendRequest`, `MessageStatusUpdateRequest`, `MessageResponse`,
`MessageListResponse`, `MessageReceipt(Response)`, `ChannelConfigResponse`,
以及值域常量 `MESSAGE_CHANNELS` / `MESSAGE_RECEIPT_SOURCES`。
P5MSG-01 原始命名 `ChannelMessage*` 以别名保留(`= Message*`), 新代码用
`Message*` 规范名。

## 7. 测试

- `tests/test_message_skeleton.py` — P5MSG-01 基础用例(路由注册、渠道骨架
  4001 信封、信封工具、schema 值域、模型/迁移结构), 离线确定性, 不依赖
  活跃 DB。
- `tests/test_message_delivery.py` — P5MSG-02 投递状态机用例(本卡交付后由
  P5MSG-02 拥有)。

## 8. 协作 / 冲突说明

本仓 backend 为**非 git 共享目录**, P5MSG-01/02/03/04 并行读写。P5MSG-01
交付 `messages` 表 + 迁移 + 路由骨架 + schema + 信封契约; P5MSG-02 已在同目录
落地 `app/routers/messages.py` 真实实现、`app/services/message_service.py` 状态机
与 `023_messages_receipt` 迁移, 并在 `Conversation`/`ChannelMessage` 模型上挂接
回执列。P5MSG-01 的 schema/模型作为**共享契约**被 P5MSG-02/03 消费。
冲突热点已按协议在 P5MSG-02 卡片 (t_ac5cd055) 以 `hotspot:` 评论标注。
