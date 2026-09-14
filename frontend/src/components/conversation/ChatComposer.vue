<template>
  <div class="chat-composer" :class="{ 'chat-composer--streaming': streaming }">
    <label class="chat-composer__sr" :for="inputId">消息输入框</label>
    <textarea
      :id="inputId"
      ref="textareaEl"
      v-model="modelText"
      class="chat-composer__input"
      :rows="String(rows)"
      :disabled="disabled"
      :placeholder="placeholder"
      :aria-disabled="disabled"
      @input="autoResize"
      @keydown="onKeydown"
    ></textarea>

    <div class="chat-composer__actions">
      <span v-if="streaming" class="chat-composer__hint" role="status" aria-live="polite">
        AI 正在回复…
      </span>
      <span v-else-if="modelText.trim().length > 0" class="chat-composer__hint">
        {{ modelText.trim().length }} 字
      </span>

      <button
        v-if="streaming"
        class="btn btn--ghost btn--sm chat-composer__interrupt"
        type="button"
        @click="onInterrupt"
      >
        ⏹ 中断生成
      </button>
      <button
        class="btn btn--primary btn--sm chat-composer__send"
        type="button"
        :disabled="sendDisabled"
        :aria-label="'发送消息'"
        @click="onSend"
      >
        发送 <span class="chat-composer__send-key" aria-hidden="true">↵</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    /** 生成中：禁用发送、显示「中断生成」 */
    streaming?: boolean
    /** 外部禁用（如会话未选中） */
    disabled?: boolean
    inputId?: string
    placeholder?: string
    maxLength?: number
  }>(),
  {
    streaming: false,
    disabled: false,
    inputId: 'chat-composer-input',
    placeholder: '输入消息，Enter 发送 · Shift+Enter 换行',
    maxLength: 2000,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'send'): void
  (e: 'interrupt'): void
}>()

const textareaEl = ref<HTMLTextAreaElement | null>(null)
const modelText = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const rows = computed(() => Math.min(6, Math.max(1, modelText.value.split('\n').length)))

const sendDisabled = computed(
  () => props.disabled || modelText.value.trim().length === 0
)

function autoResize() {
  const el = textareaEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function onKeydown(e: KeyboardEvent) {
  // Enter 发送；Shift+Enter 换行（浏览器默认行为）
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    if (!sendDisabled.value) emit('send')
    return
  }
  // Ctrl/Cmd+Enter 兜底快捷发送（Tauri 桌面端）
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    if (!sendDisabled.value) emit('send')
  }
}

function onSend() {
  if (sendDisabled.value || props.streaming) return
  emit('send')
}

function onInterrupt() {
  emit('interrupt')
}

// 自动聚焦 + 内容变化时自适应高度
watch(
  () => props.disabled,
  (disabled) => {
    if (!disabled) {
      nextTick(() => {
        textareaEl.value?.focus()
        autoResize()
      })
    }
  },
  { immediate: true }
)

watch(modelText, autoResize)

defineExpose({
  focus() {
    textareaEl.value?.focus()
  },
})
</script>

<style scoped>
.chat-composer {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.chat-composer__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

.chat-composer__input {
  width: 100%;
  min-height: 44px;
  max-height: 200px;
  resize: none;
  overflow-y: auto;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-family: inherit;
  line-height: 1.6;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.chat-composer__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 15%, transparent);
}

.chat-composer__input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  background: var(--color-bg-tertiary);
}

.chat-composer__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-2);
}

.chat-composer__hint {
  font-size: 11px;
  color: var(--color-text-muted);
}

.chat-composer--streaming .chat-composer__hint {
  color: var(--color-primary);
}

.chat-composer__send {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chat-composer__send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.chat-composer__send-key {
  font-size: 10px;
  opacity: 0.7;
}

.chat-composer__interrupt {
  color: var(--color-warning, #F59E0B);
}
</style>
