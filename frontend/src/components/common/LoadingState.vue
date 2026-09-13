<template>
  <div class="loading-state" :class="{ 'loading-state--full': fullScreen }">
    <div class="loading-state__spinner"></div>
    <p class="loading-state__text">{{ text || '加载中...' }}</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  text?: string
  fullScreen?: boolean
}>()
</script>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-8);
  color: var(--color-text-secondary);
}

.loading-state--full {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--color-bg-secondary);
  z-index: 1000;
}

.loading-state__spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: var(--spacing-3);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-state__text {
  font-size: var(--font-size-sm);
}
</style>
