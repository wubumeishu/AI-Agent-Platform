<template>
  <div class="page-header">
    <div class="page-header__left">
      <button v-if="showBack" class="page-header__back" @click="goBack">
        ← 返回
      </button>
      <h1 class="page-header__title">{{ title }}</h1>
    </div>
    <div class="page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

defineProps<{
  title: string
  showBack?: boolean
}>()

const router = useRouter()

const goBack = () => {
  router.back()
}
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-6);
}

.page-header__left {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.page-header__back {
  display: flex;
  align-items: center;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--font-size-sm);
  transition: all var(--transition-fast);
}

.page-header__back:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.page-header__title {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.page-header__actions {
  display: flex;
  gap: var(--spacing-2);
}
</style>
