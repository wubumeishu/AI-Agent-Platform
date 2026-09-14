<template>
  <div class="filter-bar">
    <div class="filter-bar__group">
      <label class="filter-bar__label">时间窗口</label>
      <select
        class="filter-bar__select"
        :value="options.days"
        @change="onDaysChange"
      >
        <option v-for="d in dayOptions" :key="d" :value="d">{{ d }} 天</option>
      </select>
    </div>

    <div class="filter-bar__group">
      <label class="filter-bar__label">Agent</label>
      <select
        class="filter-bar__select"
        :value="options.agentId ?? ''"
        :disabled="!options.agentsLoaded && agentStore.agents.length === 0"
        @change="onAgentChange"
      >
        <option value="">全部 Agent</option>
        <option v-for="a in agentStore.agents" :key="a.id" :value="a.id">
          {{ a.name }}
        </option>
      </select>
    </div>

    <div class="filter-bar__group">
      <label class="filter-bar__label">渠道</label>
      <select
        class="filter-bar__select"
        :value="options.channel ?? ''"
        @change="onChannelChange"
      >
        <option value="">全部渠道</option>
        <option v-for="ch in options.channelOptions" :key="ch" :value="ch">
          {{ ch }}
        </option>
      </select>
    </div>

    <div class="filter-bar__group filter-bar__group--actions">
      <button
        v-if="options.filterActive || options.days !== 30"
        class="btn btn--ghost btn--sm"
        @click="onReset"
      >
        重置
      </button>
      <button class="btn btn--primary btn--sm" @click="$emit('apply')">
        应用筛选
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Analytics 共享过滤条（P6AN-10）。
 *
 * 直接读写 analyticsOptions store（时间窗口 / Agent / 渠道），视图不传 props。
 * 变更本地即时反映；「应用筛选」emit apply，由视图调用 store.refresh() 触发重取。
 */
import { onMounted } from 'vue'
import { useAnalyticsOptionsStore } from '@/stores/analyticsOptions'
import { useAgentStore } from '@/stores/agent'

defineEmits<{
  (e: 'apply'): void
}>()

const options = useAnalyticsOptionsStore()
const agentStore = useAgentStore()

const dayOptions = [7, 14, 30, 90, 180, 365]

onMounted(() => {
  void options.loadAgents()
})

function onDaysChange(e: Event) {
  options.days = Number((e.target as HTMLSelectElement).value)
}

function onAgentChange(e: Event) {
  options.setAgent((e.target as HTMLSelectElement).value || null)
}

function onChannelChange(e: Event) {
  options.setChannel((e.target as HTMLSelectElement).value || null)
}

function onReset() {
  options.reset()
}
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: flex-end;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin-bottom: var(--spacing-5);
}

.filter-bar__group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.filter-bar__group--actions {
  flex-direction: row;
  align-items: center;
  gap: var(--spacing-2);
  margin-left: auto;
}

.filter-bar__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
}

.filter-bar__select {
  min-width: 140px;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.filter-bar__select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.filter-bar__select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
