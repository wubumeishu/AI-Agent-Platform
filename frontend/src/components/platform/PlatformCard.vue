<template>
  <div class="platform-card">
    <div class="platform-card__header">
      <div class="platform-card__logo">{{ getPlatformLogo(platform.code) }}</div>
      <StatusBadge :status="platform.status === 'active' ? 'success' : 'stopped'" />
    </div>
    <div class="platform-card__content">
      <h3 class="platform-card__name">{{ platform.name }}</h3>
      <p class="platform-card__code">{{ platform.code }}</p>
      <div class="platform-card__capabilities">
        <span
          v-for="cap in platform.capabilities"
          :key="cap"
          class="capability-tag"
        >
          {{ cap }}
        </span>
      </div>
    </div>
    <div class="platform-card__actions">
      <button
        class="btn btn--ghost btn--sm"
        @click="$emit('test', platform.id)"
      >
        测试连接
      </button>
      <button
        class="btn btn--danger btn--sm"
        @click="$emit('delete', platform.id)"
      >
        注销
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Platform } from '@/api/types'
import StatusBadge from '../common/StatusBadge.vue'

defineProps<{
  platform: Platform
}>()

defineEmits<{
  (e: 'test', id: string): void
  (e: 'delete', id: string): void
}>()

const platformLogos: Record<string, string> = {
  wechat: '💬',
  douyin: '🎵',
  weibo: '📢',
  xiaohongshu: '📕',
  qq: '🐧',
}

function getPlatformLogo(code: string) {
  return platformLogos[code] || '🔌'
}
</script>

<style scoped>
.platform-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  transition: all var(--transition-fast);
}

.platform-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.platform-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.platform-card__logo {
  font-size: 40px;
}

.platform-card__content {
  margin-bottom: var(--spacing-4);
}

.platform-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.platform-card__code {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin: 0 0 var(--spacing-2);
}

.platform-card__capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-1);
}

.capability-tag {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
}

.platform-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
