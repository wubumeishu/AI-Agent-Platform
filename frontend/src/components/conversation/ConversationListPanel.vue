<template>
  <aside
    class="conv-panel"
    :class="{ 'conv-panel--selected': selectedId }"
    tabindex="0"
    role="listbox"
    aria-label="会话列表"
    @keydown="handleKeydown"
  >
    <!-- 顶部：搜索 + 新建 -->
    <div class="conv-panel__top">
      <div class="conv-panel__head">
        <h2 class="conv-panel__title">会话</h2>
        <button
          class="btn btn--primary btn--sm conv-panel__new"
          :disabled="creating"
          @click="emit('new')"
        >
          + 新建
        </button>
      </div>

      <div class="conv-search">
        <span class="conv-search__icon">🔍</span>
        <input
          v-model="search"
          class="conv-search__input"
          placeholder="搜索会话..."
          aria-label="搜索会话"
          @input="onSearchInput"
        />
        <button
          v-if="search"
          class="conv-search__clear"
          aria-label="清除搜索"
          @click="clearSearch"
        >
          ×
        </button>
      </div>

      <!-- 状态筛选：正常 / 已删除（删除后在"已删除"中恢复） -->
      <div class="conv-panel__tabs" role="tablist" aria-label="会话状态">
        <button
          v-for="tab in statusTabs"
          :key="tab.value"
          class="conv-panel__tab"
          :class="{ 'conv-panel__tab--active': statusFilter === tab.value }"
          role="tab"
          :aria-selected="statusFilter === tab.value"
          @click="switchStatus(tab.value)"
        >
          {{ tab.label }}
        </button>
      </div>
    </div>

    <!-- 主体：会话列表 -->
    <div class="conv-panel__body">
      <!-- 轻提示 -->
      <div v-if="flash" class="conv-flash" :class="`conv-flash--${flashKind}`">
        <span>{{ flash }}</span>
      </div>

      <!-- Loading -->
      <LoadingState v-if="loading" text="加载会话..." />

      <!-- 列表 / 空态 -->
      <template v-else>
        <EmptyState
          v-if="conversations.length === 0"
          :icon="statusFilter === 'deleted' ? '🗑️' : '💬'"
          :title="statusFilter === 'deleted' ? '没有已删除的会话' : '暂无会话'"
          :description="
            search.trim()
              ? '没有匹配的会话，试试调整搜索关键词'
              : statusFilter === 'deleted'
                ? '被删除的会话会出现在这里'
                : '点击上方「新建」开始第一段对话'
          "
          :show-action="!search.trim() && statusFilter !== 'deleted'"
          action-text="新建会话"
          @action="emit('new')"
        />

        <ul v-else class="conv-list">
          <li
            v-for="conv in conversations"
            :key="conv.id"
            :id="`conv-item-${conv.id}`"
            class="conv-item"
            :class="{
              'conv-item--active': conv.id === selectedId,
              'conv-item--deleted': statusFilter === 'deleted',
            }"
            role="option"
            :aria-selected="conv.id === selectedId"
            tabindex="0"
            @click="emit('select', conv.id)"
            @focus="emit('select', conv.id)"
          >
            <div class="conv-item__main">
              <div class="conv-item__title-row">
                <span class="conv-item__title">
                  {{ conv.subject || '未命名会话' }}
                </span>
                <span
                  v-if="statusFilter === 'deleted'"
                  class="conv-item__deleted-tag"
                >
                  已删除
                </span>
                <span v-else class="conv-item__channel">
                  {{ getChannelLabel(conv.channel) }}
                </span>
              </div>
              <div class="conv-item__preview">
                {{ conv.summary || '暂无内容' }}
              </div>
              <div class="conv-item__meta">
                <span>
                  {{ conv.message_count }} 条消息 · {{
                    formatTime(conv.last_message_at || conv.updated_at)
                  }}
                </span>
              </div>
            </div>

            <!-- 悬停操作菜单（键盘可达：focus-within 也显示） -->
            <div
              class="conv-item__actions"
              :class="{ 'conv-item__actions--open': menuOpenId === conv.id }"
            >
              <button
                class="conv-item__action"
                :title="statusFilter === 'deleted' ? '恢复会话' : '重命名'"
                :disabled="actingId === conv.id"
                @click.stop="onRename(conv)"
              >
                ✏️
              </button>
              <button
                v-if="statusFilter === 'deleted'"
                class="conv-item__action"
                title="恢复会话"
                :disabled="actingId === conv.id"
                @click.stop="onRestore(conv)"
              >
                ↩️
              </button>
              <button
                v-else
                class="conv-item__action conv-item__action--danger"
                title="删除会话"
                :disabled="actingId === conv.id"
                @click.stop="onDelete(conv)"
              >
                🗑️
              </button>
            </div>
          </li>
        </ul>
      </template>

      <!-- 分页（后端分页） -->
      <div v-if="!loading && total > pageSize" class="conv-panel__pager">
        <button
          class="btn btn--ghost btn--sm"
          :disabled="page <= 1"
          @click="emitFetch(page - 1)"
        >
          上一页
        </button>
        <span class="conv-panel__pager-label">
          {{ page }} / {{ totalPages }}
        </span>
        <button
          class="btn btn--ghost btn--sm"
          :disabled="page >= totalPages"
          @click="emitFetch(page + 1)"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- 底部：用户信息 -->
    <div class="conv-panel__footer">
      <div class="conv-panel__avatar">{{ userInitial }}</div>
      <div class="conv-panel__user">
        <div class="conv-panel__user-name">{{ userLabel }}</div>
        <div class="conv-panel__user-sub">共 {{ total }} 个会话</div>
      </div>
      <button
        class="conv-panel__theme-toggle"
        :title="isDark ? '切换为浅色主题' : '切换为深色主题'"
        @click="toggleTheme"
      >
        {{ isDark ? '☀️' : '🌙' }}
      </button>
    </div>
  </aside>

  <!-- 重命名对话框 -->
  <Modal
    v-if="renameTarget"
    :title="statusFilter === 'deleted' ? '恢复会话' : '重命名会话'"
    @close="closeRename"
  >
    <ConversationRenameForm
      :conversation="renameTarget"
      :mode="statusFilter === 'deleted' ? 'restore' : 'rename'"
      :submitting="actingId === renameTarget.id"
      @submit="handleRenameSubmit"
      @cancel="closeRename"
    />
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useConversationStore } from '@/stores/conversation'
import { useSettingsStore } from '@/stores/settings'
import type { Conversation } from '@/api/conversation'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import ConversationRenameForm from './ConversationRenameForm.vue'

