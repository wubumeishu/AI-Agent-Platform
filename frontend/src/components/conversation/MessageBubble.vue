<template>
  <div
    class="msg-bubble"
    :class="[`msg-bubble--${role}`, { 'msg-bubble--interrupted': interrupted }]"
  >
    <!-- 系统消息：顶部通栏特殊样式 -->
    <div v-if="role === 'system'" class="msg-bubble__system">
      <span class="msg-bubble__system-icon">⚙️</span>
      <span class="msg-bubble__content">{{ content }}</span>
      <span class="msg-bubble__system-time">{{ displayTime }}</span>
    </div>

    <!-- 用户 / AI 消息 -->
    <template v-else>
      <div class="msg-bubble__head">
        <span class="msg-bubble__avatar" :aria-hidden="true">
          {{ role === 'user' ? '我' : 'AI' }}
        </span>
        <span class="msg-bubble__role">{{ role === 'user' ? '我' : 'AI 助手' }}</span>
        <span v-if="streaming" class="msg-bubble__typing" role="status" aria-live="polite">
          <span class="msg-bubble__dot"></span>
          <span class="msg-bubble__dot"></span>
          <span class="msg-bubble__dot"></span>
          <span class="msg-bubble__typing-label">正在输入</span>
        </span>
        <span v-else-if="interrupted" class="msg-bubble__interrupted-tag">已中断</span>
      </div>

      <div class="msg-bubble__body">
        <p
          v-if="content"
          class="msg-bubble__content"
          :class="{ 'msg-bubble__content--typing': streaming }"
        >
          {{ content }}<span
            v-if="streaming"
            class="msg-bubble__cursor"
            aria-hidden="true"
          ></span>
        </p>
        <p
          v-else-if="streaming"
          class="msg-bubble__content msg-bubble__content--placeholder"
        >
          AI 正在思考<span class="msg-bubble__cursor"></span>
        </p>
      </div>

      <div class="msg-bubble__meta">
        <span class="msg-bubble__time">{{ displayTime }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    role: 'user' | 'assistant' | 'system'
    content: string
    createdAt: string
    /** 流式生成中（最后一条 assistant 气泡）：显示打字机光标与「正在输入」指示 */
    streaming?: boolean
    /** 已中断的流式消息（占位 tmp- 消息残留） */
    interrupted?: boolean
  }>(),
  {
    streaming: false,
    interrupted: false,
  }
)

const displayTime = computed(() => formatTime(props.createdAt))

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
</script>

<style scoped>
/* 通用 */
.msg-bubble {
  max-width: 72%;
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  background: var(--color-bg-secondary);
  padding: 10px 14px;
  animation: msg-bubble-in 200ms ease;
}

@keyframes msg-bubble-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.msg-bubble__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  margin-bottom: 6px;
}

.msg-bubble__avatar {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  font-size: 10px;
  font-weight: var(--font-weight-semibold);
  color: #fff;
  background: var(--color-primary);
}

.msg-bubble__role {
  font-size: 11px;
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
}

.msg-bubble__body {
  min-width: 0;
}

.msg-bubble__content {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-bubble__meta {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}

.msg-bubble__time {
  font-size: 10px;
  color: var(--color-text-muted);
}

/* 用户消息：右侧，主色调背景 */
.msg-bubble--user {
  align-self: flex-end;
  background: var(--color-primary-light);
  border-color: color-mix(in srgb, var(--color-primary) 25%, transparent);
}

.msg-bubble--user .msg-bubble__avatar {
  background: var(--color-primary-dark, var(--color-primary));
}

.msg-bubble--user .msg-bubble__head,
.msg-bubble--user .msg-bubble__meta {
  justify-content: flex-end;
}

/* AI 消息：左侧，灰色背景 */
.msg-bubble--assistant {
  align-self: flex-start;
  background: var(--color-bg-secondary);
}

/* 系统消息：顶部通栏特殊样式 */
.msg-bubble--system {
  align-self: center;
  max-width: 90%;
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  background: transparent;
  border: 1px dashed var(--color-border);
  font-size: 12px;
  color: var(--color-text-muted);
}

.msg-bubble__system-icon {
  font-size: 13px;
}

.msg-bubble__system .msg-bubble__content {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.msg-bubble__system-time {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--color-text-muted);
}

/* 流式打字机光标 */
.msg-bubble__cursor {
  display: inline-block;
  width: 2px;
  height: 1em;
  margin-left: 2px;
  vertical-align: -0.15em;
  background: var(--color-primary);
  animation: msg-cursor-blink 900ms steps(1) infinite;
}

@keyframes msg-cursor-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

/* 「正在输入」三点跳动指示 */
.msg-bubble__typing {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--color-text-muted);
}

.msg-bubble__typing-label {
  margin-left: 2px;
}

.msg-bubble__dot {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--color-text-muted);
  animation: msg-dot-bounce 1.2s ease-in-out infinite;
}

.msg-bubble__dot:nth-child(2) {
  animation-delay: 0.15s;
}

.msg-bubble__dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes msg-dot-bounce {
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

/* 已中断标记 */
.msg-bubble--interrupted {
  border-color: color-mix(in srgb, var(--color-danger, #EF4444) 40%, transparent);
}

.msg-bubble__interrupted-tag {
  font-size: 10px;
  color: var(--color-danger, #EF4444);
  background: color-mix(in srgb, var(--color-danger, #EF4444) 10%, transparent);
  border-radius: var(--radius-full);
  padding: 1px 6px;
}

/* 减少动效偏好：关闭光标闪烁与三点跳动 */
@media (prefers-reduced-motion: reduce) {
  .msg-bubble {
    animation: none;
  }
  .msg-bubble__cursor,
  .msg-bubble__dot {
    animation: none;
  }
}
</style>
