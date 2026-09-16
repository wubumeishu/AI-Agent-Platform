<template>
  <div class="chat-panel">
    <!-- 消息滚动区（可向上滚动加载历史） -->
    <div
      ref="scrollEl"
      class="chat-panel__scroll"
      role="log"
      aria-label="消息记录"
      :aria-busy="initialLoading || loadingOlder || streaming ? 'true' : 'false'"
      @scroll.passive="onScroll"
    >
      <!-- 加载更多 -->
      <div v-if="!initialLoading" class="chat-panel__load-more">
        <button
          v-if="canLoadOlder"
          class="btn btn--ghost btn--sm chat-panel__load-btn"
          type="button"
          :disabled="loadingOlder"
          @click="loadOlder"
        >
          <span v-if="loadingOlder" class="chat-panel__spinner" aria-hidden="true"></span>
          {{ loadingOlder ? '加载中...' : `加载更早消息（还有 ${olderRemaining} 条）` }}
        </button>
        <p v-else-if="olderRemaining === 0 && messages.length > 0" class="chat-panel__all-loaded">
          已加载全部 {{ messagesTotal }} 条消息
        </p>
      </div>

      <!-- 会话加载失败 -->
      <EmptyState
        v-if="loadFailed"
        icon="⚠️"
        title="消息加载失败"
        :description="loadError || '请检查网络后重试'"
        show-action
        action-text="重试"
        @action="retryLoad"
      />

      <!-- 加载中 -->
      <LoadingState v-else-if="initialLoading" text="加载消息..." />

      <!-- 消息列表 -->
      <template v-else>
        <div v-if="messages.length === 0" class="chat-panel__empty">
          <span class="chat-panel__empty-icon">📭</span>
          <p>暂无消息，发送第一条消息开始对话</p>
        </div>

        <ul v-else class="chat-panel__list">
          <li v-for="(msg, idx) in messages" :key="msg.id" class="chat-panel__item">
            <MessageBubble
              :role="msg.role"
              :content="msg.content"
              :created-at="msg.created_at"
              :streaming="isStreamingBubble(msg)"
              :interrupted="isInterruptedBubble(msg)"
            />
          </li>

          <!-- 生成中但 AI 尚未输出首个 token：思考指示 -->
          <li
            v-if="streaming && awaitingFirstChunk"
            class="chat-panel__item"
            aria-live="polite"
          >
            <div class="chat-panel__thinking" role="status">
              <span class="chat-panel__thinking-dots" aria-hidden="true">
                <span></span><span></span><span></span>
              </span>
              <span>AI 正在思考…</span>
            </div>
          </li>
        </ul>
      </template>

      <!-- 回到底部 -->
      <button
        v-if="showJumpToBottom"
        class="chat-panel__jump"
        type="button"
        aria-label="回到底部"
        @click="jumpToBottom"
      >
        ↓
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useConversationStore } from '@/stores/conversation'
import { conversationApi } from '@/api/conversation'
import type { Message } from '@/api/conversation'
import MessageBubble from './MessageBubble.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingState from '@/components/common/LoadingState.vue'

const props = defineProps<{
  conversationId: string
}>()

const emit = defineEmits<{
  (e: 'loaded'): void
  (e: 'error', message: string): void
}>()

const store = useConversationStore()
const { messages, messagesTotal, streaming, awaitingFirstChunk } = storeToRefs(store)

// ---- 本地 UI 状态 ----
const scrollEl = ref<HTMLElement | null>(null)
const initialLoading = ref(false)
const loadingOlder = ref(false)
/** 已加载的「最新」一页页码（后端按时间升序分页，page=1 为最早） */
const lastPage = ref(0)
/** 最近一次分页请求的 page_size */
const pageSize = ref(50)
/** 首屏/重试加载失败 */
const loadFailed = ref(false)
const loadError = ref<string | null>(null)

// ---- 历史消息总数与可加载余量 ----
const loadedCount = computed(() => messages.value.length)
const olderRemaining = computed(() =>
  Math.max(0, messagesTotal.value - loadedCount.value)
)
const canLoadOlder = computed(
  () =>
    olderRemaining.value > 0 &&
    !initialLoading.value &&
    !loadingOlder.value
)

// ---- 首次 / 切换会话加载（定位并加载「最新」一页） ----
async function loadInitial() {
  loadFailed.value = false
  loadError.value = null
  initialLoading.value = true
  try {
    // 1) 先拿总数（用相同 page_size 请求第 1 页），计算最新一页的页码（后端按时间升序分页）
    const probe = await conversationApi.listMessages(props.conversationId, {
      page: 1,
      page_size: pageSize.value,
    })
    const total = probe.total
    const lastPageNum = total === 0 ? 1 : Math.max(1, Math.ceil(total / probe.page_size))
    // 2) 加载最新一页
    const data = await conversationApi.listMessages(props.conversationId, {
      page: lastPageNum,
      page_size: pageSize.value,
    })
    messages.value = data.items
    messagesTotal.value = total
    lastPage.value = data.page
    // 记录服务端实际采用的页大小（可能被 max 截断），供 loadOlder 计算更早页
    pageSize.value = data.page_size
    await scrollToBottom(false)
    emit('loaded')
  } catch (error) {
    loadFailed.value = true
    loadError.value = (error as Error).message || '消息加载失败'
    emit('error', loadError.value || '消息加载失败')
  } finally {
    initialLoading.value = false
  }
}

async function retryLoad() {
  await loadInitial()
}

