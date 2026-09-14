<template>
  <div class="cmb" :class="`cmb--${msg.direction}`">
    <!-- 方向 + 渠道头 -->
    <div class="cmb__head">
      <span class="cmb__dir">{{ directionLabel }}</span>
      <span class="cmb__channel" :class="`cmb__channel--${msg.channel}`">
        {{ channelLabel }}
      </span>
      <span v-if="providerId" class="cmb__provider" :title="providerId">
        ref: {{ providerId }}
      </span>
      <!-- 投递状态标记 (仅出站消息) -->
      <span
        v-if="msg.direction === 'out'"
        class="cmb__status"
        :class="`cmb__status--${msg.status}`"
        :title="statusTitle"
        role="status"
      >
        <span class="cmb__status-mark" aria-hidden="true">{{ statusIcon }}</span>
        {{ statusLabel }}
      </span>
    </div>

    <!-- 气泡正文 -->
    <div class="cmb__bubble">
      <p class="cmb__text">{{ displayText }}</p>
      <dl v-if="extraContent.length" class="cmb__extra">
        <div v-for="row in extraContent" :key="row.key" class="cmb__extra-row">
          <dt>{{ row.key }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
      <!-- 失败详情 -->
      <div v-if="msg.status === 'failed' && errorMsg" class="cmb__error">
        <span class="cmb__error-icon" aria-hidden="true">⚠️</span>
        <span>{{ errorMsg }}</span>
      </div>
    </div>

    <!-- 元信息 -->
    <div class="cmb__meta">
      <span class="cmb__time">{{ displayTime }}</span>
      <span v-if="msg.provider_message_id" class="cmb__meta-id">
        {{ msg.provider_message_id }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  CHANNEL_LABELS,
  DIRECTION_LABELS,
  STATUS_LABELS,
  type ChannelMessage,
} from '@/api/channel-message-types'

const props = defineProps<{ msg: ChannelMessage }>()

/** 气泡内展示的文本: 优先 content.text, 其次 content.content, 再兜底 */
const displayText = computed(() => {
  const c = props.msg.content ?? {}
  const text = c.text ?? c.content ?? c.preview
  if (typeof text === 'string' && text.trim()) return text
  if (typeof text === 'number' || typeof text === 'boolean') return String(text)
  // 纯媒体 / 其它结构化载荷
  if (Object.keys(c).length > 0) {
    return JSON.stringify(c, null, 2)
  }
  return '(空消息)'
})

/** content 中除 text/content/preview 外的其它字段 (media refs / platform fields) */
const extraContent = computed(() => {
  const c = props.msg.content ?? {}
  const skip = new Set(['text', 'content', 'preview'])
  const rows: Array<{ key: string; value: string }> = []
  for (const [k, v] of Object.entries(c)) {
    if (skip.has(k)) continue
    rows.push({ key: k, value: String(v ?? '') })
  }
  return rows.slice(0, 6)
})

const errorMsg = computed(() => {
  if (!props.msg.error) return ''
  const e = props.msg.error as Record<string, unknown>
  const m = e.message ?? e.code ?? e.detail
  return m ? String(m) : JSON.stringify(props.msg.error)
})

const directionLabel = computed(
  () => DIRECTION_LABELS[props.msg.direction] ?? props.msg.direction,
)
const channelLabel = computed(
  () => CHANNEL_LABELS[props.msg.channel] ?? props.msg.channel,
)
const providerId = computed(() => props.msg.provider_message_id ?? '')

const statusLabel = computed(
  () => STATUS_LABELS[props.msg.status] ?? props.msg.status,
)
const statusIcon = computed(() => {
  switch (props.msg.status) {
    case 'queued': return '⏳'
    case 'sent': return '🕓'
    case 'delivered': return '✅'
    case 'read': return '👁️'
    case 'failed': return '⚠️'
    default: return '•'
  }
})
const statusTitle = computed(() => {
  const base = `投递状态: ${statusLabel.value}`
  return errorMsg.value ? `${base} — ${errorMsg.value}` : base
})

const displayTime = computed(() => {
  const d = new Date(props.msg.created_at)
  if (Number.isNaN(d.getTime())) return props.msg.created_at
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
})
</script>

<style scoped>
.cmb {
  max-width: 560px;
}

.cmb--in {
  margin-right: auto;
}

.cmb--out {
  margin-left: auto;
}

.cmb__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.cmb--out .cmb__head {
  flex-direction: row-reverse;
}

.cmb__dir {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.cmb__channel {
  padding: 1px 7px;
  border-radius: var(--radius-full);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.cmb__channel--wechat { background: #d1fae5; }
.cmb__channel--email { background: var(--color-info-light); }
.cmb__channel--web { background: var(--color-primary-light); }

.cmb__provider {
  font-size: 11px;
  color: var(--color-text-muted);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 投递状态标记 */
.cmb__status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: var(--font-weight-medium);
  cursor: default;
}

.cmb__status--queued {
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
}
.cmb__status--sent {
  color: var(--color-info);
  background: var(--color-info-light);
}
.cmb__status--delivered {
  color: var(--color-success);
  background: var(--color-success-light);
}
.cmb__status--read {
  color: var(--color-success);
  background: var(--color-success-light);
  font-weight: var(--font-weight-semibold);
}
.cmb__status--failed {
  color: var(--color-error);
  background: var(--color-error-light);
}

/* 气泡 */
.cmb__bubble {
  padding: var(--spacing-3) var(--spacing-4);
  border-radius: var(--radius-lg);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}

.cmb--in .cmb__bubble {
  border-top-left-radius: var(--radius-sm);
}

.cmb--out .cmb__bubble {
  border-top-right-radius: var(--radius-sm);
  background: var(--color-primary-light);
  border-color: color-mix(in srgb, var(--color-primary) 25%, transparent);
}

.cmb__text {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.cmb__extra {
  margin: var(--spacing-2) 0 0;
  padding: var(--spacing-2);
  background: color-mix(in srgb, var(--color-text-primary) 4%, transparent);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
}

.cmb__extra-row {
  display: flex;
  gap: var(--spacing-2);
}

.cmb__extra-row dt {
  color: var(--color-text-muted);
  flex-shrink: 0;
}

.cmb__extra-row dd {
  margin: 0;
  color: var(--color-text-secondary);
  word-break: break-all;
}

.cmb__error {
  display: flex;
  gap: var(--spacing-2);
  margin-top: var(--spacing-2);
  padding: var(--spacing-2);
  border-radius: var(--radius-sm);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: var(--font-size-xs);
}

.cmb__meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-top: var(--spacing-1);
  font-size: 11px;
  color: var(--color-text-muted);
}

.cmb--out .cmb__meta {
  justify-content: flex-end;
}
</style>
