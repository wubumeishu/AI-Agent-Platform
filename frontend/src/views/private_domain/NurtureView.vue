<template>
  <div class="page-container">
    <PageHeader
      title="培育计划"
      description="创建和管理客户培育自动化流程"
      :loading="loading"
    >
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建培育计划
        </button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="filters-bar">
      <div class="filters-bar__left">
        <select v-model="filterStatus" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="active">运行中</option>
          <option value="paused">已暂停</option>
          <option value="completed">已完成</option>
          <option value="archived">已归档</option>
        </select>
        <select v-model="filterChannelId" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部渠道</option>
          <option v-for="ch in channels" :key="ch.id" :value="ch.id">
            {{ ch.name }}
          </option>
        </select>
      </div>
      <div class="filters-bar__right">
        <span class="text-muted">{{ filteredPlans.length }} 个培育计划</span>
      </div>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading" />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && filteredPlans.length === 0"
      icon="🌱"
      title="暂无培育计划"
      description="还没有任何培育计划，点击创建第一个培育计划"
      :show-action="true"
      action-text="创建培育计划"
      @action="showCreateDialog = true"
    />

    <!-- Nurture Plan List -->
    <div v-else class="nurture-list">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-name">计划名称</th>
            <th class="col-channel">关联渠道</th>
            <th class="col-schedule">触发方式</th>
            <th class="col-status">状态</th>
            <th class="col-steps">步骤数</th>
            <th class="col-created">创建时间</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="plan in filteredPlans" :key="plan.id">
            <td class="col-name">
              <router-link :to="`/private-domain/nurture/${plan.id}`" class="plan-link">
                {{ plan.name }}
              </router-link>
            </td>
            <td class="col-channel">
              <span class="text-muted">{{ getChannelName(plan.channel_id) }}</span>
            </td>
            <td class="col-schedule">
              <span class="schedule-badge">{{ getScheduleLabel(plan.schedule_type) }}</span>
            </td>
            <td class="col-status">
              <StatusBadge :status="plan.status" :label="getStatusLabel(plan.status)" />
            </td>
            <td class="col-steps">{{ plan.sequence_steps?.length || 0 }}</td>
            <td class="col-created">{{ formatDate(plan.created_at) }}</td>
            <td class="col-actions">
              <button class="btn btn--ghost btn--sm" @click="handleView(plan)">查看</button>
              <button class="btn btn--ghost btn--sm" @click="handleEdit(plan)">编辑</button>
              <button
                v-if="plan.status !== 'active'"
                class="btn btn--success btn--sm"
                @click="handleStart(plan)"
              >启动</button>
              <button
                v-else
                class="btn btn--warning btn--sm"
                @click="handlePause(plan)"
              >暂停</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(plan)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
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

    <!-- Create Dialog -->
    <Modal v-if="showCreateDialog" title="新建培育计划" @close="showCreateDialog = false">
      <NurturePlanCreateDialog
        :channels="channels"
        @submit="handleCreate"
        @cancel="showCreateDialog = false"
        :creating="creating"
      />
    </Modal>

    <!-- Edit Dialog -->
    <Modal v-if="showEditDialog" title="编辑培育计划" @close="showEditDialog = false">
      <NurturePlanEditDialog
        v-if="editingPlan"
        :plan="editingPlan"
        :channels="channels"
        @submit="handleUpdate"
        @cancel="showEditDialog = false"
        :updating="updating"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useNurtureStore } from '@/stores/nurture'
import { useChannelStore } from '@/stores/channel'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import NurturePlanCreateDialog from '@/components/private_domain/NurturePlanCreateDialog.vue'
import NurturePlanEditDialog from '@/components/private_domain/NurturePlanEditDialog.vue'

const router = useRouter()
const nurtureStore = useNurtureStore()
const channelStore = useChannelStore()

const { nurtureList, total, loading } = storeToRefs(nurtureStore)
const { channelList: channels } = storeToRefs(channelStore)

// 筛选状态
const filterStatus = ref('')
const filterChannelId = ref('')

// 对话框状态
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingPlan = ref<any>(null)
const creating = ref(false)
const updating = ref(false)

