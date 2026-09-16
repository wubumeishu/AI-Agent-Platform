<template>
  <div class="convs-view">
    <PageHeader
      title="会话管理"
      description="渠道会话列表 · 未读角标 · 最后消息预览 (实时刷新)"
      :loading="convLoading"
    >
      <template #actions>
        <!-- P5MSG-FIX-2 (P1-3): 会话预览按客户归属收口 → 客户选择器 -->
        <label
          v-if="customers.length > 0"
          class="convs-view__customer-scope"
          :for="'convs-customer-select'"
        >
          <span class="convs-view__customer-scope-label">客户</span>
          <select
            id="convs-customer-select"
            class="form-select form-select--sm"
            :value="selectedCustomerId"
            @change="onCustomerChange((($event.target as HTMLSelectElement).value))"
          >
            <option v-for="c in customers" :key="c.id" :value="c.id">
              {{ c.name }}
            </option>
          </select>
        </label>
        <span
          class="convs-view__rt-badge"
          :class="`convs-view__rt-badge--${rtStatus}`"
          role="status"
          :title="rtStatusTitle"
        >
          <span class="convs-view__rt-dot" aria-hidden="true"></span>
          {{ rtStatusLabel }}
        </span>
        <button
          class="btn btn--ghost btn--sm"
          :disabled="convLoading || !selectedCustomerId"
          @click="onRefresh"
        >
          刷新
        </button>
      </template>
    </PageHeader>

    <!-- 客户加载失败 / 无客户 (P1-3 无法定位 customer scope) -->
    <EmptyState
      v-if="!convLoading && !convError && customers.length === 0"
      icon="🏷️"
      title="暂无可选客户"
      description="会话预览按客户归属展示 (P5MSG-FIX P1-3)。请先在 CRM 创建客户"
    />

    <!-- 加载态 -->
    <LoadingState v-else-if="convLoading && conversations.length === 0" text="加载会话..." />

    <!-- 错误态 (含 P0-2 未配置 VITE_REALTIME_PUBLISH_TOKEN 时的 401) -->
    <div v-else-if="convError" class="convs-view__error" role="alert">
      <p>会话列表加载失败: {{ convError }}</p>
      <button class="btn btn--primary btn--sm" @click="onRefresh">重试</button>
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="conversations.length === 0"
      icon="💬"
      :title="`该客户暂无活跃会话`"
      description="渠道 (微信 / 抖音 / 小红书 / 邮件…) 的活跃会话会出现在这里"
    />

    <!-- 会话列表 -->
    <div v-else class="convs-view__body">
      <!-- 汇总条 -->
      <div class="convs-view__summary">
        <span>{{ conversations.length }} 个活跃会话</span>
        <span v-if="totalUnread > 0" class="convs-view__unread">
          <span class="convs-view__unread-num">{{ totalUnread }}</span>
          条未读消息
        </span>
      </div>

      <ul class="convs-view__list">
        <ConversationListItem
          v-for="item in conversations"
          :key="item.conversation_id"
          :item="item"
        />
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConversationListItem from '@/components/conversations/ConversationListItem.vue'
import { useChannelMessageStore } from '@/stores/channel-message'
import { useRealtimeStream } from '@/composables/useRealtimeStream'
import { storeToRefs } from 'pinia'
import { customerApi } from '@/api/customer'
import type { Customer } from '@/api/types'
import type { RealtimeStatus } from '@/composables/useRealtimeStream'

const store = useChannelMessageStore()
const { conversations, totalUnread, convLoading, convError } = storeToRefs(store)

// ---- P5MSG-FIX-2 (P1-3): 会话预览是 PII, 后端按 customer 归属强校验 ----
// 会话列表必须落在某个客户名下 → 客户选择器 (默认第一个客户), 切换时重拉列表。
const customers = ref<Customer[]>([])
const selectedCustomerId = ref('')