const props = defineProps<{
  selectedId?: string | null
  customerName?: string
}>()

const emit = defineEmits<{
  (e: 'new'): void
  (e: 'select', id: string): void
  (
    e: 'fetch',
    params: {
      page: number
      page_size: number
      search?: string
      status?: string
    }
  ): void
}>()

const store = useConversationStore()
const settingsStore = useSettingsStore()
const {
  conversations,
  total,
  page,
  loading,
  creating,
  listError,
} = storeToRefs(store)
const { isDark } = storeToRefs(settingsStore)

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

function formatTime(iso?: string | null) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// ---- 搜索 / 状态筛选（实时过滤：300ms 防抖触发父级拉取） ----
const search = ref('')
const statusFilter = ref<'active' | 'deleted'>('active')
let searchTimer: number | undefined

const statusTabs = [
  { value: 'active' as const, label: '全部' },
  { value: 'deleted' as const, label: '已删除' },
]

function emitFetch(pageNo: number) {
  emit('fetch', {
    page: pageNo,
    page_size: pageSize,
    search: search.value.trim() || undefined,
    status: statusFilter.value === 'deleted' ? 'deleted' : undefined,
  })
}

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => emitFetch(1), 300)
}

function clearSearch() {
  search.value = ''
  emitFetch(1)
}

function switchStatus(value: 'active' | 'deleted') {
  statusFilter.value = value
  emitFetch(1)
}

function readFilters() {
  return {
    search: search.value.trim() || undefined,
    status: statusFilter.value === 'deleted' ? 'deleted' : undefined,
  }
}

defineExpose({ readFilters, switchStatus })

const pageSize = 20
const totalPages = computed(() =>
  Math.max(1, Math.ceil(total.value / pageSize))
)

// ---- 轻提示 ----
const flash = ref('')
const flashKind = ref<'success' | 'error'>('success')
let flashTimer: number | undefined

