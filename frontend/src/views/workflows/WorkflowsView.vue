<template>
  <div class="page-container">
    <PageHeader
      title="工作流管理"
      description="创建并管理自动化工作流，配置触发器与动作"
      :loading="loading"
    >
      <template #actions>
        <button
          class="btn btn--primary"
          :disabled="!apiReady || creating"
          @click="showCreateDialog = true"
        >
          + 新建工作流
        </button>
      </template>
    </PageHeader>

    <!-- 后端未就绪：友好占位（保留框架约定） -->
    <div v-if="apiError && !loading" class="workflow-note">
      <div class="workflow-note__card">
        <div class="workflow-note__icon">🚧</div>
        <h3>工作流后端服务即将上线</h3>
        <p>
          Workflow 列表接口尚未就绪（等待后端 API）。前端框架已配置完成，
          路由、Store 与 API Client 均已绑定，后端服务启动后即可自动展示数据。
        </p>
        <button class="btn btn--ghost" @click="fetchWorkflows()">重新加载</button>
      </div>
    </div>

    <template v-else-if="!apiError">
      <!-- 搜索 + 筛选栏 -->
      <div class="filters-bar">
        <div class="filters-bar__left">
          <div class="search-box">
            <span class="search-box__icon">🔍</span>
            <input
              v-model="searchQuery"
              class="search-box__input"
              placeholder="搜索工作流名称 / 描述..."
              @input="handleSearch"
            />
          </div>
          <select
            v-model="filterStatus"
            class="form-select form-select--sm"
            @change="handleFilter"
          >
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="active">启用</option>
            <option value="paused">暂停</option>
            <option value="archived">已归档</option>
          </select>
        </div>
        <div class="filters-bar__right">
          <span class="text-muted">共 {{ total }} 个工作流</span>
        </div>
      </div>

      <!-- 操作反馈 -->
      <div v-if="flash" class="flash" :class="`flash--${flashType}`">
        <span class="flash__icon">{{ flashIcon }}</span>
        <span>{{ flash }}</span>
      </div>

      <!-- Loading -->
      <LoadingState v-if="loading" text="加载工作流..." />

      <!-- Empty -->
      <EmptyState
        v-else-if="workflows.length === 0"
        icon="⚡"
        title="暂无工作流"
        :description="
          hasActiveFilters
            ? '没有匹配的工作流，试试调整搜索或筛选条件'
            : '还没有任何工作流，点击创建你的第一个自动化工作流'
        "
        :show-action="!hasActiveFilters"
        action-text="创建工作流"
        @action="showCreateDialog = true"
      />

      <!-- Workflow 列表 -->
      <div v-else class="workflow-list">
        <table class="data-table">
          <thead>
            <tr>
              <th class="col-name">工作流名称</th>
              <th class="col-status">状态</th>
              <th class="col-time">最近更新</th>
              <th class="col-actions">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="workflow in workflows" :key="workflow.id">
              <td class="col-name">
                <router-link
                  :to="`/workflows/${workflow.id}`"
                  class="workflow-name__link"
                >
                  <div class="workflow-name">
                    <span class="workflow-name__title">
                      {{ workflow.name }}
                    </span>
                    <span
                      v-if="workflow.description"
                      class="workflow-name__desc"
                    >
                      {{ workflow.description }}
                    </span>
                  </div>
                </router-link>
              </td>
              <td class="col-status">
                <StatusBadge
                  :status="getStatusKey(workflow.status)"
                  :label="getStatusLabel(workflow.status)"
                />
              </td>
              <td class="col-time text-muted">{{ formatTime(workflow.updated_at) }}</td>
              <td class="col-actions">
                <button
                  class="btn btn--ghost btn--sm"
                  :disabled="acting === workflow.id"
                  @click="handleToggleStatus(workflow)"
                >
                  {{ workflow.status === 'active' ? '⏸ 暂停' : '▶ 启动' }}
                </button>
                <button
                  class="btn btn--ghost btn--sm"
                  @click="openEdit(workflow)"
                >
                  编辑
                </button>
                <button
                  class="btn btn--danger btn--sm"
                  :disabled="acting === workflow.id"
                  @click="handleDelete(workflow)"
                >
                  删除
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <!-- 分页 -->
        <div v-if="total > 0" class="pagination">
          <span class="pagination-info">共 {{ total }} 条</span>
          <button
            class="btn btn--ghost"
            :disabled="currentPage === 1"
            @click="handlePageChange(currentPage - 1)"
          >
            上一页
          </button>
          <span class="pagination-current">{{ currentPage }}</span>
          <button
            class="btn btn--ghost"
            :disabled="currentPage * pageSize >= total"
            @click="handlePageChange(currentPage + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </template>

    <!-- 创建对话框 -->
    <Modal
      v-if="showCreateDialog"
      title="新建工作流"
      @close="showCreateDialog = false"
    >
      <WorkflowCreateDialog
        :submitting="creating"
        @submit="handleCreate"
        @cancel="showCreateDialog = false"
      />
    </Modal>

    <!-- 编辑对话框 -->
    <Modal
      v-if="showEditDialog && editingWorkflow"
      title="编辑工作流"
      @close="showEditDialog = false"
    >
      <WorkflowEditDialog
        :workflow="editingWorkflow"
        :updating="updating"
        @submit="handleUpdate"
        @cancel="showEditDialog = false"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import type { Workflow, WorkflowStatus, WorkflowListParams } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import WorkflowCreateDialog from '@/components/workflows/WorkflowCreateDialog.vue'
