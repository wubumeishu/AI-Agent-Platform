<template>
  <div class="settings-view">
    <h2>设置</h2>
    <p class="settings-view__desc">应用基础设置（P0-005 实现）</p>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.settings-view {
  max-width: 600px;
}

.settings-view h2 {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-4);
}

.settings-view__desc {
  color: var(--color-text-secondary);
}
</style>