function showFlash(message: string, kind: 'success' | 'error' = 'success') {
  flash.value = message
  flashKind.value = kind
  if (flashTimer) window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => (flash.value = ''), 2600)
}

// ---- 重命名 / 删除 / 恢复 ----
const renameTarget = ref<Conversation | null>(null)
const menuOpenId = ref<string>('')
const actingId = ref('')

function onRename(conv: Conversation) {
  if (statusFilter.value === 'deleted') {
    // 已删除会话：直接确认恢复
    if (window.confirm(`确定恢复会话「${conv.subject || '未命名'}」吗？`)) {
      onRestore(conv)
    }
    return
  }
  renameTarget.value = conv
}

function closeRename() {
  renameTarget.value = null
}

async function handleRenameSubmit(data: { subject?: string; restore?: boolean }) {
  const conv = renameTarget.value
  if (!conv) return
  actingId.value = conv.id
  try {
    if (data.restore) {
      await store.restoreConversation(conv.id)
      showFlash(`会话「${conv.subject || '未命名'}」已恢复`)
    } else if (data.subject !== undefined) {
      await store.updateConversation(conv.id, { subject: data.subject })
      showFlash('会话已重命名')
    }
    closeRename()
  } catch (error) {
    console.error('操作失败:', error)
    showFlash('操作失败，请重试', 'error')
  } finally {
    actingId.value = ''
  }
}

async function onRestore(conv: Conversation) {
  actingId.value = conv.id
  try {
    await store.restoreConversation(conv.id)
    showFlash(`会话「${conv.subject || '未命名'}」已恢复`)
  } catch (error) {
    console.error('恢复失败:', error)
    showFlash('恢复失败，请重试', 'error')
  } finally {
    actingId.value = ''
  }
}

async function onDelete(conv: Conversation) {
  if (!window.confirm(`确定删除会话「${conv.subject || '未命名'}」吗？删除后可在「已删除」中恢复。`)) {
    return
  }
  actingId.value = conv.id
  try {
    await store.deleteConversation(conv.id)
    showFlash('会话已删除')
  } catch (error) {
    console.error('删除失败:', error)
    showFlash('删除失败，请重试', 'error')
  } finally {
    actingId.value = ''
  }
}

// ---- 键盘导航（↑/↓ 在列表间移动，Enter 打开，n 新建，/ 聚焦搜索） ----
function handleKeydown(event: KeyboardEvent) {
  const items = conversations.value
  if (items.length === 0) return

  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const currentIdx = items.findIndex((c) => c.id === props.selectedId)
    const next =
      event.key === 'ArrowDown'
        ? Math.min(items.length - 1, currentIdx + 1)
        : Math.max(0, currentIdx <= 0 ? 0 : currentIdx - 1)
    focusItem(items[next]?.id)
  } else if (event.key === 'Enter') {
    if (props.selectedId) {
      emit('select', props.selectedId)
    }
  } else if (event.key === 'n' || event.key === 'N') {
    emit('new')
  } else if (event.key === '/') {
    event.preventDefault()
    document
      .querySelector<HTMLInputElement>('.conv-search__input')
      ?.focus()
  }
}

function focusItem(id?: string) {
  if (!id) return
  const el = document.getElementById(`conv-item-${id}`)
  el?.focus()
  if (el instanceof HTMLElement) {
    el.scrollIntoView({ block: 'nearest' })
  }
  menuOpenId.value = ''
}

// 选中项变化时同步高亮
watch(
  () => props.selectedId,
  (id) => {
    menuOpenId.value = ''
    if (id) focusItem(id)
  }
)

// ---- 底部用户信息 ----
const userLabel = computed(() => props.customerName || '当前用户')
const userInitial = computed(() =>
  (props.customerName || 'U').trim().charAt(0).toUpperCase() || 'U'
)

function toggleTheme() {
  settingsStore.setTheme(isDark.value ? 'light' : 'dark')
}

// 列表错误轻提示（如后端未就绪的 404）
watch(listError, (err) => {
  if (err) showFlash(`加载失败：${err}`, 'error')
})
</script>

<style scoped>
.conv-panel {
  width: 280px;
  min-width: 280px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  outline: none;
  transition: border-color var(--transition-fast);
}

