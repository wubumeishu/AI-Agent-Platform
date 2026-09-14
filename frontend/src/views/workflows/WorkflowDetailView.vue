<template>
  <div class="page-container">
    <PageHeader
      :title="currentWorkflow?.name || '工作流详情'"
      description="查看工作流配置、触发器、动作与执行历史"
      show-back
      :loading="loading"
    >
      <template v-if="currentWorkflow && !apiError" #actions>
        <button
          class="btn btn--ghost"
          :disabled="acting"
          @click="handleToggleStatus()"
        >
          {{
            currentWorkflow.status === 'active'
              ? '⏸ 暂停工作流'
              : '▶ 启动工作流'
          }}
        </button>
        <button class="btn btn--ghost" @click="openEdit()">编辑</button>
        <button
          class="btn btn--danger"
          :disabled="acting"
          @click="handleDelete()"
        >
          删除
        </button>
      </template>
    </PageHeader>

    <!-- 操作反馈 -->
    <div v-if="flash" class="flash" :class="`flash--${flashType}`">
      <span class="flash__icon">{{ flashIcon }}</span>
      <span>{{ flash }}</span>
    </div>

    <!-- 后端未就绪：友好占位（保留框架约定） -->
    <div v-if="apiError && !loading" class="workflow-note">
      <div class="workflow-note__card">
        <div class="workflow-note__icon">🚧</div>
        <h3>工作流后端服务即将上线</h3>
        <p>
          该工作流的详情接口尚未就绪（等待后端 API）。加载完成后将展示
          基本信息、触发器、动作与执行历史。
        </p>
        <button class="btn btn--ghost" @click="fetchAll()">重新加载</button>
      </div>
    </div>

    <template v-else-if="currentWorkflow && !apiError">
      <!-- 基本信息 -->
      <section class="detail-block">
        <div class="overview">
          <div class="overview__status">
            <StatusBadge
              :status="getStatusKey(currentWorkflow.status)"
              :label="getStatusLabel(currentWorkflow.status)"
            />
          </div>
          <div class="overview__body">
            <div v-if="currentWorkflow.description" class="overview__desc">
              {{ currentWorkflow.description }}
            </div>
            <div class="overview__meta">
              <span
                >版本 <b>{{ currentWorkflow.version ?? '-' }}</b></span
              >
              <span>类型 <b>{{ currentWorkflow.workflow_type ?? '-' }}</b></span>
              <span>触发器 <b>{{ triggers.length }}</b></span>
              <span
                >条件 <b>{{ totalConditionCount }}</b></span
              >
              <span
                >动作 <b>{{ totalActionCount }}</b></span
              >
              <span
                >创建 <b>{{ formatTime(currentWorkflow.created_at) }}</b></span
              >
              <span
                >更新 <b>{{ formatTime(currentWorkflow.updated_at) }}</b></span
              >
            </div>
          </div>
        </div>
      </section>

      <!-- 触发器配置区（t_wf_010） -->
      <section class="detail-block detail-block--full">
        <div class="trigger-section-head">
          <h3 class="detail-block__title">
            触发器
            <span class="text-muted" v-if="triggers.length">
              {{ triggers.length }}
            </span>
          </h3>
          <button
            class="btn btn--primary btn--sm"
            :disabled="triggerBusy || apiError"
            @click="openCreateTrigger()"
          >
            + 新建触发器
          </button>
        </div>

        <EmptyState
          v-if="triggers.length === 0 && !triggersLoading"
          icon="⏰"
          title="暂无触发器"
          description="配置定时、事件或手动触发器，让工作流在合适的时机自动运行"
        />
        <LoadingState v-else-if="triggersLoading" text="加载触发器..." />
        <TriggerList
          v-else
          :triggers="triggers"
          :conditions-of="conditionsOf"
          :busy-ids="busyTriggerIds"
          @toggle-enabled="handleToggleTriggerEnabled"
          @edit="openEditTrigger"
          @delete="handleDeleteTrigger"
          @add-condition="openConditionDialog"
        />
      </section>

      <!-- 执行历史 -->
      <section class="detail-block detail-block--full">
        <h3 class="detail-block__title">
          执行历史
          <span class="text-muted" v-if="executionLogs.length">
            {{ executionLogsTotal }}
          </span>
        </h3>
        <div class="exec-subhead">
          <span v-if="executionLogsLoading" class="text-muted">加载中...</span>
          <button
            v-else-if="executionLogs.length > 0"
            class="btn btn--ghost btn--sm"
            @click="fetchAll()"
          >
            刷新
          </button>
        </div>
        <EmptyState
          v-if="!executionLogsLoading && executionLogs.length === 0"
          icon="📜"
          title="暂无执行记录"
          description="该工作流还没有执行日志"
        />
        <div v-else-if="executionLogs.length > 0" class="exec-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th class="col-exec-type">类型</th>
                <th class="col-exec-status">状态</th>
                <th class="col-exec-start">开始时间</th>
                <th class="col-exec-end">结束时间</th>
                <th class="col-exec-dur">耗时</th>
                <th class="col-exec-error">错误信息</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in executionLogs" :key="log.id">
                <td class="col-exec-type text-muted">
                  {{ log.trigger_type || '-' }}
                </td>
                <td class="col-exec-status">
                  <StatusBadge
                    :status="getExecStatusKey(log.status)"
                    :label="getExecStatusLabel(log.status)"
                  />
                </td>
                <td class="col-exec-start text-muted">
                  {{ formatTime(log.started_at) }}
                </td>
                <td class="col-exec-end text-muted">
                  {{ formatTime(log.finished_at) }}
                </td>
                <td class="col-exec-dur">{{
                  formatDuration(log.duration_ms)
                }}</td>
                <td class="col-exec-error">
                  <span
                    v-if="log.error_message"
                    class="exec-error"
                    :title="log.error_message"
                  >
                    {{ log.error_message }}
                  </span>
                  <span v-else class="text-muted">-</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <!-- 编辑工作流对话框 -->
    <Modal
      v-if="showEditDialog && currentWorkflow"
      title="编辑工作流"
      @close="showEditDialog = false"
    >
      <WorkflowEditDialog
        :workflow="currentWorkflow"
        :updating="updating"
        @submit="handleUpdate"
        @cancel="showEditDialog = false"
      />
    </Modal>

    <!-- 触发器配置对话框（创建 / 编辑） -->
    <Modal
      v-if="showTriggerDialog"
      :title="triggerEditing ? '编辑触发器' : '新建触发器'"
      width="640px"
      @close="showTriggerDialog = false"
    >
      <TriggerDialog
        :editing="triggerEditing"
        :conditions="triggerEditing ? conditionsOf(triggerEditing.id) : undefined"
        :submitting="triggerBusy"
        @submit="handleTriggerSubmit"
        @cancel="showTriggerDialog = false"
      />
    </Modal>

    <!-- 条件管理对话框（挂在某触发器下） -->
    <Modal
      v-if="showConditionDialog && conditionTrigger"
      :title="`条件管理 · ${triggerSummaryLabel(conditionTrigger)}`"
      width="640px"
      @close="showConditionDialog = false"
    >
      <ConditionDialog
        :conditions="conditionsOf(conditionTrigger.id)"
        :busy="triggerBusy"
        @create-condition="handleCreateCondition"
        @update-condition="handleUpdateCondition"
        @delete-condition="handleDeleteCondition"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, onBeforeRouteLeave, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useWorkflowStore } from '@/stores/workflow'
