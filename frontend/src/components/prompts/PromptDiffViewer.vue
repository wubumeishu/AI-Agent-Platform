<template>
  <div class="diff-viewer">
    <div v-if="!lines || lines.length === 0" class="diff-viewer__empty">
      两个版本内容一致，无差异
    </div>
    <div v-else-if="summaryEmpty" class="diff-viewer__summary diff-viewer__summary--empty">
      ✓ 内容一致（{{ lines.length }} 行）
    </div>
    <div v-else class="diff-viewer__summary">
      <span class="diff-chip diff-chip--added">+ {{ stats.added }}</span>
      <span class="diff-chip diff-chip--removed">- {{ stats.removed }}</span>
      <span class="diff-chip diff-chip--modified">~ {{ stats.modified }}</span>
    </div>

    <div class="diff-viewer__list">
      <div
        v-for="line in lines"
        :key="`${line.oldLine ?? 0}-${line.newLine ?? 0}-${line.type}`"
        class="diff-line"
        :class="`diff-line--${line.type}`"
      >
        <span class="diff-line__oldno">{{ line.oldLine ?? ' ' }}</span>
        <span class="diff-line__newno">{{ line.newLine ?? ' ' }}</span>
        <span class="diff-line__mark">
          {{ line.type === 'added' ? '+' : line.type === 'removed' ? '-' : line.type === 'modified' ? '~' : ' ' }}
        </span>
        <pre class="diff-line__content" v-if="line.type === 'removed'">{{ line.oldContent }}</pre>
        <pre class="diff-line__content" v-else-if="line.type === 'added'">{{ line.newContent }}</pre>
        <div v-else class="diff-line__content-pair">
          <pre v-if="line.type === 'modified'" class="diff-line__content diff-line__content--old">{{ line.oldContent }}</pre>
          <pre v-else class="diff-line__content">{{ line.newContent }}</pre>
          <pre v-if="line.type === 'modified'" class="diff-line__content diff-line__content--new">{{ line.newContent }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DiffLine } from '@/api/types'

const props = defineProps<{
  lines?: DiffLine[] | null
}>()

const lines = computed(() => props.lines ?? [])
const summaryEmpty = computed(() => lines.value.every((l) => l.type === 'unchanged'))

const stats = computed(() => {
  let added = 0
  let removed = 0
  let modified = 0
  for (const l of lines.value) {
    if (l.type === 'added') added++
    else if (l.type === 'removed') removed++
    else if (l.type === 'modified') modified++
  }
  return { added, removed, modified }
})
</script>

<style scoped>
.diff-viewer {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.diff-viewer__empty,
.diff-viewer__summary {
  padding: var(--spacing-3) var(--spacing-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
}

.diff-viewer__summary {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
  border-bottom: 1px solid var(--color-border);
}

.diff-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
}

.diff-chip--added { background: var(--color-success-light); color: var(--color-success); }
.diff-chip--removed { background: var(--color-error-light); color: var(--color-error); }
.diff-chip--modified { background: var(--color-warning-light); color: var(--color-warning); }

.diff-viewer__list {
  max-height: 320px;
  overflow-y: auto;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
}

.diff-line {
  display: flex;
  align-items: stretch;
  min-height: 48px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-bg-primary);
}

.diff-line:last-child {
  border-bottom: none;
}

/* 差异高亮：新增绿底，删除红底，修改黄底 */
.diff-line--added { background: var(--color-success-light); }
.diff-line--removed { background: var(--color-error-light); }
.diff-line--modified { background: var(--color-warning-light); }

.diff-line__oldno,
.diff-line__newno {
  flex: 0 0 44px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 4px 6px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  user-select: none;
}

.diff-line__mark {
  flex: 0 0 24px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 4px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
  user-select: none;
}

.diff-line--added .diff-line__mark { color: var(--color-success); }
.diff-line--removed .diff-line__mark { color: var(--color-error); }
.diff-line--modified .diff-line__mark { color: var(--color-warning); }

.diff-line__content {
  flex: 1;
  margin: 0;
  padding: 4px 10px;
  font-size: 13px;
  line-height: 20px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}

.diff-line--removed .diff-line__content {
  text-decoration: line-through;
  opacity: 0.85;
}

.diff-line__content--old {
  text-decoration: line-through;
  opacity: 0.85;
}

.diff-line__content--new {
  text-decoration: none;
  opacity: 1;
}
</style>