.conv-panel:focus-visible {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* ---- 顶部 ---- */
.conv-panel__top {
  padding: var(--spacing-4) var(--spacing-4) 0;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
  border-bottom: 1px solid var(--color-border);
}

.conv-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.conv-panel__title {
  margin: 0;
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.conv-search {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  transition: border-color var(--transition-fast);
}

.conv-search:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.conv-search__icon {
  font-size: 13px;
  opacity: 0.7;
  flex-shrink: 0;
}

.conv-search__input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--color-text-primary);
}

.conv-search__clear {
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0 2px;
}

.conv-search__clear:hover {
  color: var(--color-text-primary);
}

/* 状态筛选 tabs */
.conv-panel__tabs {
  display: flex;
  gap: var(--spacing-1);
  background: var(--color-bg-tertiary);
  border-radius: 6px;
  padding: 3px;
}

.conv-panel__tab {
  flex: 1;
  padding: 5px 0;
  border: none;
  background: transparent;
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.conv-panel__tab--active {
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
  box-shadow: var(--shadow-sm);
}

/* ---- 主体 ---- */
.conv-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--spacing-2) 0;
}

.conv-flash {
  padding: 8px 12px;
  margin: 4px 12px;
  border-radius: var(--radius-md);
  font-size: 12px;
}

.conv-flash--success {
  background: var(--color-success-light);
  color: var(--color-success);
}

.conv-flash--error {
  background: var(--color-error-light);
  color: var(--color-error);
}

.conv-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.conv-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  margin: 2px 8px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  outline: none;
}

.conv-item:hover,
.conv-item:focus-visible {
  background: var(--color-bg-tertiary);
}

.conv-item--active {
  background: var(--color-primary-light);
}

.conv-item--active .conv-item__title {
  color: var(--color-primary);
  font-weight: var(--font-weight-medium);
}

.conv-item__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conv-item__title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.conv-item__title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item__channel {
  font-size: 10px;
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  padding: 1px 6px;
  flex-shrink: 0;
}

.conv-item__deleted-tag {
  font-size: 10px;
  color: var(--color-error);
  background: var(--color-error-light);
  border-radius: var(--radius-full);
  padding: 1px 6px;
  flex-shrink: 0;
}

.conv-item__preview {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-item__meta {
  font-size: 11px;
  color: var(--color-text-muted);
}

/* 悬停操作菜单（鼠标 hover 或键盘 focus-within 时显示） */
.conv-item__actions {
  position: absolute;
  top: 6px;
  right: 8px;
  display: flex;
  gap: 2px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  padding: 2px;
  box-shadow: var(--shadow-md);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-2px);
  transition: all var(--transition-fast);
  z-index: 5;
}

.conv-item:hover .conv-item__actions,
.conv-item:focus-within .conv-item__actions,
.conv-item__actions--open {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.conv-item__action {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  padding: 3px 5px;
  border-radius: 4px;
  line-height: 1;
  transition: background var(--transition-fast);
}

.conv-item__action:hover:not(:disabled) {
  background: var(--color-bg-tertiary);
}

.conv-item__action--danger:hover:not(:disabled) {
  background: var(--color-error-light);
}

.conv-item__action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 分页 */
.conv-panel__pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  border-top: 1px solid var(--color-border);
}

.conv-panel__pager-label {
  font-size: 12px;
  color: var(--color-text-muted);
}

/* ---- 底部用户信息 ---- */
.conv-panel__footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--spacing-3) var(--spacing-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
}

.conv-panel__avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--color-primary-light);
  color: var(--color-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: var(--font-weight-semibold);
  flex-shrink: 0;
}

.conv-panel__user {
  flex: 1;
  min-width: 0;
}

.conv-panel__user-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv-panel__user-sub {
  font-size: 11px;
  color: var(--color-text-muted);
}

.conv-panel__theme-toggle {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
  padding: 4px;
  border-radius: var(--radius-md);
  line-height: 1;
  transition: background var(--transition-fast);
}

.conv-panel__theme-toggle:hover {
  background: var(--color-bg-tertiary);
}

/* 响应式：<1200px 时由父级决定堆叠，面板保持 280px 但允许收窄 */
@media (max-width: 1199px) {
  .conv-panel {
    width: 100%;
    min-width: 0;
  }
}
</style>