// 分页
const currentPage = ref(1)
const pageSize = ref(10)

// 筛选后的培育计划列表
const filteredPlans = computed(() => {
  return nurtureList.value.filter(plan => {
    if (filterStatus.value && plan.status !== filterStatus.value) return false
    if (filterChannelId.value && plan.channel_id !== filterChannelId.value) return false
    return true
  })
})

onMounted(async () => {
  await Promise.all([
    fetchChannels(),
    fetchNurturePlans()
  ])
})

async function fetchChannels() {
  try {
    await channelStore.fetchChannels({ page_size: 100 })
  } catch (error) {
    console.error('Failed to fetch channels:', error)
  }
}

async function fetchNurturePlans() {
  try {
    const params: any = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (filterStatus.value) params.status = filterStatus.value
    if (filterChannelId.value) params.channel_id = filterChannelId.value
    await nurtureStore.fetchNurturePlans(params)
  } catch (error) {
    console.error('Failed to fetch nurture plans:', error)
  }
}

function handleFilter() {
  currentPage.value = 1
  fetchNurturePlans()
}

function getChannelName(channelId: string): string {
  const channel = channels.value.find(c => c.id === channelId)
  return channel?.name || channelId
}

function getScheduleLabel(scheduleType: string) {
  const labels: Record<string, string> = {
    fixed: '固定时间',
    drip: '滴灌序列',
    triggered: '触发式',
  }
  return labels[scheduleType] || scheduleType
}

function getStatusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: '草稿',
    active: '运行中',
    paused: '已暂停',
    completed: '已完成',
    archived: '已归档',
  }
  return labels[status] || status
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

function handleView(plan: any) {
  router.push(`/private-domain/nurture/${plan.id}`)
}

function handleEdit(plan: any) {
  editingPlan.value = plan
  showEditDialog.value = true
}

function handleCreate(data: any) {
  creating.value = true
  showCreateDialog.value = false
  nurtureStore.createNurture(data).then(() => {
    fetchNurturePlans()
  }).catch(error => {
    console.error('Failed to create nurture plan:', error)
  }).finally(() => {
    creating.value = false
  })
}

async function handleUpdate(data: any) {
  if (!editingPlan.value) return
  updating.value = true
  try {
    await nurtureStore.updateNurture(editingPlan.value.id, data)
    showEditDialog.value = false
    await fetchNurturePlans()
  } catch (error) {
    console.error('Failed to update nurture plan:', error)
  } finally {
    updating.value = false
  }
}

async function handleStart(plan: any) {
  try {
    await nurtureStore.startNurture(plan.id)
    await fetchNurturePlans()
  } catch (error) {
    console.error('启动失败:', error)
  }
}

async function handlePause(plan: any) {
  try {
    await nurtureStore.pauseNurture(plan.id)
    await fetchNurturePlans()
  } catch (error) {
    console.error('暂停失败:', error)
  }
}

async function handleDelete(plan: any) {
  if (!confirm(`确定要删除培育计划「${plan.name}」吗？`)) {
    return
  }
  try {
    await nurtureStore.deleteNurture(plan.id)
    await fetchNurturePlans()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  fetchNurturePlans()
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filters-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.filters-bar__left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-select--sm {
  padding: 6px 12px;
  font-size: 13px;
}

.nurture-list {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  background: var(--color-bg-secondary);
}

.data-table tbody tr:hover {
  background: var(--color-bg-tertiary);
}

.plan-link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}

.plan-link:hover {
  text-decoration: underline;
}

.schedule-badge {
  display: inline-block;
  padding: 4px 10px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.col-name {
  width: 180px;
}

.col-channel {
  width: 150px;
}

.col-schedule {
  width: 100px;
}

.col-status {
  width: 90px;
}

.col-steps {
  width: 80px;
}

.col-created {
  width: 120px;
}

.col-actions {
  width: 200px;
  text-align: right;
}

.btn--success {
  background: var(--color-success);
  color: white;
}

.btn--success:hover {
  background: #059669;
}

.btn--warning {
  background: var(--color-warning);
  color: white;
}

.btn--warning:hover {
  background: #D97706;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px;
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
