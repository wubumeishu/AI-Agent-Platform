<template>
  <div class="convd">
    <!-- 头部 -->
    <header class="convd__header">
      <div class="convd__head-text">
        <h2 class="convd__title">
          {{ conversation?.subject || '会话详情' }}
        </h2>
        <div class="convd__sub">
          <span class="convd__channel">{{ channelLabel }}</span>
          <span v-if="conversation" class="convd__count">
            {{ conversation.message_count }} 条消息
          </span>
          <span
            v-if="unreadOnly > 0"
            class="convd__unread"
          >
            {{ unreadOnly }} 条未读
          </span>
        </div>
      </div>

      <div class="convd__actions">
        <span
          class="convd__rt"
          :class="`convd__rt--${rt.status}`"
          role="status"
        >
          <span class="convd__rt-dot" aria-hidden="true"></span>
          {{ rtLabel }}
        </span>
        <button
          v-if="unreadOnly > 0"
          class="btn btn--ghost btn--sm"
          :disabled="markingRead"
          @click="onMarkRead"
        >
          全部标为已读
        </button>
        <button
          class="btn btn--ghost btn--sm"
          :disabled="messagesLoading"
          @click="onRefresh"
        >
          刷新
        </button>
      </div>
    </header>

    <!-- 会话详情加载 -->
    <LoadingState v-if="convDetailLoading && !conversation" text="加载会话..." />

    <!-- 会话加载错误 -->
    <div v-else-if="convDetailError" class="convd__error" role="alert">
      <p>会话加载失败: {{ convDetailError }}</p>
      <button class="btn btn--primary btn--sm" @click="onLoadConversation">重试</button>
    </div>

    <template v-else>
      <!-- 方向过滤 -->
      <div class="convd__filters">
        <button
          v-for="f in directionFilters"
          :key="f.value"
          class="convd__filter"
          :class="{ 'convd__filter--active': f.value === directionFilter }"
          @click="onDirectionFilter(f.value)"
        >
          {{ f.label }}
        </button>
      </div>

      <!-- 消息流 -->
      <div class="convd__messages" @scroll="onScroll">
        <!-- 分页加载指示器 (上滚加载更早) -->
        <div v-if="hasMoreMessages && olderLoading" class="convd__older">
          正在加载更早消息…
        </div>
        <div v-else-if="hasMoreMessages && messages.length > 0" class="convd__older">
          <button class="btn btn--ghost btn--sm" @click="onLoadOlder">
            加载更早消息
          </button>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-if="!messagesLoading && !messagesError && messages.length === 0"
          icon="✉️"
          title="暂无消息"
          description="发送第一条消息, 或等待渠道适配器投递入站消息"
        />

        <!-- 错误态 -->
        <div v-else-if="messagesError" class="convd__error convd__error--center" role="alert">
          <p>消息加载失败: {{ messagesError }}</p>
          <button class="btn btn--primary btn--sm" @click="onRefresh">重试</button>
        </div>

        <!-- 气泡 (时间正序: 最旧在顶, 最新在底) -->
        <div v-else class="convd__bubbles">
          <ChannelMessageBubble
            v-for="msg in chronologicalMessages"
            :key="msg.id"
            :msg="msg"
          />
          <div v-if="messagesLoading" class="convd__loading-row">
            <LoadingState text="加载中..." />
          </div>
        </div>
      </div>

      <!-- 发送框 -->
      <ChannelMessageComposer
        :default-channel="conversation?.channel ?? 'web'"
        :sending="sending"
        :send-error="sendError"
        :send="onComposerSend"
        @clear-error="onClearSendError"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ChannelMessageBubble from '@/components/conversations/ChannelMessageBubble.vue'
import ChannelMessageComposer from '@/components/conversations/ChannelMessageComposer.vue'
import { useChannelMessageStore } from '@/stores/channel-message'
import { useRealtimeStream } from '@/composables/useRealtimeStream'
import { storeToRefs } from 'pinia'
import { CHANNEL_LABELS } from '@/api/channel-message-types'
import type { RealtimeStatus } from '@/composables/useRealtimeStream'
import type { ChannelMessage, MessageDirection } from '@/api/channel-message-types'

const route = useRoute()
const conversationId = computed(() => String(route.params.id ?? ''))

const store = useChannelMessageStore()
const {
  currentConversation: conversation,
  convDetailLoading,
  convDetailError,
  messages,
  messagesLoading,
  messagesError,
  hasMoreMessages,
  sending,
  sendError,
} = storeToRefs(store)

const olderLoading = ref(false)
const markingRead = ref(false)
const directionFilter = ref<MessageDirection | undefined>(undefined)

// 未读: 当前会话的收件未读数 — 基于已加载消息直接推导 (in 且未到 read 终态),
// 不依赖列表缓存 (直开详情页时列表可能尚未加载)
const unreadOnly = computed(() =>
  store.messages.filter((m) => m.direction === 'in' && m.status !== 'read')
    .length,
)