async function loadCustomers(): Promise<void> {
  try {
    const data = await customerApi.list({ limit: 100 })
    customers.value = data.data ?? []
    if (customers.value.length > 0) {
      const first = customers.value[0]
      if (first) selectedCustomerId.value = first.id
    }
  } catch {
    // 客户列表加载失败 — 会话列表区展示错误横幅即可 (无法定位 customer scope)
    customers.value = []
  }
}

async function onMountedLoad(): Promise<void> {
  if (!selectedCustomerId.value) return
  try {
    await store.fetchConversationList(selectedCustomerId.value)
  } catch {
    // convError 已由 store 记录; 视图展示错误横幅
  }
}

async function onCustomerChange(value: string): Promise<void> {
  selectedCustomerId.value = value
  void onMountedLoad()
  void store.refreshUnread(value).catch(() => {})
}

function onRefresh(): void {
  if (!selectedCustomerId.value) return
  void onMountedLoad()
  void store.refreshUnread(selectedCustomerId.value).catch(() => {})
}

// ---- 全局实时流 (所有会话): 新消息 / 状态变更 / 已读 → 刷新列表 ----
const rt = useRealtimeStream({
  onEvent: (ev) => {
    // 新消息 / 会话活动 → 轻量刷新列表 + 未读 (P1-3: 带 customer scope)
    if (!selectedCustomerId.value) return
    if (ev.kind === 'channel_message.created' || ev.kind === 'conversation.updated') {
      void store.fetchConversationList(selectedCustomerId.value).catch(() => {})
      void store.refreshUnread(selectedCustomerId.value).catch(() => {})
    } else if (ev.kind === 'channel_message.read') {
      store.applyRealtimeEvent(ev)
      void store.refreshUnread(selectedCustomerId.value).catch(() => {})
    }
  },
  onGap: () => {
    // since 游标早于服务端保留窗口 → REST 全量重取
    if (selectedCustomerId.value) {
      void store.fetchConversationList(selectedCustomerId.value).catch(() => {})
    }
  },
})

const RT_STATUS_LABELS: Record<RealtimeStatus, string> = {
  connecting: '连接中',
  connected: '实时连接正常',
  reconnecting: '重连中…',
  closed: '已断开',
}

const rtStatus = computed(() => rt.status.value)
const rtStatusLabel = computed(() => RT_STATUS_LABELS[rtStatus.value])
const rtStatusTitle = computed(
  () => `实时通道: ${rtStatusLabel.value} (最后处理序号 ${rt.lastSeq.value})`,
)

onMounted(async () => {
  // P1-3: 先定位 customer scope, 再拉会话列表 (顺序依赖)
  await loadCustomers()
  await onMountedLoad()
})
</script>

<style scoped>
.convs-view {
  max-width: 820px;
}

/* P5MSG-FIX-2 (P1-3): 客户 scope 选择器 */
.convs-view__customer-scope {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.convs-view__customer-scope select {
  width: 180px;
}

/* 实时状态徽标 */
.convs-view__rt-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-size: 12px;
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
}

.convs-view__rt-badge--connected {
  color: var(--color-success);
  background: var(--color-success-light);
}

.convs-view__rt-badge--reconnecting,
.convs-view__rt-badge--connecting {
  color: var(--color-warning);
  background: var(--color-warning-light);
}

.convs-view__rt-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.convs-view__rt-badge--connected .convs-view__rt-dot {
  animation: convs-pulse 1.6s ease-in-out infinite;
}

@keyframes convs-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* 错误态 */
.convs-view__error {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-4);
  border-radius: var(--radius-lg);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: var(--font-size-sm);
}

.convs-view__error p {
  flex: 1;
}

/* 列表区 */
.convs-view__body {
  display: flex;
  flex-direction: column;
}

.convs-view__summary {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-3);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.convs-view__unread {
  color: var(--color-text-secondary);
}

.convs-view__unread-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-error);
  color: #fff;
  font-size: 11px;
  font-weight: var(--font-weight-semibold);
  margin-right: 4px;
}

.convs-view__list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}
</style>
