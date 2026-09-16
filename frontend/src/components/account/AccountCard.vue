<template>
  <div class="account-card" @click="$emit('click')">
    <div class="account-card__header">
      <div class="account-card__platform">
        <span class="platform-icon">{{ getPlatformIcon(account.platform_id) }}</span>
        <span class="platform-name">{{ getPlatformName(account.platform_id) }}</span>
      </div>
      <StatusBadge :status="account.status as any" />
    </div>
    <div class="account-card__content">
      <h3 class="account-card__name">{{ account.name }}</h3>
      <p v-if="account.username" class="account-card__username">@{{ account.username }}</p>
    </div>
    <div class="account-card__footer">
      <button
        class="btn btn--ghost btn--sm"
        @click.stop="$emit('test')"
      >
        测试连接
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Account } from '@/api/types'
import StatusBadge from '../common/StatusBadge.vue'

defineProps<{
  account: Account
}>()

defineEmits<{
  (e: 'click'): void
  (e: 'test'): void
}>()

const platformMap: Record<string, { name: string; icon: string }> = {
  wechat: { name: '微信', icon: '💬' },
  douyin: { name: '抖音', icon: '🎵' },
  weibo: { name: '微博', icon: '📢' },
  xiaohongshu: { name: '小红书', icon: '📕' },
}

function getPlatformIcon(platformId: string) {
  return platformMap[platformId]?.icon || '📱'
}

function getPlatformName(platformId: string) {
  return platformMap[platformId]?.name || platformId
}
</script>

<style scoped>
.account-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.account-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.account-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.account-card__platform {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.platform-icon {
  font-size: 24px;
}

.platform-name {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.account-card__content {
  margin-bottom: var(--spacing-3);
}

.account-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.account-card__username {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin: 0;
}

.account-card__footer {
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