const channelLabel = computed(
  () =>
    CHANNEL_LABELS[conversation.value?.channel ?? ''] ??
    conversation.value?.channel ??
    '',
)

/** 倒序加载 (page 1 最新) → 时间正序展示 */
const chronologicalMessages = computed<ChannelMessage[]>(() =>
  [...messages.value].reverse(),
)

const directionFilters: Array<{ value: MessageDirection | undefined; label: string }> = [
  { value: undefined, label: '全部' },
  { value: 'in', label: '收件' },
  { value: 'out', label: '发件' },
]

// ---- 数据加载 ----
async function onLoadConversation(): Promise<void> {
  try {
    await store.fetchConversation(conversationId.value)
  } catch {
    // convDetailError 已由 store 记录
  }
}

async function onRefresh(): Promise<void> {
  try {
    await store.fetchMessages(conversationId.value, {
      page: 1,
      direction: directionFilter.value,
    })
  } catch {
    // messagesError 已由 store 记录
  }
}

function onDirectionFilter(value: MessageDirection | undefined): void {
  directionFilter.value = value
  void store.fetchMessages(conversationId.value, {
    page: 1,
    direction: value,
  })
}

async function onLoadOlder(): Promise<void> {
  olderLoading.value = true
  try {
    await store.loadOlderMessages()
  } catch {
    // 忽略 — 保留已有消息
  } finally {
    olderLoading.value = false
  }
}

// 触底/滚顶加载更早消息 (上滚检测)
function onScroll(e: Event): void {
  const el = e.target as HTMLElement
  if (
    el.scrollTop <= 8 &&
    hasMoreMessages.value &&
    !messagesLoading.value &&
    !olderLoading.value
  ) {
    void onLoadOlder()
  }
}

async function onMarkRead(): Promise<void> {
  markingRead.value = true
  try {
    await store.markConversationRead(conversationId.value)
  } catch (err) {
    sendError.value = (err as Error).message ?? '标记已读失败'
  } finally {
    markingRead.value = false
  }
}

async function onComposerSend(
  text: string,
  meta: { channel: string; accountId?: string },
): Promise<void> {
  await store.sendMessage({
    conversation_id: conversationId.value,
    channel: meta.channel,
    account_id: meta.accountId ?? null,
    direction: 'out',
    content: { text },
  })
}

function onClearSendError(): void {
  store.sendError = null
}

// ---- 会话作用域实时流 (P5MSG-04: since 断线重连补发 + 去重) ----
const RT_LABELS: Record<RealtimeStatus, string> = {
  connecting: '连接中',
  connected: '实时',
  reconnecting: '重连中',
  closed: '已断开',
}

const rt = useRealtimeStream({
  conversationId: conversationId.value,
  onEvent: (ev) => {
    switch (ev.kind) {
      case 'channel_message.created':
        // 新消息 → 重拉最新页 (正文走 REST, 事件只带 ids/status)
        void onRefresh()
        break
      case 'channel_message.status':
        // 投递状态变更 → 就地合并 (created 已含该消息时; 否则忽略)
        store.applyRealtimeEvent(ev)
        break
      case 'channel_message.read':
        store.applyRealtimeEvent(ev)
        break
      case 'conversation.updated':
        void onLoadConversation()
        void onRefresh()
        break
    }
  },
  onGap: () => {
    // 游标早于保留窗口 → 全量重取
    void onRefresh()
  },
})

const rtLabel = computed(() => RT_LABELS[rt.status.value])

onMounted(async () => {
  await onLoadConversation()
  await onRefresh()
})
</script>

<style scoped>
.convd {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 88px);
  max-width: 760px;
}

/* 头部 */
.convd__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-4);
  padding-bottom: var(--spacing-4);
  border-bottom: 1px solid var(--color-border);
}

.convd__title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.convd__sub {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: 2px;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.convd__channel {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
}

.convd__unread {
  color: var(--color-error);
}

.convd__actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

/* 实时状态 */
.convd__rt {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.convd__rt--connected {
  color: var(--color-success);
}

.convd__rt--reconnecting,
.convd__rt--connecting {
  color: var(--color-warning);
}

.convd__rt-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.convd__rt--connected .convd__rt-dot {
  animation: convd-pulse 1.6s ease-in-out infinite;
}

@keyframes convd-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* 过滤 */
.convd__filters {
  display: flex;
  gap: var(--spacing-2);
  padding: var(--spacing-3) 0;
}

.convd__filter {
  padding: var(--spacing-1) var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: transparent;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.convd__filter--active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

/* 消息流 */
.convd__messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-3) 0;
  display: flex;
  flex-direction: column;
}

.convd__older {
  text-align: center;
  padding: var(--spacing-3);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.convd__bubbles {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
  padding: var(--spacing-2);
}

.convd__loading-row {
  margin-top: var(--spacing-3);
}

/* 错误横幅 */
.convd__error {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-4);
  border-radius: var(--radius-lg);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: var(--font-size-sm);
}

.convd__error--center {
  justify-content: center;
  text-align: center;
}

.convd__error p {
  flex: 1;
}
</style>
