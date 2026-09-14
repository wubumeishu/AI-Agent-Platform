# P5MSG-02 — 消息 API 与投递状态管理 · API 说明

任务: **P5MSG-02** (t_ac5cd055) · Roadmap Phase 2 Message/Conversation 增量
卡片池: P5MSG batch (t_6b5b88e5) · Owner: backend-engineer · 2026-09-14

本卡在 P5MSG-01 的 `messages` 表骨架之上实现**消息查询、发送(API 层入队)、
已读回执与投递状态机**。不含实际渠道发送执行 (P5MSG-03)、实时推送
(P5MSG-04)、Phase 6 Analytics 的 Conversation Metrics。

---

## 1. 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/messages` | 分页 + channel/direction/status 过滤 |
| GET | `/api/v1/messages/{id}` | 单条渠道消息 |
| POST | `/api/v1/messages/send` | 入队 (status=queued) |
| POST | `/api/v1/messages/{id}/status` | 投递状态机 |
| GET | `/api/v1/messages/{id}/receipt` | 投递/已读回执审计轨迹 |

> 路由顺序约定: 静态路径 (`/send`) 先于动态 `/{message_id}` 注册, 否则会被
> UUID 参数捕获返回 422。

## 2. 响应信封 (PHASE1-API-SPEC)

成功: `{"code": 0, "message": "success", "data": ...}`
失败: HTTP 4xx + `{"code": <业务码>, "message": <说明>, "data": null}`

业务码:
- **4001 / 4004** — 资源不存在 (会话 / 账号 / 消息)
- **4002** — 参数错误 (未知 channel/direction/status, account 平台不匹配)
- **4003** — 非法状态转换

## 3. GET /api/v1/messages (分页过滤)

查询参数:
- `conversation_id` (UUID, 可选)
- `channel` (str, 可选)
- `direction` (`in`/`out`, 可选)
- `status` (`queued/sent/delivered/failed/read`, 可选)
- `page` (int, 默认 1, `ge=1`)
- `page_size` (int, 默认 20, `ge=1`, `le=100`)

边界: `page>=1`, `1<=page_size<=100` 越界返回 422; 越界 filter 值 (未知
channel/direction/status) 返回 4002。`page` 越过末页返回空 items + 正确 total。

## 4. POST /api/v1/messages/send (入队)

请求体 (`MessageSendRequest`):
- `conversation_id` (UUID, 必填)
- `account_id` (UUID, 可选)
- `agent_id` (UUID, 可选)
- `channel` (默认 `web`)
- `direction` (默认 `out`)
- `content` (JSONB object, 必填且非空)
- `provider_message_id` (可选)

Phase 1 资源层校验 (业务码):
- 会话不存在 → 4001/4004
- `account_id` 不存在 → 4001/4004
- `account_id` 所属平台代码与 `channel` 不匹配 → 4002
  (例外: `channel == "web"` 是平台渠道, 不要求账号绑定)

入队成功后返回 `{"id": ..., "status": "queued", "enqueued": true}`, 并写一条
`execution_log` (execution_type=`message_status`, from=(none), to=queued)。

## 5. 投递状态机

```
queued ──► sent ──► delivered ──► read
  │        │
  └──────┴──► failed (error 记录)
```

- 合法: `queued->sent`, `sent->delivered`, `sent->read`, `delivered->read`,
  `queued->failed`, `sent->failed`
- 拒绝: 其余一切 (含 skip `queued->delivered`、回退 `delivered->sent`、
  终态 `read`/`failed` 的任意后继) → 4003
- `failed` 必须带 `error` 详情 (schema 层 422)
- `sent` 记 `sent_at`; `delivered`/`read` 记 `received_at`
- 每个被接受的 transition 写一条 `execution_log` 并 append 到
  `receipts` (JSONB 审计轨迹, `{status, at, source, error?, provider_message_id?}`)

### POST /api/v1/messages/{id}/status

请求体 (`MessageStatusUpdateRequest`):
- `status` (目标状态)
- `error` (status=failed 时必填)
- `provider_message_id` (可选)
- `source` (`provider`/`manual`, 默认 `manual`)

### 并发 (P5MSG-D1 修复)

`update_status` 通过 `SELECT ... FOR UPDATE` + `populate_existing=True` 行锁
串行化并发 transition:
- 两个并发 transition 在同一行上不再互相静默覆盖 (last-writer-wins 丢更新);
- 第二个 transition 在第一个提交后重读 status, 要么做合法下一跳要么被
  4003 拒绝;
- `receipts` 与 `execution_log` 不再丢失任何一条记录。

> 关键: `populate_existing=True` 不可省 — 若 session 的 identity map 已缓存
> 该行 (长活/共享 session, 或复用入队时的 session), SQLAlchemy 会返回缓存的
> 陈旧对象, 在 ORM 层复现丢更新, 即使 DB 锁已持有。

