# P5MSG-03 — 渠道集成 (Channel Adapter + BitBrowser 渠道发送) · API 说明

任务: **P5MSG-03** (t_0b5802f2) · Roadmap Phase 2 Message/Conversation 模块 + Phase 5 渠道集成增量
卡片池: P5MSG batch (t_6b5b88e5) · Owner: backend-engineer · 2026-09-14

本卡在 P5MSG-01 (`messages` 表 / 4001 骨架) + P5MSG-02 (消息 API + 投递状态机) 之上，
通过 Phase 1 的 `BrowserProvider` (BitBrowser) 抽象实现**渠道消息收发适配器**：
`ChannelAdapter` 抽象接口 (send/receive/poll)、渠道配置 CRUD (`/api/v1/channels`)、
走 BitBrowser Provider 打开目标平台会话页并发送/拉取消息 (V1 仅 BitBrowser, ADR-002)、
以及 per-channel 的重试与限频策略。

**分层约定 (架构合规)**: 平台 *怎么做* (BitBrowser 开页 / 打字 / 拉取) 隔离在
`app/adapters/` 平台适配器里；业务 *做什么* (限频门 / 重试 / 状态机推进 / 持久化) 在
`app/services/` 业务服务里。router 只做二者组合 (API → Service → Data)，不含业务规则。

---

## 1. 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET    | `/api/v1/channels`              | 渠道配置列表 (分页 + channel/account/enabled 过滤) |
| GET    | `/api/v1/channels/{id}`        | 单个渠道配置 |
| POST   | `/api/v1/channels`             | 创建渠道配置 (201) |
| PUT    | `/api/v1/channels/{id}`        | 更新渠道配置 (部分字段) |
| DELETE | `/api/v1/channels/{id}`        | 软删除渠道配置 |
| POST   | `/api/v1/channels/deliver`     | 投递一条 queued 出站消息 (适配器 + 重试 + 限频) |
| POST   | `/api/v1/channels/poll`        | 拉取某会话的入站消息 (适配器 receive) |

> 路由顺序约定: 静态路径 (`/deliver` / `/poll`) 先于动态 `/{channel_id}` 注册 (与
> P5MSG-02 的 `/send` 同规则)，否则被 UUID 参数捕获返回 422。

## 2. 响应信封 (PHASE1-API-SPEC)

成功: `{"code": 0, "message": "success", "data": ...}`
失败: HTTP 4xx + `{"code": <业务码>, "message": <说明>, "data": null}`

业务码:
- **4002** — 参数错误 (未知 channel/type、越界值、重复的 account 绑定、不支持的渠道)
- **4004** — 资源不存在 (渠道配置 / 消息不存在)

## 3. ChannelAdapter 抽象 (app/adapters/channel_adapter.py)

```
ChannelAdapter (ABC)
├── adapter_name        -> str
├── supported_channels() -> Set[str]
├── async send(content, target=None) -> SendResult
├── async receive(limit, since=None) -> List[ReceivedMessage]
└── async poll(...)      (默认委托 receive)

ChannelAdapterRegistry          # channel code -> adapter 映射
├── register(adapter)
├── adapter_for(channel)        # 无注册渠道 -> UnsupportedChannelError (4002)
└── known_channels()
```

V1 具体实现 `BitBrowserChannelAdapter` (consumes Phase-1 `BrowserProvider`，不重造其内部):
- `test_connection()` 判定 mock vs real。**BitBrowser SDK 不可用 (Phase 1 已知
  blocker) → mock_mode**：send 返回合成 `provider_message_id` (`mock_*`) 且 `mock=True`；
  receive/poll 返回空 (无真实入站源)。这就是验收标准 "至少 1 个 V1 渠道端到端
  发送成功" 在 fallback 现实下走的路径。
- real mode 需一个可注入的 `driver` (开页/打字/拉取)。V1 不接 DOM driver：未注入时
  报 `page_drive_unavailable` 而不是伪造结果；未来 Phase-5/6 DOM driver 从此缝插入，
  不动业务层。
