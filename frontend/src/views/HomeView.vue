<template>
  <div class="home-view">
    <h1>欢迎使用 AI Agent Platform</h1>
    <p class="home-view__subtitle">智能获客与私域运营平台</p>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.home-view {
  max-width: 800px;
  margin: 0 auto;
  padding: var(--spacing-8) var(--spacing-6);
}

.home-view h1 {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.home-view__subtitle {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}
</style>
