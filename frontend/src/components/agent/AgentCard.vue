<template>
  <div class="agent-card" @click="$emit('click', agent.id)">
    <div class="agent-card__header">
      <div class="agent-card__avatar">
        <span class="avatar-icon">{{ agent.icon || '🤖' }}</span>
      </div>
      <StatusBadge :status="agent.status" />
    </div>
    
    <div class="agent-card__content">
      <h3 class="agent-card__name">{{ agent.name }}</h3>
      <p class="agent-card__desc">{{ agent.description || '暂无描述' }}</p>
      
      <div class="agent-card__meta">
        <span v-if="agent.persona_name" class="agent-card__persona">
          👤 {{ agent.persona_name }}
        </span>
        <span class="agent-card__time">
          {{ formatTime(agent.created_at) }}
        </span>
      </div>
    </div>
    
    <div class="agent-card__actions" @click.stop>
      <button class="btn btn--ghost btn--sm" @click="$emit('start', agent.id)">
        ▶ 启动
      </button>
      <button 
        v-if="agent.status === 'running' || agent.status === 'active'" 
        class="btn btn--ghost btn--sm"
        @click="$emit('stop', agent.id)"
      >
        ⏹ 停止
      </button>
      <button class="btn btn--danger btn--sm" @click="$emit('delete', agent.id)">
        🗑 删除
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Agent } from '@/api/types'
import StatusBadge from '@/components/common/StatusBadge.vue'

defineProps<{
  agent: Agent
}>()

defineEmits<{
  (e: 'click', id: string): void
  (e: 'start', id: string): void
  (e: 'stop', id: string): void
  (e: 'delete', id: string): void
}>()

function formatTime(time: string): string {
  return new Date(time).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.agent-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.agent-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.agent-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-3);
}

.agent-card__avatar {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.agent-card__content {
  margin-bottom: var(--spacing-4);
}

.agent-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.agent-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.agent-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.agent-card__persona {
  color: var(--color-primary);
}

.agent-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