// ---- 加载更早历史（按钮触发；后端升序分页，更早页在前，保持视口位置） ----
async function loadOlder() {
  if (loadingOlder.value || !canLoadOlder.value) return
  loadingOlder.value = true
  const el = scrollEl.value
  const prevHeight = el?.scrollHeight ?? 0
  const prevScrollTop = el?.scrollTop ?? 0
  try {
    // 不走 store.fetchMessages（会整体替换 messages 数组），直接请求更早页并前置拼接
    const olderPage = lastPage.value - 1
    const data = await conversationApi.listMessages(props.conversationId, {
      page: olderPage,
      page_size: pageSize.value,
    })
    // 去重：已加载消息 id 集合（防御时间戳非唯一导致的分页边界重复）
    const seen = new Set(messages.value.map((m) => m.id))
    const fresh = data.items.filter((m) => !seen.has(m.id))
    if (fresh.length > 0) {
      messages.value = [...fresh, ...messages.value]
    }
    // messagesTotal 始终为服务端总数（含未加载部分），无需累加
    lastPage.value = data.page
    await nextTick()
    if (el) {
      const newHeight = el.scrollHeight
      el.scrollTop = prevScrollTop + (newHeight - prevHeight)
    }
  } catch {
    // 静默失败：按钮可再次点击
  } finally {
    loadingOlder.value = false
  }
}

// ---- 自动滚动（新消息 / 流式 token 追加时） ----
/** 用户是否贴近底部（贴底才自动跟随） */
const isPinned = ref(true)

function onScroll() {
  const el = scrollEl.value
  if (!el) return
  isPinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

async function scrollToBottom(smooth = true) {
  isPinned.value = true
  await nextTick()
  const el = scrollEl.value
  if (!el) return
  if (smooth) {
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  } else {
    el.scrollTop = el.scrollHeight
  }
}

function jumpToBottom() {
  scrollToBottom(true)
}

/** 流式内容增长 → 贴底时自动跟随 */
watch(
  () => messages.value[messages.value.length - 1]?.content,
  () => {
    if (isPinned.value && (streaming.value || messages.value.length > 0)) {
      scrollToBottom(false)
    }
  }
)

/** 新消息追加（用户消息 / AI 落库）→ 贴底时自动跟随 */
watch(loadedCount, () => {
  if (isPinned.value) scrollToBottom(false)
})

const showJumpToBottom = computed(
  () => !isPinned.value && loadedCount.value > 0 && !loadingOlder.value
)

// ---- 气泡状态判定 ----
function isStreamingBubble(msg: Message): boolean {
  if (!streaming.value) return false
  const last = messages.value[messages.value.length - 1]
  return msg.role === 'assistant' && msg.id === last?.id && last.id.startsWith('tmp-')
}

/** 中断后残留的 tmp- 消息（部分内容 + 已中断标记） */
function isInterruptedBubble(msg: Message): boolean {
  return !streaming.value && msg.id.startsWith('tmp-') && msg.role === 'assistant'
}

watch(
  () => props.conversationId,
  (id, prev) => {
    if (id && id !== prev) {
      // 切换会话：先取消进行中的生成，再加载新会话消息
      store.abortStream()
      loadFailed.value = false
      lastPage.value = 0
      void loadInitial()
    }
  },
  { immediate: true }
)

defineExpose({ jumpToBottom, scrollToBottom, loadInitial })
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  position: relative;
}

.chat-panel__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--spacing-4);
  position: relative;
  scroll-behavior: smooth;
}

/* 加载更多 */
.chat-panel__load-more {
  text-align: center;
  padding-bottom: var(--spacing-3);
}

.chat-panel__load-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chat-panel__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: var(--radius-full);
  animation: chat-panel-spin 700ms linear infinite;
}

@keyframes chat-panel-spin {
  to {
    transform: rotate(360deg);
  }
}

.chat-panel__all-loaded {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

/* 空状态 */
.chat-panel__empty {
  text-align: center;
  color: var(--color-text-muted);
  padding: var(--spacing-6) 0;
  font-size: 13px;
}

.chat-panel__empty-icon {
  font-size: 28px;
  display: block;
  margin-bottom: 8px;
}

.chat-panel__empty p {
  margin: 0;
}

/* 消息列表 */
.chat-panel__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.chat-panel__item {
  display: flex;
}

/* 「AI 正在思考」指示 */
.chat-panel__thinking {
  align-self: flex-start;
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-muted);
  animation: chat-panel-in 200ms ease;
}

.chat-panel__thinking-dots {
  display: inline-flex;
  gap: 3px;
}

.chat-panel__thinking-dots span {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: var(--color-text-muted);
  animation: chat-panel-dot 1.2s ease-in-out infinite;
}

.chat-panel__thinking-dots span:nth-child(2) {
  animation-delay: 0.15s;
}

.chat-panel__thinking-dots span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes chat-panel-dot {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

@keyframes chat-panel-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 回到底部悬浮按钮 */
.chat-panel__jump {
  position: sticky;
  bottom: var(--spacing-2);
  margin-left: auto;
  display: flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg-primary);
  color: var(--color-text-secondary);
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
  cursor: pointer;
  transition: background var(--transition-fast), transform var(--transition-fast);
}

.chat-panel__jump:hover {
  background: var(--color-bg-tertiary);
  transform: translateY(-1px);
}

@media (prefers-reduced-motion: reduce) {
  .chat-panel__scroll {
    scroll-behavior: auto;
  }
  .chat-panel__thinking,
  .chat-panel__thinking-dots span,
  .chat-panel__spinner {
    animation: none;
  }
}
</style>
