<template>
  <div class="status-badge" :class="`status-badge--${status}`">
    <span class="status-badge__dot"></span>
    <span>{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: 'success' | 'warning' | 'error' | 'info' | 'running' | 'stopped' | 'connected' | 'disconnected' | 'failed'
  label?: string
}>()

const label = computed(() => {
  if (props.label) return props.label
  const map: Record<string, string> = {
    success: '成功',
    warning: '警告',
    error: '错误',
    info: '信息',
    running: '运行中',
    stopped: '已停止',
    connected: '已连接',
    disconnected: '未连接',
    failed: '失败',
  }
  return map[props.status] || props.status
})
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-1);
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.status-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-badge--success {
  color: var(--color-success);
  background: var(--color-success-light);
}

.status-badge--warning {
  color: var(--color-warning);
  background: var(--color-warning-light);
}

.status-badge--error {
  color: var(--color-error);
  background: var(--color-error-light);
}

.status-badge--info {
  color: var(--color-info);
  background: var(--color-info-light);
}

.status-badge--running {
  color: var(--color-success);
  background: var(--color-success-light);
}

.status-badge--stopped {
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
}

.status-badge--connected {
  color: var(--color-success);
  background: var(--color-success-light);
}

.status-badge--disconnected {
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
}

.status-badge--failed {
  color: var(--color-error);
  background: var(--color-error-light);
}
</style>