import { useTriggerStore } from '@/stores/trigger'
import type {
  WorkflowStatus,
  TriggerType,
  ExecutionStatus,
  WorkflowTrigger,
  WorkflowCondition,
  CreateConditionRequest,
  UpdateConditionRequest,
} from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import WorkflowEditDialog from '@/components/workflows/WorkflowEditDialog.vue'
import TriggerList from '@/components/workflows/TriggerList.vue'
import TriggerDialog from '@/components/workflows/TriggerDialog.vue'
import ConditionDialog from '@/components/workflows/ConditionDialog.vue'

const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const triggerStore = useTriggerStore()

const {
  currentWorkflow,
  loading,
  executionLogs,
  executionLogsTotal,
  executionLogsLoading,
} = storeToRefs(workflowStore)
const { triggers, loading: triggersLoading } = storeToRefs(triggerStore)
// 普通函数（非 ref），直接引用以便模板使用
const conditionsOf = triggerStore.conditionsOf.bind(triggerStore)

const apiError = ref(false)
const acting = ref(false)
const updating = ref(false)
const showEditDialog = ref(false)

// ---- 触发器对话框状态 ----
const showTriggerDialog = ref(false)
const triggerEditing = ref<WorkflowTrigger | null>(null)
const showConditionDialog = ref(false)
const conditionTrigger = ref<WorkflowTrigger | null>(null)
const busyTriggerIds = ref<string[]>([])

