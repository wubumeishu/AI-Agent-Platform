# P5MSG-04 — 实时消息推送与会话管理集成 · API 说明

任务: **P5MSG-04** (t_c60e3d54) · Roadmap Phase 2 Message/Conversation 增量
卡片池: P5MSG batch (t_6b5b88e5) · Owner: backend-engineer · 2026-09-14

本卡建立**实时通道 + 会话管理**: SSE 实时推送(新消息/已读回执/投递状态变更)
+ 活跃会话列表(最后消息预览、未读数) + 断线重连/离线队列/补发(去重) +
与 P5MSG-02 消息事件源集成。**不含**前端推送 UI (P5MSG-05/06)、
Phase 4 Workflow 触发的实时事件(未来池范围)。

---

## 1. 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 传输 | **SSE**(非 WebSocket) | 与 Phase 1 SSE 风格一致(卡片要求);单向推送够用;HTTP 天然带 keep-alive/重连 |
| 部署 | 进程内 hub(单 event-loop) | 与 `app.events.domain_events` 一致的 V1 in-process 约定;表面很小,日后换 Redis pub/sub 不动发布方 |
| 补发/去重 | 有界**回放日志**(replay log) + 每事件单调 `seq` | 回放日志即"离线队列";`seq` 即去重游标——已消费事件(`seq<=since`)不再重发,离线期间事件仍在日志中 → 不丢不重 |
| 背压 | 有界 live 队列 + `behind` 标记 | 慢客户端溢出时标记 behind 停推,**不阻塞 emitter**;客户端靠 since-resync 权威恢复 → 有背压仍不丢消息 |
| 会话管理 | 读端点走 `RealtimeConversationService`,数据源 = P5MSG-01/02 的 `messages`(`ChannelMessage`)投递记录 | 活跃列表/预览/未读反映**真实渠道活动**,不是 AI 聊天稿 |
| 事件源集成 | 直接发布 seam + 共享 bus 桥(双路径) | 主路径 = P5MSG-02/03 直接调 `publish_realtime_event`(解耦、稳定契约);冗余 = bus 桥(沿用 `register_*_subscriber` 桥接模式,发布方无需感知 hub) |

## 2. 事件词汇(SSE `kind`)

