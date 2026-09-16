<template>
  <div class="error-banner" role="alert">
    <span class="error-banner__icon">⚠️</span>
    <div class="error-banner__body">
      <div class="error-banner__title">数据加载失败</div>
      <div class="error-banner__message">{{ message }}</div>
    </div>
    <button v-if="retryable" class="error-banner__retry btn btn--ghost btn--sm" @click="$emit('retry')">
      重试
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * Analytics 错误条（P6AN-10）。
 * 顶部内联错误（保留旧数据降级展示）；retryable 时显示重试按钮。
 */
defineProps<{
  message: string
  retryable?: boolean
}>()

defineEmits<{
  (e: 'retry'): void
}>()
</script>

<style scoped>
.error-banner {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  padding: var(--spacing-3) var(--spacing-4);
  margin-bottom: var(--spacing-4);
}

.error-banner__icon {
  font-size: var(--font-size-lg);
}

.error-banner__body {
  flex: 1;
  min-width: 0;
}

.error-banner__title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.error-banner__message {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
