<template>
  <li
    class="conv-item"
    :class="{ 'conv-item--unread': item.unread_count > 0 }"
    :aria-label="`会话 ${item.subject || item.conversation_id}`"
  >
    <router-link
      :to="`/conversations/${item.conversation_id}`"
      class="conv-item__link"
    >
      <!-- 头像区: 渠道图标 -->
      <span
        class="conv-item__avatar"
        :class="`conv-item__avatar--${item.channel}`"
        :aria-hidden="true"
      >
        {{ channelIcon(item.channel) }}
      </span>

      <!-- 主体 -->
      <div class="conv-item__body">
        <div class="conv-item__row-top">
          <span class="conv-item__subject">
            {{ item.subject || '未命名会话' }}
          </span>
          <!-- 未读角标 -->
          <span
            v-if="item.unread_count > 0"
            class="conv-item__badge"
            role="status"
            :aria-label="`${item.unread_count} 条未读`"
          >
            {{ item.unread_count > 99 ? '99+' : item.unread_count }}
          </span>
          <span v-else class="conv-item__time-conv">
            {{ formatTime(item.last_message_at) }}
          </span>
        </div>
        <div class="conv-item__row-bottom">
          <p class="conv-item__preview" :title="item.last_message_preview ?? ''">
            <span v-if="directionHint" class="conv-item__preview-dir">
              {{ directionHint }}
            </span>
            <template v-if="item.last_message_preview">
              {{ item.last_message_preview }}
            </template>
            <template v-else class="conv-item__preview-empty">
              暂无消息预览
            </template>
          </p>
        </div>
      </div>

      <!-- 右侧: 渠道标签 -->
      <span class="conv-item__channel-tag">{{ channelLabel(item.channel) }}</span>
    </router-link>
  </li>
</template>

<script setup lang="ts">
import {
  CHANNEL_LABELS,
  type RealtimeConversationItem,
} from '@/api/channel-message-types'

defineProps<{
  item: RealtimeConversationItem
  /** 传入最后一条消息的 direction 提示 (in/out → 前缀「收」/「发」) */
  directionHint?: string
}>()

const CHANNEL_ICONS: Record<string, string> = {
  wechat: '💬',
  wechat_work: '💼',
  douyin: '🎵',
  xiaohongshu: '📕',
  email: '✉️',
  sms: '📱',
  whatsapp: '🟢',
  line: '⬜',
  web: '🌐',
  other: '📄',
}

function channelIcon(channel: string): string {
  return CHANNEL_ICONS[channel] ?? '📄'
}

function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel
}

/** 列表项未携带 created_at — 用 last_message_at 兜底, 无效时显示占位 */
function formatTime(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

/** 预览前缀提示由父级传入 (如 '← 收') */
</script>

<style scoped>
.conv-item {
  list-style: none;
}

.conv-item__link {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-primary);
  color: inherit;
  text-decoration: none;
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.conv-item__link:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.conv-item--unread .conv-item__link {
  border-left: 3px solid var(--color-primary);
}

/* 头像 */
.conv-item__avatar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  font-size: 18px;
}

.conv-item__avatar--wechat { background: #d1fae5; }
.conv-item__avatar--email { background: var(--color-info-light); }
.conv-item__avatar--web { background: var(--color-primary-light); }

/* 主体 */
.conv-item__body {
  flex: 1;
  min-width: 0;
}

.conv-item__row-top {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.conv-item__subject {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item__badge {
  flex-shrink: 0;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--color-error);
  color: #fff;
  font-size: 11px;
  font-weight: var(--font-weight-semibold);
}

.conv-item__time-conv {
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.conv-item__row-bottom {
  margin-top: 2px;
}

.conv-item__preview {
  margin: 0;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item__preview-dir {
  display: inline-block;
  margin-right: 4px;
  padding: 0 4px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-tertiary);
  color: var(--color-text-muted);
  font-size: 11px;
}

.conv-item__preview-empty {
  color: var(--color-text-muted);
}

/* 渠道标签 */
.conv-item__channel-tag {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-size: 11px;
}
</style>