客户端据此 switch;payload 只带 id/status/channel,**不带消息正文、PII、凭据**(ARCHITECTURE #16)。

| kind | 触发 |
|------|------|
| `channel_message.created` | 新渠道消息入队/送达 |
| `channel_message.status` | 投递状态变更(queued→sent→delivered→read / failed) |
| `channel_message.read` | 已读回执 |
| `conversation.updated` | 会话活跃态变更 |

## 3. 端点(均挂 `/api/v1/realtime`,见 `app/routers/realtime.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/realtime` | **SSE 流**:hello → replay(`seq>since`,离线补发)→ 实时 message;每 ~15s 一条 keep-alive 注释 |
| GET | `/api/v1/realtime/conversations` | 活跃会话列表 + 最后消息预览 + 未读数 + 分页/过滤 |
| GET | `/api/v1/realtime/unread` | 未读聚合(可选按 customer 收敛) |
| GET | `/api/v1/realtime/resync` | 回放日志 JSON 尾(按 `since` 游标补发;`gap` 提示需全量 REST 重同步) |
| POST | `/api/v1/realtime/read` | 将会话标读:驱动 P5MSG-02 `read` 回执 + 发 `channel_message.read` 事件(未读角标实时清零) |
| POST | `/api/v1/realtime/publish` | 事件直发 seam(已知 kind 校验,202;重复 dedup 丢弃) |

### SSE 帧格式(与 Phase 1 SSE 一致)
```
event: hello
data: {"type":"hello","head_seq":N,"oldest_seq":M,"gap":bool,"since":S,"conversation_id":...}

event: replay        # 每条一个 RealtimeEvent (seq>since)
data: {"type":"event","seq":K,"kind":"...","conversation_id":"...","ts":...,"payload":{...}}

event: message       # 实时事件
data: {...}

: keep-alive         # 空闲保活注释
```

### 断线重连 / 离线 / 去重语义
- 客户端记住已处理的最高 `seq`,重连时以 `since` 传入 → 流先 replay `seq>since`
  的离线事件再续接实时;
- 每事件带稳定 `seq` → 客户端按 `seq` 去重(已消费的 `seq<=since` 永不重发);
- 若 `since` 早于保留窗口(`oldest_seq`),`hello.gap=true`,客户端需回退 REST
  全量重同步(`/conversations` 或 `/messages`);实时投递仍继续。

## 4. 响应信封
沿用 PHASE1-API-SPEC `{code, message, data}`。
- `publish` 成功 202 `{code:0, message:"accepted", data:{emitted_seq}}`;
  重复 202 `{message:"duplicate_dropped", data:{emitted_seq:null}}`;
  未知 kind 422 + `code:4002`。
- `read` / `resync` / `conversations` / `unread` 走 `_ok` 成功信封或标准 4xx。

## 5. 代码布局(API → Service → Data)
- `app/services/realtime_hub.py` — 传输层:fan-out + 有界回放日志 + 去重 + 背压(进程单例 `get_realtime_hub()`)。
- `app/services/realtime_events.py` — 事件词汇 + `publish_realtime_event` 直发 seam + `register_realtime_bus_bridge`(共享 bus 桥)。
- `app/services/realtime_conversation_service.py` — 会话管理读端点(活跃列表/预览/未读)。
- `app/schemas/realtime.py` — Pydantic 请求/响应模型。
- `app/routers/realtime.py` — SSE 流 + REST 端点。
- `app/main.py` — 挂载 `/api/v1` + 注册 bus 桥 + `/realtime` 加入 SSE autoflush 跳过集。

> 均为**新增文件**;对 `app/main.py` 仅做**加法**(import + `include_router`
> + 一段 try/except bus 桥注册 + SSE 路径标记),未改既有路由逻辑。

## 6. 测试(Definition of Done:pytest + 并发测试)
- `tests/test_realtime_hub.py`(离线,无 DB)— 19 用例:emit/seq/回放/游标补发/
  去重/溢出背压(replay 仍恢复全部 → 不丢)/重连/并发会话(8 会话×25 事件无串扰无丢失 +
  离线 resync 全恢复)/发布 seam/bus 桥幂等。
- `tests/test_realtime_api.py`(真实测试库,`skipif` DB 不可达)— 10 用例:
  活跃列表预览+未读、未读聚合、closed 会话排除、标读驱动 P5MSG-02 回执并清零未读、
  publish/resync 游标去重、SSE 帧直驱验证(hello+replay)。
- 验收:推送延迟 `<1s`(本机)— `test_emit_latency_under_1s` + 本地流实测;
  断线重连补发不丢 — 并发/重连用例;并发会话 — `TestConcurrentConversations`。

## 7. 与 P5MSG-02 事件源集成
- P5MSG-02 `app/routers/messages.py`(send/status/receipt)目前**尚未**在其 commit 后
  直接发 `channel_message.*` 事件;本卡提供两条即插即用的集成路径:
  1. **直接 seam**:P5MSG-02/03 在 `MessageService` 相关 commit 后调
     `publish_realtime_event("channel_message.status", conv, {status, message_id}, dedup_id=...)`;
  2. **bus 桥**:P5MSG-02/03 向共享 bus 发 `channel_message.*` 事件,
     `register_realtime_bus_bridge()`(已在 `main.py` 注册)自动转发到 hub。
- 本卡自带 `POST /realtime/publish` + `POST /realtime/read` 两个自测/触发入口,
  可在 P5MSG-02 侧完全落地前独立验证整条实时链路(已在本卡测试中覆盖)。

## 8. 协作 / 冲突说明
本仓 backend 为**非 git 共享目录**,P5MSG-01/02/03/04/05 并行读写。
- P5MSG-04 全部代码为**新增文件**,对共享 `app/main.py` 仅做**加法**编辑,
  未触碰 P5MSG-01/02/03 的既有行。
- 事件词汇 `channel_message.*` 属 P5MSG-04 局部定义(未改共享
  `app/events/domain_events.py`),避免与 P5MSG-02 命名冲突;若 P5MSG-02
  后续引入自有事件名,在 `realtime_events.py` 对齐即可。
- 冲突热点(`app/main.py` 被 P5MSG-02/05 并发编辑)已按协议在卡片注释标注
  `hotspot: app/main.py`。
