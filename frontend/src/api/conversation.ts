import { api } from './client'
import type {
  Conversation,
  CreateConversationRequest,
  UpdateConversationRequest,
  ConversationListParams,
  ConversationListResponse,
  ConversationStats,
  Message,
  CreateMessageRequest,
  UpdateMessageRequest,
  MessageListParams,
  MessageListResponse,
  MessageRole,
  RedoResponse,
} from './conversation-types'

const BASE = '/conversations'

export const conversationApi = {
  // ---- 会话 CRUD ----
  list(params?: ConversationListParams): Promise<ConversationListResponse> {
    return api.get<ConversationListResponse>(BASE, { params })
  },

  create(data: CreateConversationRequest): Promise<Conversation> {
    return api.post<Conversation>(BASE, data)
  },

  detail(id: string): Promise<Conversation> {
    return api.get<Conversation>(`${BASE}/${id}`)
  },

  update(id: string, data: UpdateConversationRequest): Promise<Conversation> {
    return api.put<Conversation>(`${BASE}/${id}`, data)
  },

  delete(id: string): Promise<void> {
    return api.delete<void>(`${BASE}/${id}`)
  },

  restore(id: string): Promise<Conversation> {
    return api.post<Conversation>(`${BASE}/${id}/restore`)
  },

  stats(id: string): Promise<ConversationStats> {
    return api.get<ConversationStats>(`${BASE}/${id}/stats`)
  },

  // ---- 消息 ----
  listMessages(
    conversationId: string,
    params?: MessageListParams
  ): Promise<MessageListResponse> {
    return api.get<MessageListResponse>(
      `${BASE}/${conversationId}/messages`,
      { params }
    )
  },

  createMessage(
    conversationId: string,
    data: Omit<CreateMessageRequest, 'conversation_id'>
  ): Promise<Message> {
    return api.post<Message>(`${BASE}/${conversationId}/messages`, {
      ...data,
      conversation_id: conversationId,
    })
  },

  updateMessage(
    messageId: string,
    data: UpdateMessageRequest
  ): Promise<Message> {
    return api.put<Message>(`${BASE}/messages/${messageId}`, data)
  },

  deleteMessage(messageId: string): Promise<void> {
    return api.delete<void>(`${BASE}/messages/${messageId}`)
  },

  batchDeleteMessages(
    conversationId: string,
    messageIds: string[]
  ): Promise<{ deleted: number; message_ids: string[] }> {
    return api.delete<{ deleted: number; message_ids: string[] }>(
      `${BASE}/${conversationId}/messages`,
      { data: { message_ids: messageIds } }
    )
  },

  // 重新生成（redo）assistant 消息
  redoMessage(
    conversationId: string,
    messageId: string
  ): Promise<RedoResponse> {
    return api.post<RedoResponse>(
      `${BASE}/${conversationId}/messages/${messageId}/redo`
    )
  },

  // 上下文窗口内的历史消息
  history(
    conversationId: string,
    params?: { limit?: number; include_summary?: boolean }
  ): Promise<Message[]> {
    return api.get<Message[]>(
      `${BASE}/${conversationId}/messages/history`,
      { params }
    )
  },

  // ---- SSE 流式聊天 ----
  /**
   * 发起流式聊天。后端通过 SSE 推送：
   *   data: {"type":"conversation_id","id":...}
   *   data: {"type":"chunk","content":"...","index":0}
   *   data: {"type":"message_saved","id":"...","content":"...","created_at":"..."}
   *   data: {"type":"done"}
   *
   * 调用方通过 AbortController 中断生成。
   * 注意：SSE 走原生 fetch，不经过共享 axios 实例。
   */
  streamChat(
    conversationId: string,
    message: string,
    signal?: AbortSignal,
    onEvent?: (event: StreamEvent) => void
  ): Promise<void> {
    const url = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1'}/${BASE}/${conversationId}/chat/stream?message=${encodeURIComponent(message)}`
    return fetch(url, {
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
      signal,
    })
      .then(async (res) => {
        if (!res.ok || !res.body) {
          throw new Error(`SSE 请求失败：HTTP ${res.status}`)
        }
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const raw = line.slice(5).trim()
            if (!raw) continue
            let event: StreamEvent
            try {
              event = JSON.parse(raw)
            } catch {
              continue
            }
            onEvent?.(event)
          }
        }
      })
      .catch((error: unknown) => {
        if ((error as { name?: string })?.name === 'AbortError') return
        throw error
      })
  },
}

export type {
  Conversation,
  CreateConversationRequest,
  UpdateConversationRequest,
  ConversationListParams,
  ConversationListResponse,
  ConversationStats,
  Message,
  MessageRole,
  CreateMessageRequest,
  UpdateMessageRequest,
  MessageListParams,
  MessageListResponse,
  RedoResponse,
} from './conversation-types'

export interface StreamEvent {
  type:
    | 'conversation_id'
    | 'chunk'
    | 'message_saved'
    | 'done'
    | string
  [key: string]: unknown
}
