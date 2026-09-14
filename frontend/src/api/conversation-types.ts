// ============================================================
// P1-003 会话与消息系统 - 前端类型定义
// 与后端 app/schemas/conversation.py 的 Pydantic 模型一一对应。
// 后端返回的是裸 Pydantic 序列化结果（items/total/page/page_size），
// 不包裹 {code,message,data} 信封 —— 注意共享 api 客户端的拦截器
// 假设了 code===0 信封（见 client.ts 注释与 Kanban 任务 handoff）。
// ============================================================

export type ConversationStatus = 'active' | 'closed' | 'archived' | 'deleted'
export type ConversationChannel = 'web' | 'email' | 'phone' | 'wechat' | 'dingtalk'
export type ConversationSentiment = 'positive' | 'neutral' | 'negative'

export interface Conversation {
  id: string
  customer_id: string
  channel: ConversationChannel
  subject?: string | null
  status: ConversationStatus
  summary?: string | null
  sentiment?: ConversationSentiment | null
  tags: string[]
  metadata?: Record<string, unknown> | null
  duration_seconds?: number | null
  message_count: number
  last_message_at?: string | null
  created_at: string
  updated_at: string
}

export interface CreateConversationRequest {
  customer_id: string
  channel?: ConversationChannel
  subject?: string
  status?: ConversationStatus
  summary?: string
  sentiment?: ConversationSentiment
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface UpdateConversationRequest {
  subject?: string
  status?: ConversationStatus
  summary?: string
  sentiment?: ConversationSentiment
  duration_seconds?: number
  tags?: string[]
  metadata?: Record<string, unknown>
}

export interface ConversationListParams {
  customer_id?: string
  status?: ConversationStatus | string
  channel?: ConversationChannel | string
  search?: string
  sort?: 'created_at' | 'last_message_at'
  order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export interface ConversationListResponse {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

export interface ConversationStats {
  conversation_id: string
  total_messages: number
  user_messages: number
  assistant_messages: number
  system_messages: number
  first_message_at?: string | null
  last_message_at?: string | null
  avg_response_time_seconds?: number | null
}

// ---- 消息 ----

export type MessageRole = 'user' | 'assistant' | 'system'

export interface Message {
  id: string
  conversation_id: string
  role: MessageRole
  content: string
  parent_id?: string | null
  metadata?: Record<string, unknown> | null
  edit_count: number
  created_at: string
  updated_at?: string | null
}

export interface CreateMessageRequest {
  conversation_id: string
  role: MessageRole
  content: string
  parent_id?: string
  metadata?: Record<string, unknown>
}

export interface UpdateMessageRequest {
  content?: string
  metadata?: Record<string, unknown>
}

export interface MessageListParams {
  role?: MessageRole | string
  page?: number
  page_size?: number
  start_time?: string
  end_time?: string
}

export interface MessageListResponse {
  items: Message[]
  total: number
  page: number
  page_size: number
}

export interface RedoResponse {
  original_id: string
  new_id: string
  original_role: MessageRole
  new_content: string
  status: string
  created_at: string
}
