<template>
  <div
    class="pt-card"
    :class="{ 'pt-card--archived': isArchived, 'pt-card--acting': actingId === item.id }"
  >
    <!-- 卡片主体 -->
    <div class="pt-card__body">
      <!-- 标题 + 状态 -->
      <div class="pt-card__top">
        <div class="pt-card__title-wrap">
          <h3 class="pt-card__title" :title="item.name">{{ item.name }}</h3>
          <span class="pt-card__version">v{{ item.version }}</span>
        </div>
        <span
          class="pt-card__status"
          :class="isArchived ? 'pt-card__status--archived' : 'pt-card__status--active'"
        >
          <span class="pt-card__status-dot"></span>
          {{ isArchived ? '已归档' : '已启用' }}
        </span>
      </div>

      <!-- 描述 -->
      <p v-if="item.description" class="pt-card__desc" :title="item.description">
        {{ item.description }}
      </p>

      <!-- 分类标签 -->
      <div class="pt-card__tags">
        <span v-if="typeLabel" class="pt-tag pt-tag--type">{{ typeLabel }}</span>
        <span v-if="categoryLabel" class="pt-tag">{{ categoryLabel }}</span>
      </div>

      <!-- 内容摘要（变量高亮） -->
      <div class="pt-card__content">
        <template v-for="(token, i) in contentTokens" :key="i">
          <span v-if="token.type === 'var'" class="pt-card__var">{{ token.name }}</span>
          <span v-else>{{ token.text }}</span>
        </template>
      </div>

      <!-- 底部：变量数 + 时间 -->
      <div class="pt-card__meta">
        <span class="pt-card__meta-item">
          <span class="pt-card__meta-icon">⚙</span> {{ (item.variables ?? []).length }} 个变量
        </span>
        <span class="pt-card__meta-item">
          <span class="pt-card__meta-icon">🕐</span> {{ formatTime(item.created_at) }}
        </span>
      </div>
    </div>

    <!-- 悬停操作栏（编辑 / 预览 / 删除） -->
    <div class="pt-card__actions">
      <button
        class="pt-card__btn"
        :disabled="acting"
        @click.stop="$emit('edit', item)"
      >
        编辑
      </button>
      <button
        class="pt-card__btn"
        :disabled="acting"
        @click.stop="$emit('preview', item)"
      >
        预览
      </button>
      <button
        class="pt-card__btn pt-card__btn--danger"
        :disabled="acting"
        @click.stop="$emit('delete', item)"
      >
        删除
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PromptTemplateListItem } from '@/api/types'
import {
  TEMPLATE_TYPE_LABELS,
  CATEGORY_LABELS,
} from '@/stores/promptTemplate'

const props = defineProps<{
  item: PromptTemplateListItem
  /** 正在对该卡执行操作时禁用按钮（防重复点击） */
  actingId?: string
}>()

defineEmits<{
  (e: 'edit', item: PromptTemplateListItem): void
  (e: 'preview', item: PromptTemplateListItem): void
  (e: 'delete', item: PromptTemplateListItem): void
}>()

const acting = computed(() => props.actingId === props.item.id)

const isArchived = computed(() => props.item.is_baseline === false)

const typeLabel = computed(
  () => TEMPLATE_TYPE_LABELS[props.item.template_type] ?? props.item.template_type,
)

const categoryLabel = computed(() => {
  const cat = props.item.category
  if (!cat) return ''
  return CATEGORY_LABELS[cat] ?? cat
})

/** 内容摘要：截断 + 变量占位符高亮（与 PromptPreviewDialog 的 token 化逻辑一致） */
const contentTokens = computed(() => {
  const source = (props.item.content ?? '').slice(0, 160)
  const tokens: Array<{ type: 'text' | 'var'; text?: string; name?: string }> = []
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) {
    if (m.index > last) tokens.push({ type: 'text', text: source.slice(last, m.index) })
    tokens.push({ type: 'var', name: m[1] })
    last = m.index + m[0].length
  }
  if (last < source.length) tokens.push({ type: 'text', text: source.slice(last) })
  return tokens
})

function formatTime(iso?: string): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
  } catch {
    return iso
  }
}
</script>

