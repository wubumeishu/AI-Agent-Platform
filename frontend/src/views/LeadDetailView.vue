<template>
  <div class="lead-detail-view" v-loading="currentLeadLoading">
    <PageHeader title="线索详情" show-back>
      <template #actions>
        <button class="btn btn--ghost" @click="handleEdit">编辑</button>
        <button class="btn btn--danger" @click="handleDelete">删除</button>
      </template>
    </PageHeader>

    <div v-if="!currentLead" class="empty-state">
      <p>线索不存在</p>
    </div>

    <div v-else class="lead-detail-content">
      <!-- Lead Header Card -->
      <Card class="lead-header-card">
        <template #header>
          <div class="lead-header">
            <div class="lead-header__info">
              <h2 class="lead-header__id">线索 #{{ currentLead.id.slice(0, 8) }}</h2>
              <div class="lead-header__meta">
                <StatusBadge :status="getStatusClass(currentLead.status)" :label="getStatusLabel(currentLead.status)" />
                <span class="meta-separator">·</span>
                <span class="meta-text">创建于 {{ formatTime(currentLead.created_at) }}</span>
              </div>
            </div>
            <div class="lead-header__score">
              <div class="score-circle" :style="{ '--score-color': getScoreColor(currentLead.intent_score) }">
                <span class="score-circle__value">{{ currentLead.intent_score ?? '-' }}</span>
                <span class="score-circle__label">意向分</span>
              </div>
            </div>
          </div>
        </template>
        
        <div class="lead-basic-info">
          <div class="info-grid">
            <div class="info-item">
              <span class="info-label">生命周期阶段</span>
              <span class="info-value">{{ currentLead.lifecycle_stage_code || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">来源类型</span>
              <span class="info-value">{{ getSourceLabel(currentLead.source_type || 'other') }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">关联客户</span>
              <span class="info-value">{{ currentLead.customer_id ? '已关联' : '未关联' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">最后更新</span>
              <span class="info-value">{{ formatTime(currentLead.updated_at) }}</span>
            </div>
          </div>
          
          <!-- Notes -->
          <div class="lead-notes" v-if="currentLead.notes">
            <h4 class="section-title">备注</h4>
            <p class="notes-text">{{ currentLead.notes }}</p>
          </div>

          <!-- Tags -->
          <div class="lead-tags-section" v-if="currentLead.tags.length > 0">
            <h4 class="section-title">标签</h4>
            <div class="tags-list">
              <span
                v-for="tag in currentLead.tags"
                :key="tag.id"
                class="tag-badge"
                :style="{ backgroundColor: tag.color ? tag.color + '20' : '#f0f0f0' }"
              >
                {{ tag.name }}
              </span>
            </div>
          </div>
        </div>
      </Card>

      <!-- Tabs -->
      <div class="tabs-container">
        <Tabs v-model="activeTab" :tabs="tabs" />
      </div>

      <!-- Tab Content -->
      <div class="tab-content">
        <!-- Lifecycle Tab -->
        <div v-if="activeTab === 'lifecycle'" class="tab-panel">
          <Card>
            <template #header>
              <div class="card-header-flex">
                <h3>生命周期流转</h3>
                <button class="btn btn--ghost btn--sm" @click="showTransitionDialog = true">
                  + 阶段流转
                </button>
              </div>
            </template>
            
            <div v-if="!currentLead.lifecycle_logs || currentLead.lifecycle_logs.length === 0" class="empty-content">
              <p class="text-muted">暂无阶段变更记录</p>
            </div>
            
            <div v-else class="timeline">
              <div
                v-for="log in [...currentLead.lifecycle_logs].reverse()"
                :key="log.id"
                class="timeline-item"
              >
                <div class="timeline-item__dot"></div>
                <div class="timeline-item__content">
                  <div class="timeline-item__header">
                    <span class="timeline-item__stage">
                      <template v-if="log.old_stage_code">
                        {{ log.old_stage_code }} → {{ log.new_stage_code }}
                      </template>
                      <template v-else>
                        {{ log.new_stage_code }}
                      </template>
                    </span>
                    <span class="timeline-item__time">{{ formatTime(log.created_at) }}</span>
                  </div>
                  <p class="timeline-item__reason" v-if="log.transition_reason">
                    {{ log.transition_reason }}
                  </p>
                  <p class="timeline-item__operator" v-if="log.operator">
                    操作人: {{ log.operator }}
                  </p>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <!-- Conversations Tab -->
        <div v-if="activeTab === 'conversations'" class="tab-panel">
          <Card>
            <template #header>
              <h3>对话历史</h3>
            </template>
            <div class="conversations-empty">
              <p class="text-muted">暂无对话记录</p>
            </div>
          </Card>
        </div>

        <!-- Activity Tab -->
        <div v-if="activeTab === 'activity'" class="tab-panel">
          <Card>
            <template #header>
              <h3>活动记录</h3>
            </template>
            <div class="activity-empty">
              <p class="text-muted">暂无活动记录</p>
            </div>
          </Card>
        </div>
      </div>
    </div>

    <!-- Edit Dialog -->
    <Modal
      v-if="showEditDialog"
      title="编辑线索"
      @close="showEditDialog = false"
    >
      <form @submit.prevent="handleUpdate">
        <div class="form-group">
          <label class="form-label">生命周期阶段</label>
          <select v-model="editForm.lifecycle_stage_code" class="form-input">
            <option v-for="stage in lifecycleStages" :key="stage.code" :value="stage.code">
              {{ stage.name }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">状态</label>
          <select v-model="editForm.status" class="form-input">
            <option value="new">新线索</option>
            <option value="contacted">已联系</option>
            <option value="qualified">已验证</option>
            <option value="proposal">方案中</option>
            <option value="negotiation">谈判中</option>
            <option value="won">成交</option>
            <option value="lost">丢失</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <textarea
            v-model="editForm.notes"
            class="form-input form-input--textarea"
            rows="3"
          ></textarea>
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="showEditDialog = false">
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="updating">
            {{ updating ? '保存中...' : '保存修改' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>

    <!-- Transition Dialog -->
    <Modal
      v-if="showTransitionDialog"
      title="阶段流转"
      @close="showTransitionDialog = false"
    >
      <form @submit.prevent="handleTransition">
        <div class="form-group">
          <label class="form-label">目标阶段 *</label>
          <select v-model="transitionForm.new_stage_code" class="form-input" required>
            <option value="">请选择阶段</option>
            <option v-for="stage in lifecycleStages" :key="stage.code" :value="stage.code">
              {{ stage.name }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">流转原因</label>
          <input
            v-model="transitionForm.reason"
            class="form-input"
            placeholder="请输入流转原因（可选）"
          />
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="showTransitionDialog = false">
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="transitioning">
            {{ transitioning ? '流转中...' : '确认流转' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLeadStore } from '@/stores/lead'
import type { Lead, UpdateLeadRequest } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Tabs from '@/components/common/Tabs.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const route = useRoute()
const router = useRouter()
const leadStore = useLeadStore()

const activeTab = ref('lifecycle')
const currentLead = ref<Lead | null>(null)
const currentLeadLoading = ref(false)
const lifecycleStages = ref<{ code: string; name: string }[]>([])
const showEditDialog = ref(false)
const showTransitionDialog = ref(false)
const updating = ref(false)
const transitioning = ref(false)

const editForm = ref<Partial<UpdateLeadRequest>>({})
const transitionForm = ref({
  new_stage_code: '',
  reason: '',
})

const tabs = [
  { value: 'lifecycle', label: '生命周期' },
  { value: 'conversations', label: '对话历史' },
  { value: 'activity', label: '活动记录' },
]

onMounted(async () => {
  const id = route.params.id as string
  await Promise.all([
    fetchLead(id),
    loadLifecycleStages(),
  ])
})

watch(() => route.params.id, async (newId) => {
  if (newId) await fetchLead(newId as string)
})

async function loadLifecycleStages() {
  try {
    const stages = await leadStore.fetchLifecycleStages()
    lifecycleStages.value = stages
  } catch (error) {
    console.error('Failed to load lifecycle stages:', error)
  }
}

async function fetchLead(id: string) {
  currentLeadLoading.value = true
  try {
    const lead = await leadStore.fetchLead(id)
    currentLead.value = lead
  } catch (error) {
    console.error('Failed to fetch lead:', error)
  } finally {
    currentLeadLoading.value = false
  }
}

function handleEdit() {
  if (!currentLead.value) return
  editForm.value = {
    lifecycle_stage_code: currentLead.value.lifecycle_stage_code || undefined,
    status: currentLead.value.status,
    notes: currentLead.value.notes || undefined,
  }
  showEditDialog.value = true
}

async function handleUpdate() {
  if (!currentLead.value) return
  updating.value = true
  try {
    await leadStore.updateLead(currentLead.value.id, editForm.value as UpdateLeadRequest)
    showEditDialog.value = false
    await fetchLead(route.params.id as string)
  } catch (error) {
    console.error('Failed to update lead:', error)
  } finally {
    updating.value = false
  }
}

async function handleTransition() {
  if (!currentLead.value || !transitionForm.value.new_stage_code) return
  transitioning.value = true
  try {
    await leadStore.transitionStage({
      lead_id: currentLead.value.id,
      new_stage_code: transitionForm.value.new_stage_code,
      reason: transitionForm.value.reason || undefined,
    })
    showTransitionDialog.value = false
    transitionForm.value = { new_stage_code: '', reason: '' }
  } catch (error) {
    console.error('Failed to transition stage:', error)
  } finally {
    transitioning.value = false
  }
}

async function handleDelete() {
  if (!currentLead.value) return
  if (!confirm('确定要删除这条线索吗？此操作不可恢复。')) return
  
  try {
    await leadStore.deleteLead(currentLead.value.id)
    router.push('/crm/leads')
  } catch (error) {
    console.error('Failed to delete lead:', error)
  }
}

function getStatusClass(status: string): string {
  const map: Record<string, string> = {
    new: 'info',
    contacted: 'running',
    qualified: 'warning',
    proposal: 'info',
    negotiation: 'warning',
    won: 'success',
    lost: 'error',
  }
  return map[status] || 'info'
}

function getStatusLabel(status: string): string {
  const map: Record<string, string> = {
    new: '新线索',
    contacted: '已联系',
    qualified: '已验证',
    proposal: '方案中',
    negotiation: '谈判中',
    won: '成交',
    lost: '丢失',
  }
  return map[status] || status
}

function getSourceLabel(source: string): string {
  const map: Record<string, string> = {
    web: '网站',
    referral: '推荐',
    ad: '广告',
    social: '社交',
    search: '搜索',
    conversation: '对话',
    other: '其他',
  }
  return map[source] || source || '-'
}

function getScoreColor(score?: number): string {
  if (!score) return '#94a3b8'
  if (score >= 80) return '#22c55e'
  if (score >= 60) return '#f59e0b'
  return '#ef4444'
}

function formatTime(time: string) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}
</script>

<style scoped>
.lead-detail-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-5);
}

.lead-header-card {
  margin-bottom: 0;
}

.lead-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-5);
}

.lead-header__info {
  flex: 1;
}

.lead-header__id {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  font-family: monospace;
}

.lead-header__meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.meta-separator {
  color: var(--color-text-muted);
}

.meta-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.lead-header__score {
  flex-shrink: 0;
}

.score-circle {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  border: 3px solid var(--score-color, #94a3b8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--color-bg-primary);
}

.score-circle__value {
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-bold);
  color: var(--score-color, #94a3b8);
  line-height: 1;
}

.score-circle__label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-1);
}

.lead-basic-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
  margin-top: var(--spacing-4);
  padding-top: var(--spacing-4);
  border-top: 1px solid var(--color-border);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--spacing-3);
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.info-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-value {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.lead-notes {
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.section-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 var(--spacing-2);
}

.notes-text {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.lead-tags-section {
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.tag-badge {
  display: inline-block;
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  background: #f0f0f0;
  color: #666;
}

.tabs-container {
  margin-top: var(--spacing-5);
}

.tab-content {
  margin-top: var(--spacing-4);
}

.card-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.empty-content {
  padding: var(--spacing-8) 0;
  text-align: center;
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
  padding: var(--spacing-4) 0;
}

.timeline-item {
  display: flex;
  gap: var(--spacing-4);
  position: relative;
}

.timeline-item__dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-primary);
  flex-shrink: 0;
  margin-top: var(--spacing-1);
  position: relative;
}

.timeline-item:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 20px;
  bottom: -20px;
  width: 2px;
  background: var(--color-border);
}

.timeline-item__content {
  flex: 1;
}

.timeline-item__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-1);
}

.timeline-item__stage {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.timeline-item__time {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.timeline-item__reason {
  margin: var(--spacing-1) 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.timeline-item__operator {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.conversations-empty,
.activity-empty {
  padding: var(--spacing-8) 0;
  text-align: center;
}

.form-group {
  margin-bottom: var(--spacing-4);
}

.form-label {
  display: block;
  margin-bottom: var(--spacing-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.form-input {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  transition: border-color var(--transition-fast);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.form-input--textarea {
  resize: vertical;
  min-height: 80px;
}

.text-muted {
  color: var(--color-text-muted);
}
</style>
