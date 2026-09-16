<template>
  <div class="kpi-card" :class="{ 'kpi-card--loading': loading }">
    <div class="kpi-card__icon" v-if="icon">{{ icon }}</div>
    <div class="kpi-card__body">
      <div class="kpi-card__label">{{ label }}</div>
      <div class="kpi-card__value" v-if="!loading && valueText">
        <template v-if="subValue !== null && subValue !== undefined">
          {{ valueText }}<span class="kpi-card__sub">{{ subValue }}</span>
        </template>
        <template v-else>{{ valueText }}</template>
      </div>
      <div class="kpi-card__value kpi-card__value--na" v-else-if="!loading && noData">
        暂无数据
      </div>
      <div class="kpi-card__placeholder" v-else></div>
      <div class="kpi-card__hint" v-if="hint && !loading">{{ hint }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 通用 KPI 指标卡（P6AN-10）。
 *
 * 渲染约定：
 * - loading：占位骨架（不显示 0，避免误读为真实值）
 * - noData：分母为 0 / 无数据 → 显示「暂无数据」
 * - 否则：valueText（主值）+ subValue（可选副值，如比率、环比）
 */
defineProps<{
  label: string
  icon?: string
  /** 主值文本（已格式化，如 '1,204' 或 '38.2%'） */
  valueText: string
  /** 可选副值文本（紧跟主值） */
  subValue?: string | null
  /** 附加说明（如时间窗口） */
  hint?: string
  /** 加载中骨架 */
  loading?: boolean
  /** 无数据标记 */
  noData?: boolean
}>()
</script>

<style scoped>
.kpi-card {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  min-height: 112px;
}

.kpi-card__icon {
  font-size: 28px;
  width: 52px;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-lg);
  flex-shrink: 0;
}

.kpi-card__body {
  flex: 1;
  min-width: 0;
}

.kpi-card__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--spacing-1);
}

.kpi-card__value {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.kpi-card__sub {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  margin-left: var(--spacing-2);
}

.kpi-card__value--na {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
}

.kpi-card__placeholder {
  height: 28px;
  width: 70%;
  background: linear-gradient(
    90deg,
    var(--color-bg-tertiary) 25%,
    var(--color-bg-secondary) 50%,
    var(--color-bg-tertiary) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.2s infinite;
  border-radius: var(--radius-sm);
}

.kpi-card__hint {
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
