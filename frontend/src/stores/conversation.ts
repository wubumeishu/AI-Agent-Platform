import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { conversationApi } from '@/api/conversation'
import type {
  Conversation,
  ConversationListParams,
  CreateConversationRequest,
  UpdateConversationRequest,
  Message,
  MessageListParams,
  UpdateMessageRequest,
  MessageRole,
  ConversationStats,
} from '@/api/conversation'

export const useConversationStore = defineStore('conversation', () => {
  // ---- 会话列表状态 ----
  const conversations = ref<Conversation[]>([])
  const total = ref(0)
  const page = ref(1)
  const loading = ref(false)
  const creating = ref(false)
  const listError = ref<string | null>(null)

  // ---- 当前会话 ----
  const currentConversation = ref<Conversation | null>(null)
  const currentConversationLoading = ref(false)

  // ---- 当前会话的消息 ----
  const messages = ref<Message[]>([])
  const messagesTotal = ref(0)
  const messagesLoading = ref(false)
  const messagesError = ref<string | null>(null)

  // ---- 流式生成状态 ----
  const streaming = ref(false)
  const streamContent = ref('')
  const streamError = ref<string | null>(null)
  /** 等待 SSE 首个 token（用户消息已发送、AI 尚未开始输出） */
  const awaitingFirstChunk = ref(false)

  /** 最近一次流式失败的错误文案与用户消息（供「重试生成」使用） */
  const streamErrorText = ref<string | null>(null)
  const failedUserMessage = ref<string | null>(null)

  let streamAbortController: AbortController | null = null

  // Getters
  const hasConversations = computed(() => conversations.value.length > 0)

  // ============ 会话 ============
  async function fetchConversations(
    params?: ConversationListParams
  ): Promise<{ items: Conversation[]; total: number }> {
    loading.value = true
    listError.value = null
    try {
      const paged = params?.page ?? 1
      const data = await conversationApi.list(params)
      conversations.value = data.items
      total.value = data.total
      page.value = data.page
      return data
    } catch (error) {
      listError.value = (error as Error).message
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchConversation(id: string): Promise<Conversation> {
    currentConversationLoading.value = true
    try {
      const conv = await conversationApi.detail(id)
      currentConversation.value = conv
      return conv
    } finally {
      currentConversationLoading.value = false
    }
  }

  async function createConversation(
    data: CreateConversationRequest
  ): Promise<Conversation> {
    const conv = await conversationApi.create(data)
    conversations.value.unshift(conv)
    total.value += 1
    return conv
  }

  async function updateConversation(
    id: string,
    data: UpdateConversationRequest
  ): Promise<Conversation> {
    const conv = await conversationApi.update(id, data)
    const index = conversations.value.findIndex((c) => c.id === id)
    if (index !== -1) conversations.value[index] = conv
    if (currentConversation.value?.id === id) currentConversation.value = conv
    return conv
  }

  async function deleteConversation(id: string): Promise<void> {
    await conversationApi.delete(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    total.value = Math.max(0, total.value - 1)
    if (currentConversation.value?.id === id) clearCurrentConversation()
  }

  async function restoreConversation(id: string): Promise<Conversation> {
    const conv = await conversationApi.restore(id)
    const index = conversations.value.findIndex((c) => c.id === id)
    if (index !== -1) conversations.value[index] = conv
    else conversations.value.unshift(conv)
    return conv
  }

  async function fetchConversationStats(
    id: string
  ): Promise<ConversationStats | null> {
    try {
      return await conversationApi.stats(id)
    } catch {
      return null
    }
  }

  // ============ 消息 ============
  async function fetchMessages(
    conversationId: string,
    params?: MessageListParams
  ): Promise<{ items: Message[]; total: number }> {
    messagesLoading.value = true
    messagesError.value = null
    try {
      const data = await conversationApi.listMessages(conversationId, params)
      messages.value = data.items
      messagesTotal.value = data.total
      return data
    } catch (error) {
      messagesError.value = (error as Error).message
      throw error
    } finally {
      messagesLoading.value = false
    }
  }

  async function createMessage(
    conversationId: string,
    data: { role: MessageRole; content: string; parent_id?: string }
  ): Promise<Message> {
    const created = await conversationApi.createMessage(conversationId, data)
    messages.value.push(created)
    messagesTotal.value += 1
    return created
  }

  /**
   * 流式过程中实时更新最后一条 assistant 消息（打字机效果 / message_saved 回填）。
   * 若列表尚无 assistant 消息则自动追加一条占位消息。
   */
  function appendStreamChunk(payload: {
    conversationId: string
    content?: string
    id?: string
    created_at?: string
  }): void {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.conversation_id === payload.conversationId) {
      if (payload.content !== undefined) last.content = payload.content
      if (payload.id) last.id = payload.id
      if (payload.created_at) last.created_at = payload.created_at
      return
    }
    messages.value.push({
      id: payload.id ?? `tmp-${Date.now()}`,
      conversation_id: payload.conversationId,
      role: 'assistant',
      content: payload.content ?? '',
      edit_count: 0,
      created_at: payload.created_at ?? new Date().toISOString(),
    })
    if (!payload.id) messagesTotal.value += 1
  }

  async function editMessage(
    messageId: string,
    data: UpdateMessageRequest
  ): Promise<Message> {
    const updated = await conversationApi.updateMessage(messageId, data)
    const index = messages.value.findIndex((m) => m.id === messageId)
    if (index !== -1) messages.value[index] = updated
    return updated
  }

  async function removeMessage(
    conversationId: string,
    messageId: string
  ): Promise<void> {
    await conversationApi.deleteMessage(messageId)
    messages.value = messages.value.filter((m) => m.id !== messageId)
    messagesTotal.value = Math.max(0, messagesTotal.value - 1)
    void conversationId
  }

  // ============ 流式生成 ============
  /**
   * 流式发送用户消息并获取 AI 回复。
   * @param skipUserMessage 重试场景（用户消息已落库）传 true，跳过重复保存。
   */
  async function streamChat(
    conversationId: string,
    userMessage: string,
    options?: { skipUserMessage?: boolean }
  ): Promise<string> {
    abortStream()
    streaming.value = true
    awaitingFirstChunk.value = true
    streamContent.value = ''
    streamError.value = null
    streamErrorText.value = null
    failedUserMessage.value = null
    streamAbortController = new AbortController()

    try {
      // 1) 先保存用户消息（重试场景用户消息已落库，跳过）
      if (!options?.skipUserMessage) {
        await createMessage(conversationId, { role: 'user', content: userMessage })
      }

      // 2) SSE 拉取 AI 回复（chunk 事件实时回填最后一条 assistant 消息，打字机效果）
      await conversationApi.streamChat(
        conversationId,
        userMessage,
        streamAbortController.signal,
        (event) => {
          switch (event.type) {
            case 'chunk': {
              const chunk = String((event as { content?: unknown }).content ?? '')
              streamContent.value += chunk
              awaitingFirstChunk.value = false
              appendStreamChunk({
                conversationId,
                content: streamContent.value,
              })
              break
            }
            case 'message_saved':
              appendStreamChunk({
                conversationId,
                content: String((event as { content?: unknown }).content ?? streamContent.value),
                id: String((event as { id?: unknown }).id ?? ''),
                created_at: String((event as { created_at?: unknown }).created_at ?? ''),
              })
              break
            case 'done':
              awaitingFirstChunk.value = false
              break
          }
        }
      )
      return streamContent.value
    } catch (error) {
      const aborted = (error as Error)?.name === 'AbortError'
      awaitingFirstChunk.value = false
      if (!aborted) {
        streamError.value = (error as Error).message
        streamErrorText.value = (error as Error).message || 'AI 回复生成失败'
        failedUserMessage.value = userMessage
        // 失败时移除未落库且无内容的流式占位消息（tmp- 前缀）；
        // 已有部分内容时保留并标记为中断（UI 侧按 tmp- 前缀渲染「已中断」）
        const idx = messages.value.findIndex(
          (m) =>
            m.id.startsWith('tmp-') &&
            m.conversation_id === conversationId &&
            m.content === ''
        )
        if (idx !== -1) {
          messages.value.splice(idx, 1)
          messagesTotal.value = Math.max(0, messagesTotal.value - 1)
        }
      }
      throw error
    } finally {
      streaming.value = false
      streamAbortController = null
    }
  }

  function abortStream(): void {
    if (streamAbortController) {
      streamAbortController.abort()
      streamAbortController = null
      streaming.value = false
      awaitingFirstChunk.value = false
      // 用户主动中断：保留已有部分内容（UI 渲染「已中断」），移除空占位
      const idx = messages.value.findIndex(
        (m) => m.id.startsWith('tmp-') && m.content === ''
      )
      if (idx !== -1) {
        messages.value.splice(idx, 1)
        messagesTotal.value = Math.max(0, messagesTotal.value - 1)
      }
    }
  }

  /** 失败后重试：对最近一次失败的用户消息重新发起流式生成（跳过用户消息落库） */
  async function retryFailedStream(conversationId: string): Promise<string> {
    const message = failedUserMessage.value
    if (!message) throw new Error('没有可重试的消息')
    streamErrorText.value = null
    failedUserMessage.value = null
    // 清理上一次中断残留的 tmp- 占位消息，避免重复
    const before = messages.value.length
    messages.value = messages.value.filter(
      (m) => !(m.id.startsWith('tmp-') && m.conversation_id === conversationId)
    )
    messagesTotal.value = Math.max(0, messagesTotal.value - (before - messages.value.length))
    return streamChat(conversationId, message, { skipUserMessage: true })
  }

  // ============ 清理 ============
  function clearCurrentConversation(): void {
    currentConversation.value = null
    messages.value = []
    messagesTotal.value = 0
    abortStream()
  }

  function clearLists(): void {
    conversations.value = []
    total.value = 0
  }

  return {
    // 会话列表
    conversations,
    total,
    page,
    loading,
    creating,
    listError,
    // 当前会话
    currentConversation,
    currentConversationLoading,
    // 消息
    messages,
    messagesTotal,
    messagesLoading,
    messagesError,
    // 流式
    streaming,
    awaitingFirstChunk,
    streamContent,
    streamError,
    streamErrorText,
    failedUserMessage,
    // getters
    hasConversations,
    // 会话 actions
    fetchConversations,
    fetchConversation,
    createConversation,
    updateConversation,
    deleteConversation,
    restoreConversation,
    fetchConversationStats,
    // 消息 actions
    fetchMessages,
    createMessage,
    editMessage,
    removeMessage,
    // 流式 actions
    streamChat,
    abortStream,
    retryFailedStream,
    // 清理
    clearCurrentConversation,
    clearLists,
  }
})
