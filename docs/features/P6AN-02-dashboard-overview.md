# P6AN-02 — Dashboard 概览 API（Agent / 对话 / 转化 / 活跃度 核心指标）

## 目标
聚合 Agent / 对话 / 转化 / 活跃度核心指标，供前端 Dashboard（P6AN-10）与外部系统消费。
单端点、统一 schema、5 分钟响应缓存、P95 < 500ms @ 10k 消息量。

## 端点
```
GET /api/v1/analytics/dashboard/overview
```

### 查询参数
| 参数 | 类型 | 说明 |
|---|---|---|
| `time_range_start` | ISO 8601 | 窗口起点（含），naive 视为 UTC。与 end 同时给出时优先生效 |
| `time_range_end` | ISO 8601 | 窗口终点（不含） |
| `days` | int (1–365) | 无显式 range 时回看 N 天，默认 30，clamp 到 1..365 |
| `agent_id` | UUID | **Agent 维度过滤**：对话/线索按该 agent 名下客户限定，渠道消息按 `messages.agent_id` 限定 |
| `channel` | string | 限定对话 + 渠道消息统计到单一渠道（web/wechat/douyin/…） |

窗口校验：`start < end` 必须成立，否则 400。`days` 越界 422。

### 响应 schema（统一、扁平）
```
{
  "range":        { start, end, days },
  "agents":       { total, active },
  "conversations":{ new, active, total_messages, avg_messages_per_new_conversation },
  "messages":     { total, sent, delivered, failed, success_rate },
  "conversion":   { new_leads, total_leads, closed_leads, conversion_rate },
  "by_agent":     [ { agent_id, agent_name, conversations, messages, message_success_rate } ],
  "computed_at": <ts>,
  "cached": false,
  "cache_ttl_seconds": 300
}
```
所有比率字段在分母为 0 时为 `null`（不产出 `Infinity`/`NaN`）。`by_agent` 默认按
渠道消息量 top-10；设 `agent_id` 时收敛为单条。

## 数据源（Phase 1–5 既有表，零新表）
| 指标 | 表 | 口径 |
|---|---|---|
| Agent 活跃度 | `agent` | live 计数 + `status='active'` |
| 对话数 / 消息数 | `conversation` / `messages` | 窗口内 `created_at`；agent 经 `agent_customer_binding` 半连接 |
| 消息成功率 | `messages` | `delivered+read` / (`delivered+read`+`failed`)，仅统计已完成消息 |
| 转化率（线索→成交） | `lead` | **P6AN-05 单一事实源**：`lead.status='converted'`（终态），非 stage_code |

> 转化口径与 `GET /api/v1/analytics/leads/conversion`（P6AN-05）严格一致：
> 成交 = `Lead.status == "converted"`（CRM lead 状态机终态），本端点不耦合
> `lifecycle_stage_code`，保证两处数字可对拍。

## Agent 归属模型
Agent 通过两条硬引用拥有业务：
- `messages.agent_id`（渠道消息投递日志）
- `agent_customer_binding`（客户责任关系）
对话与线索在设 `agent_id` 时经其名下客户限定；无 agent 归属的客户不计入该
agent 指标。

## 缓存策略
- 位置：`app/services/dashboard_cache.py`（响应级，key = 归一化参数 sha1 前缀）。
- 后端选择：`DASHBOARD_CACHE_URL` / `REDIS_URL` 为 redis 时走 async Redis；否则
  进程内内存 TTL 缓存（平台栈列 Redis，但 pyproject 未声明依赖，同
  `channel_rate_limiter` 的先例——Redis 后端惰性解析，缺失即降级，绝不阻断读路径）。
- TTL 300s；`cached` 由服务端在返回时盖章（非存储），命中不返回"声称 live"的 payload。
- 任何缓存层异常降级为重新计算并记一条 warning。

## 性能验收（P95 < 500ms @ 10k 消息）
离线单测不连库；P95 需在 QA 会话对 scratch 库实测。复现脚本：
`backend/_p6an02_e2e_perf.py`（10k 渠道消息 + 1k 对话 + agent/lead 种子，
跑 N 次取 P95，命中缓存后应 ≈ 0 SQL）。本机 `REDIS_URL` 未配置时走内存缓存，
命中后 P95 主要由序列化 + HTTP 开销决定，远低于 500ms 目标。

## 测试
`tests/test_analytics_p6an02.py`（37 用例，离线可跑）：
- 窗口解析（默认/explicit/单向/naive/逆序/相等）
- 缓存 key 隔离、内存 TTL、Redis 降级、URL 脱敏
- 服务层 SQL 构造（agent binding 子查询、P6AN-05 status 口径、成功率分母、top-N）
- API 层（统一 schema、过滤透传、400/422、缓存命中 0 SQL、多 filter 独立条目）

## 变更记录
| 日期 | 变更 | 任务 |
|---|---|---|
| 2026-09-15 | Dashboard 概览 API 落地（service+router+cache+schema+tests+docs） | t_8c512f23 |
