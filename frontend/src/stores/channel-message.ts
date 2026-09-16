/**
 * P5MSG-06 — 渠道消息 / 会话共享状态 (Pinia)
 *
 * 分工 (遵循项目状态管理约定: 共享业务状态放 store, 局部 UI 状态放组件):
 *  - 会话列表 (active + preview + unread) 与 消息流 的跨页面共享状态
 *  - REST 读写 + 实时事件落地 (applyRealtimeEvent) 统一收口
 *
 * SSE 连接本身在组件生命周期内由 @/composables/useRealtimeStream 持有,
 * 事件通过 store 的 applyRealtimeEvent / 相关 action 落地 — 组件卸载即断开。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { channelMessageApi } from '@/api/channel-message'
import { conversationApi } from '@/api/conversation'
import type {
  ChannelMessage,
  MessageDirection,
  MessageSendRequest,
  MessageStatus,
  RealtimeConversationItem,
  RealtimeEvent,
} from '@/api/channel-message-types'
import type { Conversation } from '@/api/conversation-types'

export interface MessageFilters {
  conversation_id: string
  direction?: MessageDirection
  channel?: string
}

export const useChannelMessageStore = defineStore('channel-message', () => {
  // ============ 会话列表 (/realtime/conversations) ============
  const conversations = ref<RealtimeConversationItem[]>([])
  const totalUnread = ref(0)
  const convLoading = ref(false)
  const convError = ref<string | null>(null)

  // ============ 当前会话详情 ============
  const currentConversation = ref<Conversation | null>(null)
  const convDetailLoading = ref(false)
  const convDetailError = ref<string | null>(null)

  // ============ 消息流 (GET /messages?conversation_id=…) ============
  const messages = ref<ChannelMessage[]>([])
  const messagesTotal = ref(0)
  const messagesPage = ref(1)
  const pageSize = ref(20)
  const messagesLoading = ref(false)
  const messagesError = ref<string | null>(null)
  const filters = ref<MessageFilters>({ conversation_id: '' })

  // ============ 发送 ============
  const sending = ref(false)
  const sendError = ref<string | null>(null)

  const hasMoreMessages = computed(
    () => messages.value.length < messagesTotal.value,
  )

  function messageIndex(id: string): number {
    return messages.value.findIndex((m) => m.id === id)
  }

  // ============ actions: 会话列表 ============

  /**
   * 拉取某客户的活跃会话列表 (预览 + 未读)。
   *
   * P5MSG-FIX-2 (P1-3): 后端预览携带客户消息文本 (PII), 已收口为
   * customer 归属强校验 — customer_id 必填 (缺省 422 / 未知 404),
   * 且需受信任生产者 Bearer (P0-2; 未配置 VITE_REALTIME_PUBLISH_TOKEN
   * 时 401, UI 错误横幅提示)。
   */
  async function fetchConversationList(
    customerId: string,
    channel?: string,
  ): Promise<void> {
    convLoading.value = true
    convError.value = null
    try {
      const data = await channelMessageApi.realtimeConversations({
        customer_id: customerId,
        channel: channel || undefined,
        page: 1,
        page_size: 50,
      })
      conversations.value = data.items
      totalUnread.value = data.total_unread
    } catch (error) {
      convError.value = (error as Error).message
      throw error
    } finally {
      convLoading.value = false
    }
  }

  /** 轻量刷新某客户的未读总数 (不替换列表, 保持用户滚动位置; P1-3 customer 必填) */
  async function refreshUnread(customerId: string): Promise<void> {
    try {
      const data = await channelMessageApi.realtimeUnread(customerId)
      totalUnread.value = data.total_unread
      // 就地更新每个会话的未读角标
      for (const item of data.by_conversation) {
        const idx = conversations.value.findIndex(
          (c) => c.conversation_id === item.conversation_id,
        )
        if (idx !== -1) {
          const cur = conversations.value[idx]
          if (cur) cur.unread_count = item.unread_count
        }
      }
    } catch {
      // 未读刷新失败不阻断主流程 — 列表事件 (channel_message.read) 兜底
    }
  }

  // ============ actions: 会话详情 ============

  async function fetchConversation(id: string): Promise<Conversation> {
    convDetailLoading.value = true
    convDetailError.value = null
    try {
      currentConversation.value = await conversationApi.detail(id)
      return currentConversation.value
    } catch (error) {
      convDetailError.value = (error as Error).message
      throw error
    } finally {
      convDetailLoading.value = false
    }
  }

  // ============ actions: 消息流 ============

  /**
   * 加载一页消息 (后端按 created_at 倒序 → page 1 最新)。
   * @param appendMode true = 向已有列表末尾追加更早的消息 (上滚分页)。
   */
  async function fetchMessages(
    conversationId: string,
    opts?: { direction?: MessageDirection; channel?: string; page?: number },
  ): Promise<void> {
    const page = opts?.page ?? 1
    filters.value = {
      conversation_id: conversationId,
      direction: opts?.direction,
      channel: opts?.channel,
    }
    messagesLoading.value = true
    messagesError.value = null
    try {
      const data = await channelMessageApi.list({
        conversation_id: conversationId,
        direction: opts?.direction,
        channel: opts?.channel,
        page,
        page_size: pageSize.value,
      })
      if (page === 1) {
        // 重置 (保留尚未落库的乐观消息)
        const optimistic = messages.value.filter((m) => m.id.startsWith('tmp-'))
        messages.value = [...optimistic, ...data.items]
      } else {
        // 倒序列表: page 2 比 page 1 更旧 → 追加到末尾
        messages.value = [...messages.value, ...data.items]
      }
      messagesTotal.value = data.total
      messagesPage.value = data.page
    } catch (error) {
      messagesError.value = (error as Error).message
      throw error
    } finally {
      messagesLoading.value = false
    }
  }

  /** 上滚加载更早一页 (page 递增, 因为第 1 页是最新) */
  async function loadOlderMessages(): Promise<void> {
    if (!filters.value.conversation_id || messagesLoading.value) return
    await fetchMessages(filters.value.conversation_id, {
      ...filters,
      page: messagesPage.value + 1,
    })
  }

  /** 标记会话已读 (驱动 P5MSG-02 read 回执 + 实时清角标) */
  async function markConversationRead(conversationId: string): Promise<void> {
    const result = await channelMessageApi.markRead(conversationId)
    const idx = conversations.value.findIndex(
      (c) => c.conversation_id === conversationId,
    )
    if (idx !== -1) {
      totalUnread.value = Math.max(0, totalUnread.value - result.marked_read)
      const row = conversations.value[idx]
      if (row) row.unread_count = 0
    }
  }

  // ============ actions: 发送 ============

  /**
   * 发送出站消息 (入队 queued)。
   * 乐观插入一条 tmp- 占位气泡 (方向 out / 状态 queued),
   * 实时事件 (created) 到达后若带真实 id 则合并; 否则保留占位直到刷新。
   */
  async function sendMessage(request: MessageSendRequest): Promise<string> {
    sending.value = true
    sendError.value = null
    const conversationId = request.conversation_id
    let realId = ''
    try {
      const result = await channelMessageApi.send(request)
      realId = result.id
      // 乐观气泡: 若当前会话已加载且 filters 命中, 直接插到顶部
      if (
        filters.value.conversation_id === conversationId &&
        (!filters.value.direction || filters.value.direction === 'out')
      ) {
        const optimistic: ChannelMessage = {
          id: `tmp-${result.id}`,
          conversation_id: conversationId,
          channel: request.channel,
          direction: 'out',
          status: 'queued',
          content: request.content ?? {},
          provider_message_id: request.provider_message_id ?? null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          is_deleted: false,
        }
        messages.value.unshift(optimistic)
        messagesTotal.value += 1
      }
      return realId
    } catch (error) {
      sendError.value = (error as Error).message
      throw error
    } finally {
      sending.value = false
    }
  }

  // ============ 实时事件落地 ============

  /**
   * 将一条去重后的实时事件合入本地状态。
   * payload 仅含 ids/status/channel (无正文) — 需要正文时走 REST refetch。
   *
   * @returns 是否需要视图层重新拉取数据 (created/gap 场景)
   */
  function applyRealtimeEvent(ev: RealtimeEvent): 'refetch' | 'status' | 'none' {
    const convId = ev.conversation_id ?? ''
    const payload = ev.payload ?? {}

    switch (ev.kind) {
      case 'channel_message.created': {
        // 新消息: 列表预览/未读变化 → 刷新; 当前会话消息流 → 重拉最新页
        if (convId === filters.value.conversation_id) return 'refetch'
        return 'refetch' // 列表页统一由 fetchConversationList 兜底 (轻量)
      }
      case 'channel_message.status': {
        const msgId = String(payload.message_id ?? payload.id ?? '')
        const status = payload.status as MessageStatus | undefined
        if (msgId && status) {
          const idx = messageIndex(msgId)
          const existing = idx !== -1 ? messages.value[idx] : undefined
          if (existing) {
            messages.value[idx] = {
              ...existing,
              status,
              provider_message_id:
                (payload.provider_message_id as string | undefined) ??
                existing.provider_message_id,
              error:
                (payload.error as Record<string, unknown> | undefined) ??
                existing.error,
            }
            // 替换掉同真实 id 的乐观占位
            const tmpIdx = messageIndex(`tmp-${msgId}`)
            if (tmpIdx !== -1 && idx !== tmpIdx) {
              messages.value.splice(tmpIdx, 1)
            }
          }
        }
        return 'status'
      }
      case 'channel_message.read': {
        const idx = conversations.value.findIndex(
          (c) => c.conversation_id === convId,
        )
        if (idx !== -1) {
          const row = conversations.value[idx]
          if (row) row.unread_count = 0
          totalUnread.value = Math.max(0, totalUnread.value - 1)
        }
        return 'none'
      }
      case 'conversation.updated':
      default:
        return 'refetch'
    }
  }

  return {
    // 会话列表
    conversations,
    totalUnread,
    convLoading,
    convError,
    // 详情
    currentConversation,
    convDetailLoading,
    convDetailError,
    // 消息流
    messages,
    messagesTotal,
    messagesPage,
    messagesLoading,
    messagesError,
    filters,
    hasMoreMessages,
    // 发送
    sending,
    sendError,
    // actions
    fetchConversationList,
    refreshUnread,
    fetchConversation,
    fetchMessages,
    loadOlderMessages,
    markConversationRead,
    sendMessage,
    applyRealtimeEvent,
  }
})