- 支持的 V1 渠道码: `wechat` / `douyin` / `xiaohongshu`。

## 4. 渠道配置 CRUD (channel_config 表, 迁移 024_channel_config)

`ChannelConfig` 字段: `channel` (MESSAGE_CHANNELS 域), `type` (messaging/comment/web),
`platform_code` (软引用, 非硬 FK), `account_id` (FK → account.id, SET NULL, 可空),
`rate_limit_per_hour` (默认 60), `retry_max_attempts` (默认 3),
`retry_backoff_seconds` (默认 5), `enabled` (默认 true), `is_deleted`。

唯一性: 部分唯一索引 `(channel, account_id, platform_code) WHERE account_id IS NOT NULL
AND is_deleted = false` — 每个 (渠道, 账号, 平台) 至多一条 live 配置；**无账号**
(account_id NULL) 的配置不受此约束 (可并存多条)。

- POST 创建：未知 channel/type → 4002 (schema 校验)；重复的 account 绑定 live 配置 → 4002
  (冲突)。201 返回。
- PUT 更新：仅应用 set 字段；触发唯一键变化的更新先做冲突检查 → 4002。
- DELETE 软删除 (is_deleted=true)，幂等；之后 GET 单条 → 4004。
- 无账号配置不受唯一约束：同 channel 的多条 account-less 配置允许并存 (设计使然)。

## 5. POST /api/v1/channels/deliver (投递)

请求体 (`ChannelDeliverRequest`): `message_id` (UUID), `attempt_backoff_seconds` (可选,
覆盖配置 backoff，测试/显式调用用)。

流程 (ChannelDeliveryService.deliver_message):
1. 载入消息 (必须 `queued` + `out`，否则 4002 参数错)。
2. 载入 per-channel 策略 (rate limit / retry max / backoff / enabled；无配置行走默认)。
   channel 被禁用 → ChannelDeliveryError (4002)。
3. **限频门**：超过 hourly 上限 → 不重试、直接把记录推进到 `failed` 并写
   `error.code = "rate_limited"` (可观测)。
4. 重试循环调用 `adapter.send` (最多 retry_max 次，尝试间隔 backoff 秒)。
5. 成功 → P5MSG-02 状态机推进到 `sent` (写 receipt + execution_log)；
   全部失败 → 推进到 `failed` + 记录结构化 `error` (绝不含密钥)。

响应 (`ChannelDeliverResponse`): `message_id`, `status` (sent/failed),
`provider_message_id`, `error` (dict|null), `delivered` (bool), `mock` (bool),
`provider` (str)。限频尝试也作为 `failed` outcome 返回 (带 `rate_limited` error)，
不需特殊分支。

## 6. POST /api/v1/channels/poll (拉取入站)

请求体 (`ChannelPollRequest`): `channel`, `conversation_id`, `account_id` (可选),
`limit` (默认 20), `since` (可选)。

通过适配器 `receive` 拉取入站消息，按 provider id 去重后持久化为 `in`/`queued` 渠道记录。
V1 mock 适配器无入站源 → 返回 `polled: 0`。响应 (`ChannelPollResponse`):
`channel`, `conversation_id`, `polled` (int), `provider_message_ids` (list)。

## 7. 验收映射 (本卡 Acceptance Criteria)

- **至少 1 个 V1 渠道端到端发送成功** — `TestChannelDeliveryLive::test_wechat_end_to_end_send_succeeds`
  (wechat: enqueue → deliver → `sent` + `mock_*` provider id + receipt 审计，走 mock fallback)。
- **频率限制生效** — `test_rate_limit_takes_effect` (limit=0 的确定性 limiter：adapter
  不被调用，记录标 `failed`/`rate_limited`)；live API smoke 中 limit=2 下第 3 条被限频。