import WorkflowEditDialog from '@/components/workflows/WorkflowEditDialog.vue'

const workflowStore = useWorkflowStore()
const { workflows, total, loading } = storeToRefs(workflowStore)

// ---- 后端就绪标记（保留框架约定：失败不白屏，展示占位） ----
const apiReady = ref(false)
const apiError = ref(false)

// ---- 搜索 / 筛选 / 分页 ----
const searchQuery = ref('')
const filterStatus = ref('')
const currentPage = ref(1)
const pageSize = ref(10)

let searchDebounce: number | undefined

const hasActiveFilters = computed(
  () => searchQuery.value.trim() !== '' || filterStatus.value !== ''
)

// ---- 对话框 ----
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingWorkflow = ref<Workflow | null>(null)
const creating = ref(false)
const updating = ref(false)
const acting = ref<string>('')

// ---- 轻提示 ----
const flash = ref('')
const flashType = ref<'success' | 'error'>('success')
let flashTimer: number | undefined

function showFlash(message: string, type: 'success' | 'error' = 'success') {
  flash.value = message
  flashType.value = type
  if (flashTimer) window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    flash.value = ''
  }, 2600)
}
const flashIcon = computed(() => (flashType.value === 'error' ? '⚠' : '✓'))

// ---- 状态映射 ----
function getStatusKey(status: WorkflowStatus): string {
  const map: Record<WorkflowStatus, string> = {
    draft: 'info',
    active: 'running',
    paused: 'stopped',
    archived: 'stopped',
  }
  return map[status] || 'info'
}

function getStatusLabel(status: WorkflowStatus): string {
  const labels: Record<WorkflowStatus, string> = {
    draft: '草稿',
    active: '启用',
    paused: '暂停',
    archived: '已归档',
  }
  return labels[status] || status
}

