<template>
  <div class="page-container">
    <PageHeader title="培育计划详情" :show-back="true">
      <template #actions>
        <button class="btn btn--primary" @click="showEditDialog = true">
          编辑计划
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Error State -->
    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button class="btn btn--ghost" @click="fetchPlan()">重试</button>
    </div>

    <!-- Plan Detail -->
    <div v-else-if="plan" class="detail-container">
      <!-- 基本信息 -->
      <div class="detail-card">
        <h3 class="detail-card__title">基本信息</h3>
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-item__label">计划名称</span>
            <span class="detail-item__value">{{ plan.name }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">关联渠道</span>
            <span class="detail-item__value">{{ channelName }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">触发方式</span>
            <span class="detail-item__value">{{ getScheduleLabel(plan.schedule_type) }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">状态</span>
            <span class="detail-item__value">
              <StatusBadge :status="plan.status" :label="getStatusLabel(plan.status)" />
            </span>
          </div>
          <div class="detail-item" v-if="plan.target_segment_id">
            <span class="detail-item__label">目标客户群</span>
            <span class="detail-item__value">{{ plan.target_segment_id }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">创建时间</span>
            <span class="detail-item__value">{{ formatDateTime(plan.created_at) }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">更新时间</span>
            <span class="detail-item__value">{{ formatDateTime(plan.updated_at) }}</span>
          </div>
          <div class="detail-item full-width" v-if="plan.description">
            <span class="detail-item__label">描述</span>
            <span class="detail-item__value">{{ plan.description }}</span>
          </div>
        </div>
      </div>

      <!-- 步骤列表 -->
      <div class="detail-card" v-if="plan.sequence_steps && plan.sequence_steps.length > 0">
        <h3 class="detail-card__title">培育步骤</h3>
        <div class="steps-list">
          <div
            v-for="(step, index) in plan.sequence_steps"
            :key="index"
            class="step-item"
          >
            <div class="step-item__header">
              <span class="step-item__order">步骤 {{ Number(index) + 1 }}</span>
              <span class="step-item__delay" v-if="step.delay_hours > 0">
                延迟 {{ step.delay_hours }} 小时
              </span>
            </div>
            <div class="step-item__content" v-if="step.content_id">
              <span class="text-muted">内容 ID: {{ step.content_id }}</span>
            </div>
            <div class="step-item__action" v-if="step.action">
              <span class="badge badge--action">{{ step.action }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 触发条件 -->
      <div class="detail-card" v-if="plan.trigger_conditions && plan.trigger_conditions.length > 0">
        <h3 class="detail-card__title">触发条件</h3>
        <div class="conditions-list">
          <div
            v-for="(condition, index) in plan.trigger_conditions"
            :key="index"
            class="condition-item"
          >
            <span class="condition-item__field">{{ condition.field }}</span>
            <span class="condition-item__operator">{{ getOperatorLabel(condition.operator) }}</span>
            <span class="condition-item__value">{{ condition.value }}</span>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="detail-actions">
        <button
          v-if="plan.status !== 'active'"
          class="btn btn--success"
          @click="handleStart"
        >启动计划</button>
        <button
          v-else
          class="btn btn--warning"
          @click="handlePause"
        >暂停计划</button>
        <button
          v-if="plan.status !== 'completed' && plan.status !== 'archived'"
          class="btn btn--ghost"
          @click="handleComplete"
        >标记完成</button>
        <button
          class="btn btn--danger"
          @click="handleDelete"
        >删除计划</button>
      </div>
    </div>

    <!-- Edit Dialog -->
    <Modal v-if="showEditDialog" title="编辑培育计划" @close="showEditDialog = false">
      <NurturePlanEditDialog
        v-if="plan"
        :plan="plan"
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
import { useRouter, useRoute } from 'vue-router'
import { useNurtureStore } from '@/stores/nurture'
import { useChannelStore } from '@/stores/channel'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import NurturePlanEditDialog from '@/components/private_domain/NurturePlanEditDialog.vue'

const router = useRouter()
const route = useRoute()
const nurtureStore = useNurtureStore()
const channelStore = useChannelStore()

const planId = String(route.params.id)
const plan = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const showEditDialog = ref(false)
const updating = ref(false)

// 获取关联渠道名称
const channelName = computed(() => {
  if (!plan.value?.channel_id) return '-'
  const channel = channelStore.channelList.find((c: any) => c.id === plan.value.channel_id)
  return channel?.name || plan.value.channel_id
})

// 所有渠道列表
const channels = computed(() => channelStore.channelList)

onMounted(async () => {
  await Promise.all([
    channelStore.fetchChannels({ page_size: 100 }),
    fetchPlan()
  ])
})

async function fetchPlan() {
  loading.value = true
  error.value = null
  try {
    const data = await nurtureStore.fetchNurturePlan(planId)
    plan.value = data
  } catch (err: any) {
    error.value = err.message || '加载培育计划详情失败'
    console.error('Failed to fetch nurture plan:', err)
  } finally {
    loading.value = false
  }
}

function getScheduleLabel(scheduleType: string): string {
  const labels: Record<string, string> = {
    fixed: '固定时间',
    drip: '滴灌序列',
    triggered: '触发式',
  }
  return labels[scheduleType] || scheduleType
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    draft: '草稿',
    active: '运行中',
    paused: '已暂停',
    completed: '已完成',
    archived: '已归档',
  }
  return labels[status] || status
}

function getOperatorLabel(operator: string): string {
  const labels: Record<string, string> = {
    eq: '=',
    neq: '≠',
    gt: '>',
    lt: '<',
    in: 'in',
    contains: 'contains',
  }
  return labels[operator] || operator
}

function formatDateTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function handleStart() {
  try {
    await nurtureStore.startNurture(planId)
    await fetchPlan()
  } catch (error) {
    console.error('启动失败:', error)
  }
}

async function handlePause() {
  try {
    await nurtureStore.pauseNurture(planId)
    await fetchPlan()
  } catch (error) {
    console.error('暂停失败:', error)
  }
}

async function handleComplete() {
  try {
    await nurtureStore.completeNurture(planId)
    await fetchPlan()
  } catch (error) {
    console.error('标记完成失败:', error)
  }
}

async function handleUpdate(data: any) {
  updating.value = true
  try {
    await nurtureStore.updateNurture(planId, data)
    showEditDialog.value = false
    await fetchPlan()
  } catch (error) {
    console.error('更新失败:', error)
  } finally {
    updating.value = false
  }
}

async function handleDelete() {
  if (!confirm('确定要删除这个培育计划吗？此操作不可恢复。')) {
    return
  }
  try {
    await nurtureStore.deleteNurture(planId)
    router.push('/private-domain/nurture')
  } catch (error) {
    console.error('删除失败:', error)
  }
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}

.error-state p {
  color: var(--color-error);
  margin-bottom: 16px;
}

.detail-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-card {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  padding: 20px;
}

.detail-card__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-item.full-width {
  grid-column: span 3;
}

.detail-item__label {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.detail-item__value {
  font-size: 14px;
  color: var(--color-text-primary);
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-item {
  padding: 16px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.step-item__header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.step-item__order {
  font-weight: 600;
  color: var(--color-primary);
}

.step-item__delay {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.step-item__content,
.step-item__action {
  font-size: 13px;
}

.badge--action {
  display: inline-block;
  padding: 4px 10px;
  background: var(--color-info-light);
  color: var(--color-info);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.conditions-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.condition-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.condition-item__field {
  font-weight: 500;
  color: var(--color-text-primary);
}

.condition-item__operator {
  padding: 2px 8px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.condition-item__value {
  font-size: 14px;
  color: var(--color-text-primary);
}

.detail-actions {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
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

@media (max-width: 768px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .detail-item.full-width {
    grid-column: span 1;
  }

  .detail-actions {
    flex-wrap: wrap;
  }
}
</style>
