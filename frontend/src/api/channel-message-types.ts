/**
 * P5MSG-06 — 渠道消息 / 会话管理 / 实时通道 前端类型定义
 *
 * 与后端契约对齐:
 *  - app/schemas/messages.py    ChannelMessage* / MessageSendRequest / MessageReceipt*
 *  - app/schemas/realtime.py     RealtimeConversation* / RealtimeUnreadSummary
 *  - app/services/realtime_hub.py  SSE frame (RealtimeEvent.to_sse_dict)
 *
 * 注意: 渠道消息 (ChannelMessage, 投递记录) 与 Phase-2 AI 对话消息
 * (Conversation Message, role/content) 是两个概念 — 本模块只消费前者。
 */

// ---------------------------------------------------------------------------
// 值域 (镜像 app/db/models/messages.py 与 app/schemas/messages.py)
// ---------------------------------------------------------------------------

export type MessageStatus = 'queued' | 'sent' | 'delivered' | 'read' | 'failed'
export type MessageDirection = 'in' | 'out'

/** 出站渠道域 — MESSAGE_CHANNELS (P5MSG-01) */
export const MESSAGE_CHANNELS = [
  'wechat',
  'wechat_work',
  'douyin',
  'xiaohongshu',
  'email',
  'sms',
  'whatsapp',
  'line',
  'web',
  'other',
] as const
export type ChannelCode = (typeof MESSAGE_CHANNELS)[number]

export const MESSAGE_STATUSES = ['queued', 'sent', 'delivered', 'read', 'failed'] as const
export const MESSAGE_DIRECTIONS = ['in', 'out'] as const

/** 渠道 code → 中文标签 (仅 UI 展示) */
export const CHANNEL_LABELS: Record<string, string> = {
  wechat: '微信',
  wechat_work: '企业微信',
  douyin: '抖音',
  xiaohongshu: '小红书',
  email: '邮件',
  sms: '短信',
  whatsapp: 'WhatsApp',
  line: 'LINE',
  web: '网页',
  other: '其他',
}

export const STATUS_LABELS: Record<MessageStatus, string> = {
  queued: '排队中',
  sent: '已发送',
  delivered: '已送达',
  read: '已读',
  failed: '发送失败',
}

export const DIRECTION_LABELS: Record<MessageDirection, string> = {
  in: '收件',
  out: '发件',
}

/** P5MSG-04 实时事件类型 (REALTIME_EVENT_KINDS) */
export type RealtimeKind =
  | 'channel_message.created'
  | 'channel_message.status'
  | 'channel_message.read'
  | 'conversation.updated'

// ---------------------------------------------------------------------------
// 渠道消息 (GET /api/v1/messages, POST /send, /{id}, /{id}/status, /{id}/receipt)
// ---------------------------------------------------------------------------

/** 一条渠道消息投递记录 (ChannelMessageResponse) */
export interface ChannelMessage {
  id: string
  conversation_id: string
  account_id?: string | null
  agent_id?: string | null
  channel: string
  direction: MessageDirection
  status: MessageStatus
  /** 结构化载荷 (JSONB): text / media refs / platform fields */
  content: Record<string, unknown>
  provider_message_id?: string | null
  sent_at?: string | null
  received_at?: string | null
  /** status=failed 时的失败详情 */
  error?: Record<string, unknown> | null
  last_receipt_at?: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

export interface ChannelMessageListResponse {
  items: ChannelMessage[]
  total: number
  page: number
  page_size: number
  /** 过滤回显 (客户端可验证查询已生效) */
  conversation_id?: string | null
  channel?: string | null
  direction?: MessageDirection | null
  status?: MessageStatus | null
}

export interface ChannelMessageListParams {
  conversation_id?: string
  channel?: string
  direction?: MessageDirection
  status?: MessageStatus
  page?: number
  page_size?: number
}

/** POST /api/v1/messages/send — 入队 (status 始终 queued) */
export interface MessageSendRequest {
  conversation_id: string
  account_id?: string | null
  agent_id?: string | null
  channel: string
  direction?: MessageDirection
  content: Record<string, unknown>
  provider_message_id?: string | null
}

/** send 成功响应 */
export interface MessageSendResult {
  id: string
  status: MessageStatus
  enqueued: boolean
}

/** POST /api/v1/messages/{id}/status — 推进投递状态机 */
export interface MessageStatusUpdateRequest {
  status: MessageStatus
  error?: Record<string, unknown> | null
  provider_message_id?: string | null
  source?: 'provider' | 'manual'
}

/** 一条回执记录 (messages.receipts 审计轨迹) */
export interface MessageReceipt {
  status: string
  at?: string | null
  source?: string
  error?: Record<string, unknown> | null
  provider_message_id?: string | null
}

/** GET /api/v1/messages/{id}/receipt */
export interface MessageReceiptResponse {
  message_id: string
  status: MessageStatus
  error?: Record<string, unknown> | null
  provider_message_id?: string | null
  sent_at?: string | null
  received_at?: string | null
  last_receipt_at?: string | null
  receipts: MessageReceipt[]
}

// ---------------------------------------------------------------------------
// 会话管理 (P5MSG-04: /api/v1/realtime/conversations | /unread | /resync | /read | /publish)
// ---------------------------------------------------------------------------

/** 活跃会话列表项 (含最后消息预览 + 未读数) */
export interface RealtimeConversationItem {
  conversation_id: string
  customer_id?: string | null
  channel: string
  subject?: string | null
  status: string
  last_message_at?: string | null
  /** 有界文本预览 (后端从 content JSONB 渲染) */
  last_message_preview?: string | null
  unread_count: number
  message_count: number
}

export interface RealtimeConversationListResponse {
  items: RealtimeConversationItem[]
  total_unread: number
  page: number
  page_size: number
}

export interface RealtimeUnreadSummary {
  total_unread: number
  by_conversation: RealtimeConversationItem[]
}

export interface RealtimeResyncResponse {
  since: number
  head_seq: number
  oldest_seq: number
  gap: boolean
  count: number
  events: RealtimeEvent[]
}

/** POST /realtime/read 响应 */
export interface RealtimeReadResult {
  conversation_id: string
  marked_read: number
  marked_message_ids: string[]
  skipped: string[]
  emitted_seq: number | null
}

/** POST /realtime/publish 响应 */
export interface RealtimePublishResult {
  kind: string
  conversation_id?: string | null
  emitted_seq: number | null
}

// ---------------------------------------------------------------------------
// SSE 帧 (GET /api/v1/realtime — text/event-stream)
// ---------------------------------------------------------------------------

/** 事件帧 (replay / message 事件的 data JSON, RealtimeEvent.to_sse_dict) */
export interface RealtimeEvent {
  type: 'event'
  /** 全局单调递增序号 — 断线重连游标 + 去重 */
  seq: number
  kind: RealtimeKind
  conversation_id?: string | null
  ts: number
  /** 仅 ids / status / channel — 不含消息正文、PII、凭据 */
  payload: Record<string, unknown>
}

/** 连接握手帧 */
export interface RealtimeHello {
  type: 'hello'
  head_seq: number
  oldest_seq: number
  /** true = since 早于保留窗口 → 客户端回退 REST 全量重取 */
  gap: boolean
  since: number
  conversation_id?: string | null
}
