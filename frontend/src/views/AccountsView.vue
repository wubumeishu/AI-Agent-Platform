<template>
  <div class="empty-state">
    <div class="empty-state__icon">👤</div>
    <h2 class="empty-state__title">账号管理</h2>
    <p class="empty-state__desc">管理你的社交账号和代理</p>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  padding: var(--spacing-8);
}

.empty-state__icon {
  font-size: 64px;
  margin-bottom: var(--spacing-4);
}

.empty-state__title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.empty-state__desc {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}
</style>
