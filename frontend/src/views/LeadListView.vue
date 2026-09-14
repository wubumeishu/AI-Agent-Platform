<template>
  <div class="leads-view">
    <PageHeader title="线索管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建线索
        </button>
      </template>
    </PageHeader>

    <!-- Search and Filters -->
    <div class="search-bar">
      <div class="search-bar__input-wrapper">
        <span class="search-bar__icon">🔍</span>
        <input
          v-model="searchQuery"
          class="search-bar__input"
          placeholder="搜索线索..."
          @input="handleSearch"
        />
      </div>
      <div class="search-bar__filters">
        <select v-model="statusFilter" class="search-bar__select" @change="handleFilter">
          <option value="">所有状态</option>
          <option value="new">新线索</option>
          <option value="contacted">已联系</option>
          <option value="qualified">已验证</option>
          <option value="proposal">方案中</option>
          <option value="negotiation">谈判中</option>
          <option value="won">成交</option>
          <option value="lost">丢失</option>
        </select>
        <select v-model="stageFilter" class="search-bar__select" @change="handleFilter">
          <option value="">所有阶段</option>
          <option value="陌生">陌生</option>
          <option value="潜客">潜客</option>
          <option value="有效线索">有效线索</option>
          <option value="高意向">高意向</option>
          <option value="商机">商机</option>
        </select>
      </div>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && leads.length === 0"
      icon="🎯"
      title="暂无线索"
      description="开始添加你的第一个线索"
      :show-action="true"
      action-text="新建线索"
      @action="showCreateDialog = true"
    />

    <!-- Lead List Table -->
    <div v-else class="lead-table-wrapper">
      <table class="lead-table">
        <thead>
          <tr>
            <th class="col-status">状态</th>
            <th class="col-stage">生命周期阶段</th>
            <th class="col-score">意向评分</th>
            <th class="col-source">来源</th>
            <th class="col-customer">关联客户</th>
            <th class="col-tags">标签</th>
            <th class="col-time">创建时间</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="lead in leads"
            :key="lead.id"
            class="lead-row"
            @click="navigateToDetail(lead.id)"
          >
            <td class="col-status">
              <StatusBadge :status="getStatusClass(lead.status)" :label="getStatusLabel(lead.status)" />
            </td>
            <td class="col-stage">
              <span class="stage-text">{{ lead.lifecycle_stage_code || '-' }}</span>
            </td>
            <td class="col-score">
              <div class="score-wrapper">
                <div class="score-bar">
                  <div 
                    class="score-bar__fill" 
                    :style="{ width: `${lead.intent_score || 0}%`, backgroundColor: getScoreColor(lead.intent_score) }"
                  ></div>
                </div>
                <span class="score-value">{{ lead.intent_score ?? '-' }}</span>
              </div>
            </td>
            <td class="col-source">
              <span class="source-badge">{{ getSourceLabel(lead.source_type || 'other') }}</span>
            </td>
            <td class="col-customer">
              <span class="customer-text">{{ lead.customer_id ? '有客户' : '-' }}</span>
            </td>
            <td class="col-tags">
              <div class="tags-list">
                <span
                  v-for="tag in lead.tags.slice(0, 2)"
                  :key="tag.id"
                  class="tag-badge"
                  :style="{ backgroundColor: tag.color ? tag.color + '20' : '#f0f0f0' }"
                >
                  {{ tag.name }}
                </span>
                <span v-if="lead.tags.length > 2" class="tag-more">+{{ lead.tags.length - 2 }}</span>
              </div>
            </td>
            <td class="col-time">
              <span class="time-text">{{ formatTime(lead.created_at) }}</span>
            </td>
            <td class="col-actions" @click.stop>
              <button class="btn btn--ghost btn--sm" @click="handleEdit(lead)">编辑</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(lead)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div class="pagination" v-if="total > limit">
        <button
          class="pagination__btn"
          :disabled="skip <= 0"
          @click="handlePageChange(skip - limit)"
        >
          ← 上一页
        </button>
        <span class="pagination__info">
          第 {{ Math.floor(skip / limit) + 1 }} / {{ totalPages }} 页，共 {{ total }} 条
        </span>
        <button
          class="pagination__btn"
          :disabled="skip + limit >= total"
          @click="handlePageChange(skip + limit)"
        >
          下一页 →
        </button>
      </div>
    </div>

    <!-- Create/Edit Dialog -->
    <Modal
      v-if="showCreateDialog || showEditDialog"
      :title="editingLead ? '编辑线索' : '新建线索'"
      @close="closeDialog"
    >
      <form @submit.prevent="handleSubmit">
        <div class="form-group">
          <label class="form-label">生命周期阶段</label>
          <select v-model="formData.lifecycle_stage_code" class="form-input">
            <option value="">请选择阶段</option>
            <option v-for="stage in lifecycleStages" :key="stage.code" :value="stage.code">
              {{ stage.name }}
            </option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">状态</label>
          <select v-model="formData.status" class="form-input">
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
          <label class="form-label">来源类型</label>
          <select v-model="formData.source_type" class="form-input">
            <option value="">请选择来源</option>
            <option value="web">网站</option>
            <option value="referral">推荐</option>
            <option value="ad">广告</option>
            <option value="social">社交</option>
            <option value="search">搜索</option>
            <option value="conversation">对话</option>
            <option value="other">其他</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <textarea
            v-model="formData.notes"
            class="form-input form-input--textarea"
            placeholder="请输入备注信息（可选）"
            rows="3"
          ></textarea>
        </div>
        <ModalFooter>
          <button
            type="button"
            class="btn btn--ghost"
            @click="closeDialog"
          >
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="submitting">
            {{ submitting ? '保存中...' : (editingLead ? '保存修改' : '创建线索') }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useLeadStore } from '@/stores/lead'