function formatTime(iso?: string) {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

// ---- 数据拉取 ----
async function fetchWorkflows() {
  apiError.value = false
  apiReady.value = false
  const params: WorkflowListParams = {
    page: currentPage.value,
    page_size: pageSize.value,
  }
  if (filterStatus.value) params.status = filterStatus.value as WorkflowStatus
  if (searchQuery.value.trim()) params.search = searchQuery.value.trim()

  try {
    await workflowStore.fetchWorkflows(params)
    apiReady.value = true
    apiError.value = false
  } catch (error) {
    // 后端未就绪（404 / 网络错误等）→ 展示友好占位，不影响框架可用
    apiError.value = true
    console.warn('[WorkflowsView] Workflow API 尚未就绪:', error)
  }
}

function handleSearch() {
  if (searchDebounce) window.clearTimeout(searchDebounce)
  searchDebounce = window.setTimeout(() => {
    currentPage.value = 1
    fetchWorkflows()
  }, 300)
}

function handleFilter() {
  currentPage.value = 1
  fetchWorkflows()
}

function handlePageChange(page: number) {
  if (page < 1) return
  currentPage.value = page
  fetchWorkflows()
}

// ---- CRUD 操作 ----
function openEdit(workflow: Workflow) {
  editingWorkflow.value = workflow
  showEditDialog.value = true
}

async function handleCreate(data: { name: string; description?: string }) {
  creating.value = true
  try {
    await workflowStore.createWorkflow(data)
    showCreateDialog.value = false
    await fetchWorkflows()
    showFlash(`工作流「${data.name}」已创建`)
  } catch (error) {
    console.error('创建失败:', error)
    showFlash('创建工作流失败，请重试', 'error')
  } finally {
    creating.value = false
  }
}

async function handleUpdate(
  data: { name: string; description?: string; status?: WorkflowStatus }
) {
  if (!editingWorkflow.value) return
  updating.value = true
  const id = editingWorkflow.value.id
  try {
    await workflowStore.updateWorkflow(id, data)
    showEditDialog.value = false
    editingWorkflow.value = null
    await fetchWorkflows()
    showFlash('工作流已更新')
  } catch (error) {
    console.error('更新失败:', error)
    showFlash('更新工作流失败，请重试', 'error')
  } finally {
    updating.value = false
  }
}

async function handleDelete(workflow: Workflow) {
  if (!window.confirm(`确定要删除工作流「${workflow.name}」吗？此操作不可恢复。`)) {
    return
  }
  acting.value = workflow.id
  try {
    await workflowStore.deleteWorkflow(workflow.id)
    await fetchWorkflows()
    showFlash(`工作流「${workflow.name}」已删除`)
  } catch (error) {
    console.error('删除失败:', error)
    showFlash('删除工作流失败，请重试', 'error')
  } finally {
    acting.value = ''
  }
}

async function handleToggleStatus(workflow: Workflow) {
  acting.value = workflow.id
  try {
    if (workflow.status === 'active') {
      await workflowStore.pauseWorkflow(workflow.id)
      showFlash(`工作流「${workflow.name}」已暂停`)
    } else {
      await workflowStore.activateWorkflow(workflow.id)
      showFlash(`工作流「${workflow.name}」已启动`)
    }
    await fetchWorkflows()
  } catch (error) {
    console.error('启停失败:', error)
    showFlash('操作失败，请重试', 'error')
  } finally {
    acting.value = ''
  }
}

onMounted(fetchWorkflows)
onBeforeUnmount(() => {
  if (searchDebounce) window.clearTimeout(searchDebounce)
  if (flashTimer) window.clearTimeout(flashTimer)
})
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---- 后端未就绪占位 ---- */
.workflow-note {
  display: flex;
  justify-content: center;
  padding: var(--spacing-6);
}

.workflow-note__card {
  max-width: 460px;
  text-align: center;
  padding: var(--spacing-8);
  background: var(--color-bg-primary);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-3);
}

.workflow-note__icon {
  font-size: 40px;
}

.workflow-note__card h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
}

.workflow-note__card p {
  margin: 0 0 var(--spacing-3);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  line-height: 1.6;
}

/* ---- 搜索 / 筛选栏 ---- */
.filters-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.filters-bar__left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filters-bar__right {
  flex-shrink: 0;
  font-size: 13px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  min-width: 240px;
}

.search-box__icon {
  font-size: 14px;
  opacity: 0.7;
}

.search-box__input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--color-text-primary);
  width: 100%;
}

.form-select--sm {
  padding: 6px 12px;
  font-size: 13px;
}

/* ---- 轻提示 ---- */
.flash {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 13px;
}

.flash--success {
  background: var(--color-success-light);
  color: var(--color-success);
}

.flash--error {
  background: var(--color-error-light);
  color: var(--color-error);
}

.flash__icon {
  font-weight: 700;
}

/* ---- 列表表格 ---- */
.workflow-list {
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

.workflow-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.workflow-name__link {
  text-decoration: none;
  color: inherit;
}

.workflow-name__link:hover .workflow-name__title {
  color: var(--color-primary);
}

.workflow-name__title {
  font-weight: 500;
  color: var(--color-text-primary);
}

.workflow-name__desc {
  font-size: 12px;
  color: var(--color-text-muted);
}

.col-name {
  min-width: 220px;
}

.col-status {
  width: 90px;
}

.col-count {
  width: 80px;
}

.col-time {
  width: 180px;
}

.col-actions {
  width: 240px;
  text-align: right;
  white-space: nowrap;
}

.col-actions .btn {
  margin-left: 6px;
}

.col-actions .btn:first-child {
  margin-left: 0;
}

/* ---- 分页 ---- */
.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid var(--color-border);
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
