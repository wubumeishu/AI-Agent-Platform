<template>
  <div class="not-found">
    <div class="not-found__icon">🔍</div>
    <h1 class="not-found__title">404</h1>
    <p class="not-found__desc">页面未找到</p>
    <router-link to="/" class="not-found__link">返回首页</router-link>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  padding: var(--spacing-8);
}

.not-found__icon {
  font-size: 64px;
  margin-bottom: var(--spacing-4);
}

.not-found__title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.not-found__desc {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-6);
}

.not-found__link {
  display: inline-block;
  padding: var(--spacing-2) var(--spacing-6);
  background: var(--color-primary);
  color: white;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-medium);
  transition: background var(--transition-fast);
}

.not-found__link:hover {
  background: var(--color-primary-hover);
  text-decoration: none;
  color: white;
}
</style>
