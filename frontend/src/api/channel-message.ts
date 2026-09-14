/**
 * P5MSG-06 — 渠道消息 / 实时通道 API 客户端
 *
 * REST 契约 (envelope {code,message,data} 由 client.ts 拦截器解包):
 *  - GET  /messages?conversation_id=&channel=&direction=&status=&page=&page_size=
 *  - POST /messages/send
 *  - GET  /messages/{id}
 *  - GET  /messages/{id}/receipt
 *  - POST /messages/{id}/status
 *  - GET  /realtime/conversations | /unread | /resync
 *  - POST /realtime/read | /publish
 *
 * SSE 流 (GET /realtime, text/event-stream) 不走 axios — 见
 * @/composables/useRealtimeStream (EventSource + since 断线重连补发)。
 */
import { api } from './client'
import apiClient from './client'
import type {
  ChannelMessage,
  ChannelMessageListParams,
  ChannelMessageListResponse,
  MessageReceiptResponse,
  MessageSendRequest,
  MessageSendResult,
  MessageStatusUpdateRequest,
  RealtimeConversationListResponse,
  RealtimePublishResult,
  RealtimeReadResult,
  RealtimeResyncResponse,
  RealtimeUnreadSummary,
} from './channel-message-types'

/**
 * P5MSG-FIX P0-2: 写原语 (messages/{id}/status, realtime/read, realtime/publish)
 * 受信任生产者鉴权。前后端共用同一 Bearer token (后端 REALTIME_PUBLISH_TOKENS,
 * 前端 VITE_REALTIME_PUBLISH_TOKEN)。返回带 Authorization 的 axios config;
 * 未配置 token 时返回 undefined (调用仍会发出, 由后端 401/403, UI 有错误横幅)。
 */
function producerAuth(): import('axios').AxiosRequestConfig | undefined {
  const token = import.meta.env.VITE_REALTIME_PUBLISH_TOKEN as
    | string
    | undefined
  return token ? { headers: { Authorization: `Bearer ${token}` } } : undefined
}

export const channelMessageApi = {
  // ---- 渠道消息 (P5MSG-02) ----

  /** 分页 + channel/direction/status 过滤 */
  list(params?: ChannelMessageListParams): Promise<ChannelMessageListResponse> {
    return api.get<ChannelMessageListResponse>('/messages', { params })
  },

  detail(messageId: string): Promise<ChannelMessage> {
    return api.get<ChannelMessage>(`/messages/${messageId}`)
  },

  /** 入队出站消息 (status=queued; 实际渠道投递是 P5MSG-03) */
  send(data: MessageSendRequest): Promise<MessageSendResult> {
    return api.post<MessageSendResult>('/messages/send', data)
  },

  /** 投递/已读回执审计轨迹 */
  receipt(messageId: string): Promise<MessageReceiptResponse> {
    return api.get<MessageReceiptResponse>(`/messages/${messageId}/receipt`)
  },

  /** 推进投递状态机 (非法转换 → 4003 业务码; 端点受信任生产者鉴权 P0-2) */
  async updateStatus(
    messageId: string,
    data: MessageStatusUpdateRequest,
  ): Promise<ChannelMessage> {
    const res = await apiClient.post<ChannelMessage>(
      `/messages/${messageId}/status`,
      data,
      producerAuth(),
    )
    return res.data
  },

  // ---- 会话管理读端点 (P5MSG-04; P5MSG-FIX-2 P1-3: customer 归属强校验 + 受信任生产者鉴权) ----

  /**
   * 活跃会话列表 + 最后消息预览 + 未读数。
   *
   * P5MSG-FIX-2 (P1-3): 预览携带客户消息文本 (PII), 后端已收口为
   * customer 归属强校验 — customer_id 必填 (缺省 422 / 未知 404),
   * 且需受信任生产者 Bearer (P0-2, producerAuth(); 未配置 token → 401)。
   */
  async realtimeConversations(params: {
    customer_id: string
    channel?: string
    page?: number
    page_size?: number
  }): Promise<RealtimeConversationListResponse> {
    const res = await apiClient.get<RealtimeConversationListResponse>(
      '/realtime/conversations',
      { params, headers: producerAuth()?.headers },
    )
    return res.data
  },

  /** 未读聚合 (P1-3: 同样 customer_id 必填 + 受信任生产者鉴权) */
  async realtimeUnread(customerId: string): Promise<RealtimeUnreadSummary> {
    const res = await apiClient.get<RealtimeUnreadSummary>('/realtime/unread', {
      params: { customer_id: customerId },
      headers: producerAuth()?.headers,
    })
    return res.data
  },

  /** 一次性 JSON 补发 (gap-fill; 替代长时间 SSE 订阅的场景) */
  realtimeResync(params: {
    since?: number
    conversation_id?: string
    limit?: number
  }): Promise<RealtimeResyncResponse> {
    return api.get<RealtimeResyncResponse>('/realtime/resync', { params })
  },

  /**
   * 标记会话已读 (驱动 P5MSG-02 read 回执 + channel_message.read 事件)。
   *
   * P5MSG-FIX P0-2: 受信任生产者鉴权 (Bearer, producerAuth()); 未配置 token
   * 时后端返回 401, 抛出的 axios Error 由 UI 展示为错误横幅。
   * 响应是裸模型 (非 {code,message,data} 信封), 故走 apiClient 原样透传。
   */
  async markRead(
    conversationId: string,
    messageIds?: string[],
  ): Promise<RealtimeReadResult> {
    const res = await apiClient.post<RealtimeReadResult>(
      '/realtime/read',
      {
        conversation_id: conversationId,
        message_ids: messageIds ?? null,
      },
      producerAuth(),
    )
    return res.data
  },

  /**
   * 临时事件发布 (P5MSG-02/03 生产者 API seam)。
   * 同样受信任生产者鉴权 (P0-2); 裸模型响应走 apiClient。
   */
  async publish(data: {
    kind: string
    conversation_id?: string | null
    payload?: Record<string, unknown>
    dedup_id?: string | null
  }): Promise<RealtimePublishResult> {
    const res = await apiClient.post<RealtimePublishResult>(
      '/realtime/publish',
      data,
      producerAuth(),
    )
    return res.data
  },
}

export default channelMessageApi
