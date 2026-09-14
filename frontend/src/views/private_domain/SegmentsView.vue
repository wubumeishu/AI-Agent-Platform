<template>
  <div class="page-container">
    <PageHeader
      title="客户群管理"
      description="管理和细分客户群体，用于精准营销"
      :loading="loading"
    >
      <template #actions>
        <button class="btn btn--primary" @click="handleCreate">
          + 新建客户群
        </button>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="loading" />

      <EmptyState
        v-else-if="!loading && segmentList.length === 0"
        icon="👥"
        title="暂无客户群"
        description="还没有任何客户群"
        :show-action="true"
        action-text="创建客户群"
        @action="handleCreate"
      />

      <table v-else class="data-table">
        <thead>
          <tr>
            <th class="col-name">群名称</th>
            <th class="col-type">类型</th>
            <th class="col-count">成员数</th>
            <th class="col-desc">描述</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="segment in segmentList" :key="segment.id">
            <td class="col-name">{{ segment.name }}</td>
            <td class="col-type">
              <span class="type-badge" :class="getTypeClass(segment.segment_type)">
                {{ getTypeLabel(segment.segment_type) }}
              </span>
            </td>
            <td class="col-count">{{ segment.member_count }}</td>
            <td class="col-desc text-muted">{{ segment.description || '-' }}</td>
            <td class="col-actions">
              <button class="btn btn--ghost btn--sm" @click="handleEdit(segment)">编辑</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(segment)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="total > 0" class="pagination">
        <span class="pagination-info">共 {{ total }} 条</span>
        <button class="btn btn--ghost" :disabled="currentPage === 1" @click="handlePageChange(currentPage - 1)">
          上一页
        </button>
        <span class="pagination-current">{{ currentPage }}</span>
        <button class="btn btn--ghost" :disabled="currentPage * pageSize >= total" @click="handlePageChange(currentPage + 1)">
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useSegmentStore } from '@/stores/segment'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const segmentStore = useSegmentStore()
const { segmentList, total, loading } = storeToRefs(segmentStore)

const currentPage = ref(1)
const pageSize = ref(10)

onMounted(async () => {
  await fetchSegments()
})

async function fetchSegments() {
  try {
    await segmentStore.fetchSegments({
      account_id: '1',
      page: currentPage.value,
      page_size: pageSize.value,
    })
  } catch (error) {
    console.error('Failed to fetch segments:', error)
  }
}

function getTypeLabel(type: string) {
  const labels: Record<string, string> = {
    manual: '手动',
    automatic: '自动',
    dynamic: '动态',
  }
  return labels[type] || type
}

function getTypeClass(type: string) {
  return `type-${type}`
}

function handleCreate() {
  alert('创建客户群功能待实现')
}

function handleEdit(segment: any) {
  alert(`编辑客户群: ${segment.name}`)
}

async function handleDelete(segment: any) {
  if (!confirm(`确定要删除客户群「${segment.name}」吗？`)) {
    return
  }
  try {
    await segmentStore.deleteSegment(segment.id)
    await fetchSegments()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  fetchSegments()
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-content {
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  padding: 24px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
}

.data-table tbody tr:hover {
  background: var(--color-bg-tertiary);
}

.col-name {
  width: 200px;
}

.col-type {
  width: 100px;
}

.col-count {
  width: 100px;
}

.col-desc {
  width: 250px;
}

.col-actions {
  width: 150px;
  text-align: right;
}

.type-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.type-manual {
  background: #f3f4f6;
  color: #374151;
}

.type-automatic {
  background: #dbeafe;
  color: #1e40af;
}

.type-dynamic {
  background: #dcfce7;
  color: #166534;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.pagination-info {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.pagination-current {
  padding: 4px 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  border-radius: 4px;
  font-weight: 500;
}
</style>