## 6. GET /api/v1/messages/{id}/receipt

返回当前投递状态 + 完整 receipts 审计轨迹:
```json
{
  "code": 0, "message": "success",
  "data": {
    "message_id": "...", "status": "read",
    "error": null, "provider_message_id": null,
    "sent_at": "...", "received_at": "...", "last_receipt_at": "...",
    "receipts": [
      {"status": "sent", "at": "...", "source": "provider", "error": null},
      {"status": "delivered", "at": "...", "source": "provider", "error": null},
      {"status": "read", "at": "...", "source": "provider", "error": null}
    ]
  }
}
```
消息不存在 → 4001/4004。

## 7. 数据 Schema 变更 (P5MSG-02 增量)

在 P5MSG-01 的 `messages` 表上, 由迁移 `023_messages_receipt` 追加:

| 字段 | 类型 | 说明 |
|------|------|------|
| `receipts` | JSONB, 可空 | 投递/已读回执的 append-only 审计轨迹 |
| `last_receipt_at` | timestamptz, 可空 | 最近一次回执时间 |

索引: `idx_messages_last_receipt_at`。

`023_messages_receipt` 是 **merge migration** (down_revision 同时指向
`022_lead_conversation_dedup_index` 与 `022_messages_channel`), 沿用
`019_linearize_heads` 的线性化先例, 把并行分支归一到单一 head。幂等: 列
存在性预检 + `IF NOT EXISTS` / `if_not_exists=True`。

## 8. 测试

- `tests/test_message_delivery.py` — 53 用例:
  - 纯状态机逻辑 (全路径 + 终态 + skip 拒绝 + filter 域校验)
  - Pydantic schema 校验 (send / status / receipts)
  - 服务层 mock DB (入队、账号绑定、状态转换矩阵、回执组装、分页边界、错误映射)
  - **真 Postgres 集成** (不可达时自动 skip): 完整投递生命周期、execution_log
    校验、未知账号 4001、平台不匹配 4002、分页边界、**P5MSG-D1 并发无丢更新回归**
  - 路由接线 + main.py 挂载 + `update_status` 行锁静态守卫
- 真 API 路径 E2E (httpx ASGITransport, 测试库): 20 项全绿 (list / send /
  get / 状态机全路径 / receipt / 4003 拒绝 / 4002 平台不匹配 / 4001 未知账号 /
  422 分页越界)。

## 9. 验收对照

| 验收项 | 状态 |
|--------|------|
| 发送后消息可查, 状态转换有日志 | ✅ send 入队可查; 每次转换写 execution_log + receipt |
| 非法状态转换被拒绝 | ✅ 4003 (含 skip / 回退 / 终态后继) |
| 分页/边界参数校验测试通过 | ✅ page/page_size 边界 422; 越界页返回空 items |
| 迁移可升/降级 | ✅ 023 DDL 在干净 PG 上 upgrade/downgrade/re-upgrade 验证 |
| 并发无丢更新 (P5MSG-D1) | ✅ FOR UPDATE + populate_existing; 回归测试 5 轮竞态全绿 |

## 10. 与 P5MSG-01 共享文件的协调说明

本卡与并行的 P5MSG-01 (t_672cfca8) 共享同一非 git 后端目录, 双方都写
`app/schemas/messages.py` / `app/routers/messages.py`。协调结果 (已落盘合并,
非覆盖):
- P5MSG-01 保留其 scaffold 契约: `ApiCode` / `ok` / `not_implemented` /
  `bad_request` / `ChannelMessage*` 别名 + `/api/v1/channels` 骨架;
- P5MSG-02 在其上叠加真实实现: `MessageSendRequest` / `MessageStatusUpdateRequest`
  / `MessageReceipt*` + `/api/v1/messages/*` 的查询/发送/状态机/回执;
- `MESSAGE_CHANNELS` 含 Phase-1 ChannelType 域 + V1 平台注册
  (wechat/douyin/xiaohongshu) + `web`。

P5MSG-02 专属、无冲突的文件: `app/services/message_service.py`,
`alembic/versions/023_messages_receipt.py`, `tests/test_message_delivery.py`,
`app/db/models/messages.py` (receipt 列)。

已知 out-of-scope 的既有失败 (非本卡引入):
- `tests/test_message_skeleton.py::test_p5msg01_routes_registered_in_app` —
  P5MSG-01 自有的 naive `.app.routes` 路由自省, 在本 FastAPI 版本的
  `_IncludedRouter` 惰性包裹下不可见; P5MSG-02 路由经 OpenAPI + 真 API E2E
  已确认注册可达。
- `tests/test_data_integrity.py` (private-domain `get_account_channel_stats`) —
  本卡未触碰该模块的既有 mock/代码漂移。
