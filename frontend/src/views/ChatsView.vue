<template>
  <div class="chats-view">
    <!-- 左侧会话列表面板（搜索 / 新建 / 删除 / 恢复 / 键盘导航） -->
    <ConversationListPanel
      ref="panelRef"
      :selected-id="selectedId"
      @select="onSelectConversation"
      @fetch="onFetch"
      @new="openCreate"
    />

    <!-- 主区域：当前会话 -->
    <section class="chats-main" aria-label="对话内容">
      <!-- 未选中会话 -->
      <EmptyState
        v-if="!selectedId"
        icon="💬"
        title="选择一个会话"
        description="从左侧列表选择会话，或点击「新建」开始一段对话"
      />

      <template v-else>
        <!-- 头部 -->
        <header class="chats-main__header">
          <div class="chats-main__head-text">
            <h2 class="chats-main__title">
              {{ conversation?.subject || '未命名会话' }}
            </h2>
            <div class="chats-main__sub">
              <span class="chats-main__channel">
                {{ getChannelLabel(conversation?.channel ?? 'web') }}
              </span>
              <span v-if="conversation" class="chats-main__count">
                {{ conversation.message_count }} 条消息
              </span>
            </div>
          </div>
          <div class="chats-main__actions">
            <button
              class="btn btn--ghost btn--sm"
              :disabled="convLoading"
              @click="refresh"
            >
              刷新
            </button>
          </div>
        </header>

        <!-- 会话详情加载 -->
        <div v-if="convLoading" class="chats-main__messages">
          <LoadingState text="加载会话..." />
        </div>
        <div v-else-if="convError" class="chats-main__messages">
          <EmptyState
            icon="⚠️"
            title="会话加载失败"
            :description="convError"
            show-action
            action-text="重试"
            @action="loadConversation(selectedId)"
          />
        </div>

        <!-- 对话界面：消息流 + 错误横幅 + 输入区 -->
        <template v-else>
          <!-- 流式生成失败：错误横幅 + 重试 -->
          <div
            v-if="streamErrorText"
            class="chat-error-banner"
            role="alert"
          >
            <span class="chat-error-banner__icon" aria-hidden="true">⚠️</span>
            <span class="chat-error-banner__text">{{ streamErrorText }}</span>
            <div class="chat-error-banner__actions">
              <button
                class="btn btn--primary btn--sm"
                type="button"
                @click="retryStream"
              >
                重试生成
              </button>
              <button
                class="btn btn--ghost btn--sm"
                type="button"
                @click="dismissStreamError"
              >
                关闭
              </button>
            </div>
          </div>

          <!-- 消息区（打字机 / 加载更多 / 空态 / 加载失败） -->
          <ChatPanel
            ref="chatPanelRef"
            :conversation-id="selectedId"
            @loaded="onMessagesLoaded"
          />

          <!-- 输入区：自动聚焦、Enter 发送、Shift+Enter 换行、生成中可中断 -->
          <footer class="chats-main__composer">
            <ChatComposer
              v-model="draft"
              :streaming="streaming"
              :disabled="false"
              @send="sendMessage"
              @interrupt="interrupt"
            />
          </footer>
        </template>
      </template>
    </section>

    <!-- 新建会话 -->
    <Modal
      v-if="createOpen"
      title="新建会话"
      @close="createOpen = false"
    >
      <ConversationCreateDialog
        :submitting="creating"
        @submit="handleCreate"
        @cancel="createOpen = false"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useConversationStore } from '@/stores/conversation'
import type {
  Conversation,
  ConversationListParams,
} from '@/api/conversation'
import ConversationListPanel from '@/components/conversation/ConversationListPanel.vue'
import ConversationCreateDialog from '@/components/conversation/ConversationCreateDialog.vue'
import ChatPanel from '@/components/conversation/ChatPanel.vue'
import ChatComposer from '@/components/conversation/ChatComposer.vue'
import Modal from '@/components/common/Modal.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingState from '@/components/common/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const store = useConversationStore()
const {
  currentConversation: conversation,
  streaming,
  streamErrorText,
} = storeToRefs(store)

const selectedId = computed(() =>
  typeof route.params.id === 'string' ? route.params.id : ''
)

// ---- 会话详情加载 ----
const convLoading = ref(false)
const convError = ref<string | null>(null)
const chatPanelRef = ref<InstanceType<typeof ChatPanel> | null>(null)

async function loadConversation(id: string) {
  convError.value = null
  convLoading.value = true
  try {
    await store.fetchConversation(id)
    scrollToBottom()
  } catch (error) {
    convError.value = (error as Error).message || '加载会话失败'
  } finally {
    convLoading.value = false
  }
}

watch(
  selectedId,
  (id) => {
    if (id) loadConversation(id)
  },
  { immediate: true }
)