<style scoped>
/* P1-002 列表页专用设计令牌（东方雅致：古铜棕 + 宣纸白 + Noto 字体 + 8px 圆角 + 卡片阴影） */
.pt-card {
  position: relative;
  background: var(--pt-bg-card, #ffffff);
  border: 1px solid var(--pt-border, #e8e2d6);
  border-radius: var(--pt-radius, 8px);
  box-shadow: var(--pt-shadow, 0 4px 12px rgba(0, 0, 0, 0.05));
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  overflow: hidden;
}

.pt-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.09);
}

.pt-card--archived {
  opacity: 0.78;
}

.pt-card--acting {
  pointer-events: none;
  opacity: 0.7;
}

.pt-card__body {
  padding: 18px 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

/* 标题行 */
.pt-card__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.pt-card__title-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.pt-card__title {
  margin: 0;
  font-family: 'Noto Serif SC', 'Noto Sans SC', serif;
  font-size: 16px;
  font-weight: 600;
  color: var(--pt-text, #3a2f2a);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pt-card__version {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--pt-primary, #8d6e63);
  background: var(--pt-primary-light, #f3ece8);
  border-radius: var(--pt-radius, 8px);
  padding: 1px 6px;
}

/* 状态 chip（本地实现，不复用已损坏的全局 StatusBadge） */
.pt-card__status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 500;
  padding: 3px 9px;
  border-radius: 999px;
}

.pt-card__status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.pt-card__status--active {
  color: #15803d;
  background: #dcfce7;
}

.pt-card__status--archived {
  color: #9ca3af;
  background: #f3f4f6;
}

/* 描述 */
.pt-card__desc {
  margin: 0;
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 13px;
  color: var(--pt-text-secondary, #7a6f68);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 标签 */
.pt-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.pt-tag {
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--pt-bg-tertiary, #f7f4ef);
  color: var(--pt-text-secondary, #7a6f68);
  border: 1px solid var(--pt-border, #e8e2d6);
}

.pt-tag--type {
  color: var(--pt-primary, #8d6e63);
  background: var(--pt-primary-light, #f3ece8);
  border-color: #ddc9c0;
}

/* 内容摘要 */
.pt-card__content {
  font-family: 'Noto Sans SC', monospace;
  font-size: 13px;
  color: var(--pt-text, #3a2f2a);
  line-height: 1.6;
  background: var(--pt-bg-secondary, #faf8f4);
  border: 1px solid var(--pt-border, #e8e2d6);
  border-radius: var(--pt-radius, 8px);
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 84px;
  overflow: hidden;
  position: relative;
}

.pt-card__var {
  color: var(--pt-primary, #8d6e63);
  background: var(--pt-primary-light, #f3ece8);
  border-radius: 4px;
  padding: 0 3px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}

/* 底部 meta */
.pt-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.pt-card__meta-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--pt-text-muted, #a89d95);
}

.pt-card__meta-icon {
  font-size: 13px;
}

/* 悬停操作栏：默认隐藏，卡片 hover / focus-within 时浮现 */
.pt-card__actions {
  display: flex;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--pt-border, #e8e2d6);
  background: var(--pt-bg-secondary, #faf8f4);
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.pt-card:hover .pt-card__actions,
.pt-card:focus-within .pt-card__actions {
  opacity: 1;
  transform: translateY(0);
}

.pt-card__btn {
  flex: 1;
  padding: 7px 0;
  font-size: 13px;
  font-family: 'Noto Sans SC', sans-serif;
  color: var(--pt-text, #3a2f2a);
  background: var(--pt-bg-card, #ffffff);
  border: 1px solid var(--pt-border, #e8e2d6);
  border-radius: var(--pt-radius, 8px);
  cursor: pointer;
  transition: all 0.15s ease;
}

.pt-card__btn:hover:not(:disabled) {
  border-color: var(--pt-primary, #8d6e63);
  color: var(--pt-primary, #8d6e63);
  background: var(--pt-primary-light, #f3ece8);
}

.pt-card__btn--danger:hover:not(:disabled) {
  border-color: #dc2626;
  color: #dc2626;
  background: #fee2e2;
}

.pt-card__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 无障碍：键盘 focus 时也显示操作栏 */
.pt-card:focus-visible {
  outline: 2px solid var(--pt-primary, #8d6e63);
  outline-offset: 2px;
}
</style>
