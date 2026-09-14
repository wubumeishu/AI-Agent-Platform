<template>
  <div class="persona-card" @click="$emit('click', persona.id)">
    <div class="persona-card__header">
      <div class="persona-card__icon">
        <span class="icon">{{ persona.icon || '🎭' }}</span>
      </div>
      <span class="persona-card__version">v{{ persona.version }}</span>
    </div>
    
    <div class="persona-card__content">
      <h3 class="persona-card__name">{{ persona.name }}</h3>
      <p class="persona-card__desc">{{ persona.description || '暂无描述' }}</p>
      
      <div class="persona-card__preview">
        <span class="preview-tag" :class="`preview-tag--${persona.personality.tone}`">
          {{ toneLabel(persona.personality.tone) }}
        </span>
        <span class="preview-tag" :class="`preview-tag--${persona.personality.reply_length}`">
          {{ lengthLabel(persona.personality.reply_length) }}
        </span>
        <span class="preview-tag" :class="`preview-tag--${persona.personality.proactiveness}`">
          {{ proactivenessLabel(persona.personality.proactiveness) }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Persona } from '@/api/types'

defineProps<{
  persona: Persona
}>()

defineEmits<{
  (e: 'click', id: string): void
}>()

function toneLabel(tone: string): string {
  const map: Record<string, string> = {
    professional: '专业',
    friendly: '友好',
    casual: '随意',
  }
  return map[tone] || tone
}

function lengthLabel(length: string): string {
  const map: Record<string, string> = {
    concise: '简洁',
    balanced: '适中',
    detailed: '详细',
  }
  return map[length] || length
}

function proactivenessLabel(level: string): string {
  const map: Record<string, string> = {
    low: '低主动',
    medium: '中主动',
    high: '高主动',
  }
  return map[level] || level
}
</script>

<style scoped>
.persona-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.persona-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.persona-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-3);
}

.persona-card__icon {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.persona-card__version {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
}

.persona-card__content {
  margin-bottom: var(--spacing-3);
}

.persona-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.persona-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.persona-card__preview {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.preview-tag {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
}

.preview-tag--professional {
  background: var(--color-info-light);
  color: var(--color-info);
}

.preview-tag--friendly {
  background: var(--color-success-light);
  color: var(--color-success);
}

.preview-tag--casual {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.preview-tag--concise {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.preview-tag--balanced {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.preview-tag--detailed {
  background: var(--color-info-light);
  color: var(--color-info);
}

.preview-tag--low {
  background: var(--color-bg-tertiary);
  color: var(--color-text-muted);
}

.preview-tag--medium {
  background: var(--color-warning-light);
  color: var(--color-warning);
}

.preview-tag--high {
  background: var(--color-success-light);
  color: var(--color-success);
}
</style>