- **发送失败自动标记 failed 并记录 error** — `test_failed_delivery_records_error`
  (脚本 adapter 3 连败 → `failed` + 结构化 error + `attempts`)。

## 8. 测试

`tests/test_channel_delivery.py` — 33 通过 (0 skip, Postgres up):
- `TestChannelAdapterRegistry` (纯): 渠道码映射 / 不支持渠道错误 / known_channels。
- `TestChannelRateLimiter` (纯): 小时桶语义 / 滚桶 / limit<=0 禁用 / 线程安全 / 不泄密钥。
- `TestBitBrowserAdapterMock` + real: mock-mode 契约 + 注入 driver 的 real-mode 路径。
- `TestChannelConfigServiceMock`: 域校验 / 重复绑定冲突 / 软删除 (mock session)。
- `TestChannelDeliveryServiceMock`: 成功 / 重试-败-终 / 限频门 / poll 去重 (脚本 adapter, 无 DB)。
- `TestChannelRouterWiring`: 路由顺序 / schema 校验 / 迁移链 (024 → 023) / 响应形状。
- `TestChannelDeliveryLive`: 真 Postgres E2E (enqueue→deliver→sent / 限频 / 失败记 error)。

回归 (P5MSG-01/02/03/05 合并套件): **164 通过**。
- P5MSG-01 `tests/test_message_skeleton.py`: 本卡已实现 channels 路由，故把 P5MSG-01 的两条
  过期断言更新 (naive `app.routes` 内省 → OpenAPI；4001 骨架断言 → 已实现路由断言)，
  其余 P5MSG-01 契约不变。

## 9. 变更文件 (P5MSG-03)

- `app/adapters/channel_adapter.py` — ChannelAdapter / SendResult / ReceivedMessage /
  ChannelAdapterRegistry / UnsupportedChannelError。
- `app/adapters/bitbrowser_channel_adapter.py` — V1 BitBrowser 具体适配器 + mock fallback +
  可注入 driver 缝。
- `app/services/channel_delivery_service.py` — 投递业务 (限频门 / 重试 / 状态机推进 / 持久化 / poll 入站去重)。
- `app/services/channel_rate_limiter.py` — per-channel 小时桶限频器 (进程级，Redis 升级缝)。
- `app/services/channel_config_service.py` — channel_config CRUD (list/get/create/update/soft-delete)。
- `app/db/models/channel_config.py` + `alembic/versions/024_channel_config.py` — 渠道配置表。
- `app/routers/channels.py` — 替换 P5MSG-01 4001 骨架，实现 CRUD + deliver + poll。
- `tests/test_channel_delivery.py` — 33 用例。
- `tests/test_message_skeleton.py` — 更新 2 条随 P5MSG-03 落地的过期断言。

## 10. 备注 / 已知限制

- BitBrowser SDK 真实可用性仍是 Phase 1 已知 blocker；本卡 V1 走文档化的 mock fallback
  (send 成功 + provider id `mock_*`)，real-mode DOM 驱动留可注入 seam，未在本卡实现。
- 限频器为进程内存实现 (无 Redis 依赖)，Redis-backed 是 Phase 5/6 升级缝，仅此处需改。
- `platform_code` 为软引用 (非硬 FK)，避免 delivery 配置耦合 Phase-1 Platform 注册表。
- 共享非 git 目录：本卡与 P5MSG-01/02/04/05 并发改 `app/routers|schemas/messages.py`、
  `app/main.py`。本卡合并 (非覆盖) P5MSG-01/02 已落地形态，并修复了 4 条崩溃遗留的
  过期测试期望 (domain-validation / 两条 delivery mock 读法 / 迁移 head 断言) + 1 条
  E2E skip 根因 (probe 把 SQLAlchemy `+asyncpg` DSN 喂给 asyncpg 驱动 → 永远 skip，
  已改为裸 `postgresql://` 使 live E2E 真正执行)。