function refresh() {
  const filters = panelRef.value?.readFilters?.()
  if (filters) {
    void store.fetchConversations({
      page: 1,
      page_size: 20,
      ...filters,
    })
  }
  if (selectedId.value) {
    loadConversation(selectedId.value)
    // 同时重载消息面板（定位最新一页），保留进行中的流式生成
    if (!streaming.value) {
      void chatPanelRef.value?.loadInitial()
    }
  }
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chatPanelRef.value?.jumpToBottom()
  })
}

function onMessagesLoaded() {
  // ChatPanel 内部已定位到最新一页并贴底，这里仅在刷新后兜底
  scrollToBottom()
}

// ---- 面板事件 ----
type PanelExpose = { readFilters?: () => { search?: string; status?: string } }
const panelRef = ref<PanelExpose | null>(null)

function onFetch(params: ConversationListParams) {
  store.fetchConversations(params).catch(() => {
    // 面板内部已展示错误轻提示
  })
}

onMounted(() => {
  // 初始加载会话列表（面板默认 filters：active、无搜索）
  onFetch({ page: 1, page_size: 20 })
})

function onSelectConversation(id: string) {
  if (id !== selectedId.value) router.push(`/chats/${id}`)
}

// ---- 消息发送 / 流式生成 ----
const draft = ref('')

async function sendMessage() {
  const content = draft.value.trim()
  if (!content || !selectedId.value || streaming.value) return
  draft.value = ''
  try {
    await store.streamChat(selectedId.value, content)
  } catch {
    // store 已记录 streamErrorText，由错误横幅呈现
  }
}

function interrupt() {
  store.abortStream()
}

function retryStream() {
  if (!selectedId.value) return
  store.retryFailedStream(selectedId.value).catch(() => {
    // 仍失败：streamErrorText 会再次更新，横幅继续显示
  })
}

function dismissStreamError() {
  // 清除横幅文案（store 字段为响应式 ref）
  store.streamErrorText = null
  store.failedUserMessage = null
}

// 切换会话时清空流式错误与草稿
watch(selectedId, (id, prev) => {
  if (id && id !== prev) {
    store.abortStream()
    store.streamErrorText = null
    store.failedUserMessage = null
    draft.value = ''
  }
})

// ---- 新建会话 ----
const createOpen = ref(false)
const creating = ref(false)

function openCreate() {
  createOpen.value = true
}

async function handleCreate(data: {
  subject?: string
  channel: string
  customer_id?: string
}) {
  if (!data.customer_id) {
    // 对话框已内联提示必填，双保险
    return
  }
  creating.value = true
  try {
    const conv = await store.createConversation({
      subject: data.subject,
      channel: data.channel as Conversation['channel'],
      customer_id: data.customer_id,
    })
    createOpen.value = false
    refresh()
    router.push(`/chats/${conv.id}`)
  } catch (error) {
    // 保留对话框由用户修正（错误经 store.listError 由面板轻提示呈现）
    console.error('创建会话失败:', error)
  } finally {
    creating.value = false
  }
}

// ---- 展示辅助 ----
const CHANNEL_LABELS: Record<string, string> = {
  web: '网页',
  email: '邮件',
  phone: '电话',
  wechat: '微信',
  dingtalk: '钉钉',
}

function getChannelLabel(channel: string) {
  return CHANNEL_LABELS[channel] || channel
}
</script>

<style scoped>
.chats-view {
  display: flex;
  gap: var(--spacing-4);
  align-items: stretch;
  height: 100%;
  min-height: 0;
}

.chats-view > :first-child {
  flex-shrink: 0;
}

/* 主区域 */
.chats-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.chats-main__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-3);
  padding: var(--spacing-4);
  border-bottom: 1px solid var(--color-border);
}

.chats-main__head-text {
  min-width: 0;
}

.chats-main__title {
  margin: 0;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chats-main__sub {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: 4px;
}

.chats-main__channel {
  font-size: 10px;
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  padding: 1px 6px;
}

.chats-main__count {
  font-size: 11px;
  color: var(--color-text-muted);
}

.chats-main__actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.chats-main__messages {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 流式错误横幅 */
.chat-error-banner {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-4);
  background: var(--color-warning-light, #FEF3C7);
  border-bottom: 1px solid color-mix(in srgb, var(--color-warning, #F59E0B) 35%, transparent);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.chat-error-banner__icon {
  font-size: 14px;
}

.chat-error-banner__text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-error-banner__actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

/* 输入区 */
.chats-main__composer {
  border-top: 1px solid var(--color-border);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-secondary);
}

/* 未选中会话 / 加载失败时占满主区域居中 */
.chats-main > :first-child:not(.chats-main__header) {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: auto;
}

/* 响应式：<1200px 时面板堆叠在上方（面板自身已有 100% 宽度规则） */
@media (max-width: 1199px) {
  .chats-view {
    flex-direction: column;
    overflow-y: auto;
  }

  .chats-main {
    min-height: 480px;
  }
}
</style>
