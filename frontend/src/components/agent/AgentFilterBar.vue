<template>
  <div class="agent-filter-bar">
    <div class="filter-bar__search">
      <span class="filter-bar__search-icon">🔍</span>
      <input
        v-model="searchQuery"
        type="text"
        class="form-input form-input--sm"
        placeholder="搜索 Agent 名称..."
        @input="onSearch"
      />
    </div>
    
    <div class="filter-bar__status">
      <select 
        v-model="statusFilter" 
        class="form-select form-select--sm"
        @change="onFilter"
      >
        <option value="">全部状态</option>
        <option value="running">运行中</option>
        <option value="stopped">已停止</option>
        <option value="error">错误</option>
      </select>
    </div>
    
    <div class="filter-bar__sort">
      <select 
        v-model="sortField" 
        class="form-select form-select--sm"
        @change="onSort"
      >
        <option value="created_at">创建时间</option>
        <option value="name">名称</option>
        <option value="status">状态</option>
      </select>
      <button 
        class="btn btn--ghost btn--sm"
        @click="toggleSortOrder"
      >
        {{ sortOrder === 'asc' ? '↑' : '↓' }}
      </button>
    </div>
    
    <div class="filter-bar__stats">
      <span class="stats-text">共 {{ total }} 个 Agent</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{
  (e: 'search', query: string): void
  (e: 'filter', filter: { status: string }): void
  (e: 'sort', sort: { field: string; order: 'asc' | 'desc' }): void
}>()

defineProps<{
  total?: number
}>()

const searchQuery = ref('')
const statusFilter = ref('')
const sortField = ref('created_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

function onSearch(): void {
  emit('search', searchQuery.value)
}

function onFilter(): void {
  emit('filter', { status: statusFilter.value })
}

function onSort(): void {
  emit('sort', { field: sortField.value, order: sortOrder.value })
}

function toggleSortOrder(): void {
  sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
  emit('sort', { field: sortField.value, order: sortOrder.value })
}
</script>

<style scoped>
.agent-filter-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) 0;
  margin-bottom: var(--spacing-4);
  flex-wrap: wrap;
}

.filter-bar__search {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.filter-bar__search-icon {
  position: absolute;
  left: var(--spacing-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--font-size-sm);
}

.filter-bar__search input {
  padding-left: calc(var(--spacing-3) * 2);
}

.filter-bar__status,
.filter-bar__sort {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.filter-bar__stats {
  margin-left: auto;
}

.stats-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
</style>
