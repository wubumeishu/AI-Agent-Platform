<template>
  <div class="page-container">
    <PageHeader
      title="商机漏斗"
      description="跟踪和管理销售商机，监控转化进度"
      :loading="dealsLoading"
    >
      <template #actions>
        <button class="btn btn--primary" @click="handleCreate">
          + 新建商机
        </button>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="dealsLoading" />

      <EmptyState
        v-else-if="!dealsLoading && dealList.length === 0"
        icon="💼"
        title="暂无商机"
        description="还没有任何商机"
        :show-action="true"
        action-text="创建商机"
        @action="handleCreate"
      />

      <table v-else class="data-table">
        <thead>
          <tr>
            <th class="col-name">商机名称</th>
            <th class="col-stage">状态</th>
            <th class="col-priority">优先级</th>
            <th class="col-value">金额</th>
            <th class="col-date">预计关闭</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="deal in dealList" :key="deal.id">
            <td class="col-name">{{ deal.name }}</td>
            <td class="col-stage">
              <span class="status-badge" :class="getStatusClass(deal.status)">
                {{ getStatusLabel(deal.status) }}
              </span>
            </td>
            <td class="col-priority">
              <span class="priority-badge" :class="getPriorityClass(deal.priority || 'medium')">
                {{ getPriorityLabel(deal.priority || 'medium') }}
              </span>
            </td>
            <td class="col-value">
              <span v-if="deal.value">{{ formatCurrency(deal.value) }}</span>
              <span v-else class="text-muted">-</span>
            </td>
            <td class="col-date">
              <span v-if="deal.expected_close_date">{{ formatDate(deal.expected_close_date) }}</span>
              <span v-else class="text-muted">-</span>
            </td>
            <td class="col-actions">
              <button class="btn btn--ghost btn--sm" @click="handleEdit(deal)">编辑</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(deal)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="dealsTotal > 0" class="pagination">
        <span class="pagination-info">共 {{ dealsTotal }} 条</span>
        <button class="btn btn--ghost" :disabled="currentPage === 1" @click="handlePageChange(currentPage - 1)">
          上一页
        </button>
        <span class="pagination-current">{{ currentPage }}</span>
        <button class="btn btn--ghost" :disabled="currentPage * pageSize >= dealsTotal" @click="handlePageChange(currentPage + 1)">
          下一页
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useDealStore } from '@/stores/deal'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const dealStore = useDealStore()
const { dealList, dealsTotal, dealsLoading } = storeToRefs(dealStore)

const currentPage = ref(1)
const pageSize = ref(10)

onMounted(async () => {
  await fetchDeals()
})

async function fetchDeals() {
  try {
    await dealStore.fetchDeals({
      account_id: '1',
      page: currentPage.value,
      page_size: pageSize.value,
    })
  } catch (error) {
    console.error('Failed to fetch deals:', error)
  }
}

function getStatusLabel(status: string) {
  const labels: Record<string, string> = {
    open: '进行中',
    won: '已成交',
    lost: '已丢失',
    draft: '草稿',
  }
  return labels[status] || status
}

function getStatusClass(status: string) {
  return `status-${status}`
}

function getPriorityLabel(priority: string) {
  const labels: Record<string, string> = {
    low: '低',
    medium: '中',
    high: '高',
    urgent: '紧急',
  }
  return labels[priority] || priority
}

function getPriorityClass(priority: string) {
  return `priority-${priority}`
}

function formatDate(dateStr: string) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

function formatCurrency(value: number) {
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function handleCreate() {
  alert('创建商机功能待实现')
}

function handleEdit(deal: any) {
  alert(`编辑商机: ${deal.name}`)
}

async function handleDelete(deal: any) {
  if (!confirm(`确定要删除商机「${deal.name}」吗？`)) {
    return
  }
  try {
    await dealStore.deleteDeal(deal.id)
    await fetchDeals()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  fetchDeals()
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

.col-stage {
  width: 100px;
}

.col-priority {
  width: 100px;
}

.col-value {
  width: 120px;
}

.col-date {
  width: 120px;
}

.col-actions {
  width: 150px;
  text-align: right;
}

.status-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.status-open {
  background: #dbeafe;
  color: #1e40af;
}

.status-won {
  background: #dcfce7;
  color: #166534;
}

.status-lost {
  background: #fee2e2;
  color: #991b1b;
}

.status-draft {
  background: #f3f4f6;
  color: #374151;
}

.priority-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.priority-low {
  background: #f3f4f6;
  color: #374151;
}

.priority-medium {
  background: #dbeafe;
  color: #1e40af;
}

.priority-high {
  background: #fef9c3;
  color: #854d0e;
}

.priority-urgent {
  background: #fee2e2;
  color: #991b1b;
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
