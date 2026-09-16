<template>
  <div class="cmcom">
    <!-- 错误提示 (发送失败横幅) -->
    <div v-if="sendError" class="cmcom__error" role="alert">
      <span aria-hidden="true">⚠️</span>
      <span>{{ sendError }}</span>
      <button class="btn btn--ghost btn--sm" @click="onClearError">知道了</button>
    </div>

    <!-- 高级选项: 渠道 + 账号 (折叠) -->
    <details class="cmcom__options">
      <summary class="cmcom__summary">
        渠道与账号 · {{ channelLabel }}
        <span v-if="accountId" class="cmcom__account-name">{{ accountName }}</span>
      </summary>
      <div class="cmcom__options-body">
        <label class="cmcom__field">
          <span class="cmcom__label">渠道</span>
          <select
            v-model="channel"
            class="form-select form-select--sm"
            aria-label="消息渠道"
          >
            <option v-for="c in channelOptions" :key="c.value" :value="c.value">
              {{ c.label }}
            </option>
          </select>
        </label>

        <label class="cmcom__field">
          <span class="cmcom__label">绑定账号</span>
          <select
            v-model="accountId"
            class="form-select form-select--sm"
            :disabled="channel === 'web'"
            aria-label="发送账号"
          >
            <option value="">
              {{ channel === 'web' ? '无需账号 (网页渠道)' : '不绑定账号' }}
            </option>
            <option v-for="a in accountOptions" :key="a.id" :value="a.id">
              {{ a.name }} ({{ a.username || a.status }})
            </option>
          </select>
        </label>
      </div>
    </details>

    <!-- 输入区 -->
    <div class="cmcom__input-row">
      <textarea
        id="cmcom-textarea"
        ref="textareaRef"
        v-model="text"
        class="cmcom__textarea"
        rows="2"
        placeholder="输入消息内容 (Enter 发送 / Shift+Enter 换行)"
        :aria-label="`向 ${channelLabel} 发送消息`"
        @keydown="onKeydown"
      ></textarea>
      <button
        class="btn btn--primary"
        :disabled="!canSend"
        :title="canSend ? '发送' : '输入内容后可发送'"
        @click="doSend"
      >
        <span v-if="sending">发送中…</span>
        <span v-else>发送</span>
      </button>
    </div>
    <p class="cmcom__hint">
      发送后消息进入 <code>queued</code> 队列, 投递状态将实时刷新 ·
      渠道适配器 (P5MSG-03) 完成实际送达
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { accountApi } from '@/api/account'
import type { Account } from '@/api/types'
import {
  CHANNEL_LABELS,
  MESSAGE_CHANNELS,
} from '@/api/channel-message-types'

const props = withDefaults(
  defineProps<{
    /** 会话渠道 — 默认选中 (会话归属渠道) */
    defaultChannel?: string
    /** 默认账号 */
    defaultAccountId?: string
    /** 发送动作: 成功则清空输入; 抛错则恢复文本供重试 */
    send: (
      text: string,
      meta: { channel: string; accountId?: string },
    ) => Promise<void>
    /** 当前发送中状态 (来自 store.sending, 由父级回传) */
    sending?: boolean
    /** 当前发送错误 (来自 store.sendError) */
    sendError?: string | null
  }>(),
  {
    defaultChannel: 'web',
    defaultAccountId: '',
    sending: false,
    sendError: null,
  },
)

const emit = defineEmits<{
  (e: 'clear-error'): void
}>()

const text = ref('')
const channel = ref(
  MESSAGE_CHANNELS.includes(props.defaultChannel as never)
    ? props.defaultChannel
    : 'web',
)
const accountId = ref(props.defaultAccountId)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const accountOptions = ref<Account[]>([])
let accountsLoaded = false

async function ensureAccountsLoaded(): Promise<void> {
  if (accountsLoaded) return
  accountsLoaded = true
  try {
    const data = await accountApi.list({})
    accountOptions.value = data.items ?? []
  } catch {
    // 账号列表加载失败 — 不阻断发送, 仅禁用账号绑定
    accountOptions.value = []
  }
}

watch(
  () => props.defaultChannel,
  (v) => {
    if (v && MESSAGE_CHANNELS.includes(v as never)) channel.value = v
  },
)

const channelOptions = MESSAGE_CHANNELS.map((c) => ({
  value: c,
  label: CHANNEL_LABELS[c] ?? c,
}))

const channelLabel = computed(
  () => CHANNEL_LABELS[channel.value] ?? channel.value,
)

const accountName = computed(() => {
  const a = accountOptions.value.find((x) => x.id === accountId.value)
  return a ? `${a.name} (${a.status})` : accountId.value
})

const canSend = computed(
  () => text.value.trim().length > 0 && !props.sending,
)

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (canSend.value) void doSend()
  }
}

async function doSend(): Promise<void> {
  if (!canSend.value) return
  const body = text.value.trim()
  if (!body) return
  text.value = ''
  if (!accountsLoaded && channel.value !== 'web') void ensureAccountsLoaded()
  try {
    await props.send(body, {
      channel: channel.value,
      accountId: accountId.value || undefined,
    })
  } catch {
    // 错误由父级 store.sendError 呈现; 恢复输入文本以便重试
    text.value = body
    return
  }
  textareaRef.value?.focus()
}

function onClearError(): void {
  emit('clear-error')
}

// 首次渲染预载账号 (非阻塞)
void ensureAccountsLoaded()
</script>

<style scoped>
.cmcom {
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-primary);
  padding: var(--spacing-3) var(--spacing-4);
}

/* 错误横幅 */
.cmcom__error {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-3);
  border-radius: var(--radius-md);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: var(--font-size-xs);
}

/* 高级选项 */
.cmcom__options {
  margin-bottom: var(--spacing-2);
}

.cmcom__summary {
  cursor: pointer;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  user-select: none;
  list-style: none;
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.cmcom__summary::-webkit-details-marker {
  display: none;
}

.cmcom__options[open] .cmcom__summary::before {
  content: '▸ ';
}

.cmcom__summary:not([open])::before {
  content: '▸ ';
}

.cmcom__account-name {
  margin-left: auto;
  color: var(--color-text-secondary);
}

.cmcom__options-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-3);
  margin-top: var(--spacing-2);
}

.cmcom__field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.cmcom__label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

/* 输入区 */
.cmcom__input-row {
  display: flex;
  align-items: flex-end;
  gap: var(--spacing-2);
}

.cmcom__textarea {
  flex: 1;
  padding: var(--spacing-2) var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-family: inherit;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  resize: vertical;
  min-height: 56px;
  transition: border-color var(--transition-fast);
}

.cmcom__textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.cmcom__hint {
  margin: var(--spacing-2) 0 0;
  font-size: 11px;
  color: var(--color-text-muted);
}

.cmcom__hint code {
  padding: 0 3px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-tertiary);
  font-size: 10px;
}
</style>