function triggerBusyState(): boolean {
  return busyTriggerIds.value.length > 0
}
const triggerBusy = computed(triggerBusyState)

function setBusy(triggerId: string | null) {
  if (triggerId) {
    busyTriggerIds.value = [triggerId]
  } else {
    busyTriggerIds.value = []
  }
}

// ---- 统计 ----
const totalConditionCount = computed(() =>
  triggers.value.reduce(
    (sum, t) => sum + (triggerStore.conditionsOf(t.id)?.length ?? 0),
    0
  )
)
const totalActionCount = computed(() =>
  triggers.value.reduce(
    (sum, t) =>
      sum +
      (triggerStore.conditionsOf(t.id)?.reduce(
        (s, c) => s + (c.actions?.length ?? 0),
        0
      ) ?? 0),
    0
  )
)

function triggerSummaryLabel(trigger: WorkflowTrigger): string {
  return trigger.name || `触发器 ${trigger.id.slice(0, 8)}`
}

// ---- 轻提示 ----
const flash = ref('')
const flashType = ref<'success' | 'error'>('success')
let flashTimer: number | undefined
const flashIcon = computed(() => (flashType.value === 'error' ? '⚠' : '✓'))

function showFlash(message: string, type: 'success' | 'error' = 'success') {
  flash.value = message
  flashType.value = type
  if (flashTimer) window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    flash.value = ''
  }, 2600)
}

function getWorkflowId(): string {
  return String(route.params.id ?? '')
}

// ---- 状态映射（对齐后端 t_wf_001/002 词表） ----
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
  const map: Record<WorkflowStatus, string> = {
    draft: '草稿',
    active: '启用',
    paused: '暂停',
    archived: '已归档',
  }
  return map[status] || status
}

function getTriggerTypeLabel(type: TriggerType) {
  const map: Record<TriggerType, string> = {
    cron: '周期 Cron',
    scheduled: '单次定时',
    event: '事件触发',
    manual: '手动触发',
  }
  return map[type] || type
}

function getExecStatusKey(status: ExecutionStatus): string {
  const map: Record<ExecutionStatus, string> = {
    pending: 'info',
    running: 'running',
    success: 'success',
    failed: 'error',
    cancelled: 'stopped',
    timeout: 'warning',
  }
  return map[status] || 'info'
}

function getExecStatusLabel(status: ExecutionStatus): string {
  const map: Record<ExecutionStatus, string> = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
    timeout: '超时',
  }
  return map[status] || status
}

