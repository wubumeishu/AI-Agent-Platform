<template>
  <div class="proxy-card">
    <div class="proxy-card__left">
      <div class="proxy-card__type">
        <StatusBadge
          :status="(proxy.type === 'http' || proxy.type === 'https' ? 'info' : 'warning') as any"
          :label="proxy.type.toUpperCase()"
        />
      </div>
      <div class="proxy-card__address">
        <span class="proxy-card__host">{{ proxy.host }}</span>
        <span class="proxy-card__port">:{{ proxy.port }}</span>
      </div>
      <div class="proxy-card__name">{{ proxy.name }}</div>
    </div>
    <div class="proxy-card__right">
      <StatusBadge :status="(proxy.status === 'active' ? 'success' : proxy.status === 'failed' ? 'error' : 'stopped') as any" />
      <div class="proxy-card__actions">
        <button
          class="btn btn--ghost btn--sm"
          @click="$emit('test', proxy.id)"
        >
          测试
        </button>
        <button
          class="btn btn--danger btn--sm"
          @click="$emit('delete', proxy.id)"
        >
          删除
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Proxy } from '@/api/types'
import StatusBadge from '../common/StatusBadge.vue'

defineProps<{
  proxy: Proxy
}>()

defineEmits<{
  (e: 'test', id: string): void
  (e: 'delete', id: string): void
}>()
</script>

<style scoped>
.proxy-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4) var(--spacing-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all var(--transition-fast);
}

.proxy-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.proxy-card__left {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.proxy-card__type {
  width: 60px;
}

.proxy-card__address {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.proxy-card__host {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.proxy-card__port {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.proxy-card__name {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.proxy-card__right {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.proxy-card__actions {
  display: flex;
  gap: var(--spacing-2);
}
</style>