import type { Lead, CreateLeadRequest, UpdateLeadRequest } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const leadStore = useLeadStore()

// List state
const leads = ref<Lead[]>([])
const total = ref(0)
const loading = ref(false)
const skip = ref(0)
const limit = ref(10)
const searchQuery = ref('')
const statusFilter = ref('')
const stageFilter = ref('')
const lifecycleStages = ref<{ code: string; name: string }[]>([])

// Dialog state
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingLead = ref<Lead | null>(null)
const submitting = ref(false)

const formData = ref<Partial<CreateLeadRequest & UpdateLeadRequest>>({
  lifecycle_stage_code: '',
  status: 'new',
  source_type: undefined,
  notes: '',
})

const totalPages = computed(() => Math.ceil(total.value / limit.value))

onMounted(async () => {
  await Promise.all([
    fetchLeads(),
    loadLifecycleStages(),
  ])
})

async function loadLifecycleStages() {
  try {
    const stages = await leadStore.fetchLifecycleStages()
    lifecycleStages.value = stages
  } catch (error) {
    console.error('Failed to load lifecycle stages:', error)
  }
}

async function fetchLeads() {
  loading.value = true
  try {
    const params: any = {
      skip: skip.value,
      limit: limit.value,
    }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    if (stageFilter.value) {
      params.lifecycle_stage = stageFilter.value
    }
    const data = await leadStore.fetchLeads(params)
    leads.value = data.data
    total.value = data.total
  } catch (error) {
    console.error('Failed to fetch leads:', error)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  skip.value = 0
  fetchLeads()
}

function handleFilter() {
  skip.value = 0
  fetchLeads()
}

function handlePageChange(newSkip: number) {
  skip.value = newSkip
  fetchLeads()
}

function navigateToDetail(id: string) {
  router.push(`/crm/leads/${id}`)
}

function handleEdit(lead: Lead) {
  editingLead.value = lead
  formData.value = {
    lifecycle_stage_code: lead.lifecycle_stage_code || undefined,
    status: lead.status,
    source_type: lead.source_type || undefined,
    notes: lead.notes || undefined,
  }
  showEditDialog.value = true
}

async function handleSubmit() {
  if (!formData.value.status) return
  
  submitting.value = true
  try {
    if (editingLead.value) {
      await leadStore.updateLead(editingLead.value.id, formData.value as UpdateLeadRequest)
    } else {
      await leadStore.createLead(formData.value as CreateLeadRequest)
    }
    closeDialog()
    await fetchLeads()
  } catch (error) {
    console.error('Failed to save lead:', error)
  } finally {
    submitting.value = false
  }
}

function handleDelete(lead: Lead) {
  if (confirm(`确定要删除这条线索吗？此操作不可恢复。`)) {
    leadStore.deleteLead(lead.id).then(() => {
      fetchLeads()
    }).catch((error) => {
      console.error('Failed to delete lead:', error)
    })
  }
}

function closeDialog() {
  showCreateDialog.value = false
  showEditDialog.value = false
  editingLead.value = null
  formData.value = {
    lifecycle_stage_code: '',
    status: 'new',
    source_type: undefined,
    notes: '',
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
  return new Date(time).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.search-bar {
  display: flex;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-5);
}

.search-bar__input-wrapper {
  flex: 1;
  position: relative;
  max-width: 400px;
}

.search-bar__icon {
  position: absolute;
  left: var(--spacing-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--font-size-lg);
}

.search-bar__input {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3) var(--spacing-2) calc(var(--spacing-3) * 2 + var(--font-size-lg));
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  transition: border-color var(--transition-fast);
}

.search-bar__input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.search-bar__filters {
  display: flex;
  gap: var(--spacing-2);
}

.search-bar__select {
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.lead-table-wrapper {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.lead-table {
  width: 100%;
  border-collapse: collapse;
}

.lead-table thead {
  background: var(--color-bg-tertiary);
}

.lead-table th {
  padding: var(--spacing-3) var(--spacing-4);
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.lead-table td {
  padding: var(--spacing-4);
  border-top: 1px solid var(--color-border);
  vertical-align: middle;
}

.lead-row {
  cursor: pointer;
  transition: background var(--transition-fast);
}

.lead-row:hover {
  background: var(--color-bg-tertiary);
}

.col-status {
  width: 100px;
}

.col-stage {
  width: 120px;
}

.stage-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.col-score {
  width: 120px;
}

.score-wrapper {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.score-bar {
  flex: 1;
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.score-bar__fill {
  height: 100%;
  border-radius: var(--radius-full);
  transition: width var(--transition-fast);
}

.score-value {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  min-width: 28px;
}

.col-source {
  width: 100px;
}

.source-badge {
  display: inline-block;
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.col-customer {
  width: 100px;
}

.customer-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.col-tags {
  width: 150px;
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-1);
}

.tag-badge {
  display: inline-block;
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  background: #f0f0f0;
  color: #666;
}

.tag-more {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.col-time {
  width: 120px;
}

.time-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.col-actions {
  width: 150px;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-4);
  border-top: 1px solid var(--color-border);
}

.pagination__btn {
  padding: var(--spacing-2) var(--spacing-4);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.pagination__btn:hover:not(:disabled) {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.pagination__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pagination__info {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
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
</style>