function formatTime(iso?: string) {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function formatDuration(ms?: number) {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)} s`
  const minutes = Math.floor(seconds / 60)
  const rem = Math.round(seconds % 60)
  return `${minutes} 分 ${rem} 秒`
}

// ---- 数据拉取 ----
async function fetchAll() {
  apiError.value = false
  const id = getWorkflowId()
  if (!id) {
    apiError.value = true
    return
  }
  try {
    await workflowStore.fetchWorkflow(id)
    await triggerStore.fetchTriggers(id)
    await workflowStore.fetchExecutionLogs(id, { page: 1, page_size: 50 })
  } catch (error) {
    // 后端未就绪（404 / 网络错误等）→ 展示友好占位
    apiError.value = true
    console.warn('[WorkflowDetailView] Workflow API 尚未就绪:', error)
  }
}

// ---- 工作流操作 ----
function openEdit() {
  showEditDialog.value = true
}

async function handleToggleStatus() {
  const id = getWorkflowId()
  if (!id || !currentWorkflow.value) return
  acting.value = true
  try {
    if (currentWorkflow.value.status === 'active') {
      await workflowStore.pauseWorkflow(id)
      showFlash('工作流已暂停')
    } else {
      await workflowStore.activateWorkflow(id)
      showFlash('工作流已启动')
    }
  } catch (error) {
    console.error('启停失败:', error)
    showFlash('操作失败，请重试', 'error')
  } finally {
    acting.value = false
  }
}

async function handleUpdate(
  data: { name: string; description?: string; status?: WorkflowStatus }
) {
  const id = getWorkflowId()
  if (!id) return
  updating.value = true
  try {
    await workflowStore.updateWorkflow(id, data)
    showEditDialog.value = false
    await workflowStore.fetchWorkflow(id)
    showFlash('工作流已更新')
  } catch (error) {
    console.error('更新失败:', error)
    showFlash('更新工作流失败，请重试', 'error')
  } finally {
    updating.value = false
  }
}

async function handleDelete() {
  const id = getWorkflowId()
  if (!id || !currentWorkflow.value) return
  if (
    !window.confirm(
      `确定要删除工作流「${currentWorkflow.value.name}」吗？其触发器、条件与动作将一并删除，此操作不可恢复。`
    )
  ) {
    return
  }
  acting.value = true
  try {
    await workflowStore.deleteWorkflow(id)
    showFlash('工作流已删除')
    router.push('/workflows')
  } catch (error) {
    console.error('删除失败:', error)
    showFlash('删除工作流失败，请重试', 'error')
    acting.value = false
  }
}

// ---- 触发器操作 ----
function openCreateTrigger() {
  triggerEditing.value = null
  showTriggerDialog.value = true
}

function openEditTrigger(trigger: WorkflowTrigger) {
  triggerEditing.value = trigger
  showTriggerDialog.value = true
}

async function handleTriggerSubmit(payload: {
  trigger: {
    name?: string
    trigger_type: TriggerType
    spec: Record<string, unknown>
    enabled?: boolean
  }
  conditions: CreateConditionRequest[]
}) {
  const id = getWorkflowId()
  if (!id) return
  setBusy(triggerEditing.value?.id ?? null)
  try {
    if (triggerEditing.value) {
      await triggerStore.updateTrigger(id, triggerEditing.value.id, payload.trigger)
      showFlash('触发器已更新')
    } else {
      const created = await triggerStore.createTrigger(id, payload.trigger)
      // 创建后立即挂载初始条件
      for (const cond of payload.conditions) {
        await triggerStore.createCondition(id, created.id, cond)
      }
      showFlash('触发器已创建')
    }
    showTriggerDialog.value = false
    triggerEditing.value = null
    await triggerStore.fetchTriggers(id)
  } catch (error) {
    console.error('触发器保存失败:', error)
    showFlash('触发器保存失败，请检查表单与后端响应', 'error')
  } finally {
    setBusy(null)
  }
}

async function handleToggleTriggerEnabled(trigger: WorkflowTrigger) {
  const id = getWorkflowId()
  if (!id) return
  setBusy(trigger.id)
  try {
    await triggerStore.setTriggerEnabled(id, trigger.id, !trigger.enabled)
    showFlash(trigger.enabled ? '触发器已禁用' : '触发器已启用')
  } catch (error) {
    console.error('触发器启用/禁用失败:', error)
    showFlash('操作失败，请重试', 'error')
  } finally {
    setBusy(null)
  }
}

async function handleDeleteTrigger(trigger: WorkflowTrigger) {
  const id = getWorkflowId()
  if (!id) return
  if (!window.confirm(`确定删除触发器「${triggerSummaryLabel(trigger)}」吗？其条件与动作将一并删除。`)) {
    return
  }
  setBusy(trigger.id)
  try {
    await triggerStore.deleteTrigger(id, trigger.id)
    showFlash('触发器已删除')
  } catch (error) {
    console.error('删除触发器失败:', error)
    showFlash('删除触发器失败，请重试', 'error')
  } finally {
    setBusy(null)
  }
}

// ---- 条件操作 ----
function openConditionDialog(trigger: WorkflowTrigger) {
  conditionTrigger.value = trigger
  showConditionDialog.value = true
}

async function handleCreateCondition(data: CreateConditionRequest) {
  const id = getWorkflowId()
  const trigger = conditionTrigger.value
  if (!id || !trigger) return
  setBusy(trigger.id)
  try {
    await triggerStore.createCondition(id, trigger.id, data)
    showFlash('条件已添加')
  } catch (error) {
    console.error('条件创建失败:', error)
    showFlash('条件创建失败，请重试', 'error')
  } finally {
    setBusy(null)
  }
}

async function handleUpdateCondition(
  conditionId: string,
  data: UpdateConditionRequest
) {
  const id = getWorkflowId()
  const trigger = conditionTrigger.value
  if (!id || !trigger) return
  setBusy(trigger.id)
  try {
    await triggerStore.updateCondition(id, trigger.id, conditionId, data)
    showFlash('条件已更新')
  } catch (error) {
    console.error('条件更新失败:', error)
    showFlash('条件更新失败，请重试', 'error')
  } finally {
    setBusy(null)
  }
}

async function handleDeleteCondition(condition: WorkflowCondition) {
  const id = getWorkflowId()
  const trigger = conditionTrigger.value
  if (!id || !trigger) return
  if (!window.confirm('确定删除该条件吗？')) return
  setBusy(trigger.id)
  try {
    await triggerStore.deleteCondition(id, trigger.id, condition.id)
    showFlash('条件已删除')
  } catch (error) {
    console.error('条件删除失败:', error)
    showFlash('条件删除失败，请重试', 'error')
  } finally {
    setBusy(null)
  }
}

onMounted(fetchAll)
onBeforeRouteLeave(() => {
  workflowStore.clearCurrentWorkflow()
  triggerStore.clearTriggers()
})

onBeforeUnmount(() => {
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

/* ---- 基本信息 ---- */
.detail-block {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
}

.detail-block--full {
  grid-column: 1 / -1;
}

.detail-block__title {
  margin: 0 0 var(--spacing-4);
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.overview {
  display: flex;
  gap: 16px;
}

.overview__body {
  flex: 1;
  min-width: 0;
}

.overview__desc {
  margin-bottom: 10px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.overview__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.overview__meta b {
  font-weight: 600;
  color: var(--color-text-primary);
}

/* ---- 触发器区 ---- */
.trigger-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-4);
}

.trigger-section-head .detail-block__title {
  margin: 0;
}

/* ---- 执行历史 ---- */
.exec-subhead {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}

.exec-table-wrap {
  overflow-x: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  background: var(--color-bg-secondary);
}

.exec-error {
  color: var(--color-error);
  font-size: 12px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
}

.col-exec-type {
  width: 90px;
}

.col-exec-status {
  width: 90px;
}

.col-exec-start {
  width: 170px;
}

.col-exec-end {
  width: 170px;
}

.col-exec-dur {
  width: 90px;
}

@media (max-width: 768px) {
  .overview {
    flex-direction: column;
  }

  .trigger-section-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
