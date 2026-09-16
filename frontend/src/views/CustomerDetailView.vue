<template>
  <div class="customer-detail-view" v-loading="currentCustomerLoading">
    <PageHeader title="客户详情" show-back>
      <template #actions>
        <button class="btn btn--ghost" :disabled="!currentCustomer" @click="handleEdit">编辑</button>
        <button class="btn btn--danger" :disabled="!currentCustomer" @click="pendingDelete = currentCustomer">删除</button>
      </template>
    </PageHeader>

    <!-- 加载失败 -->
    <div v-if="currentCustomerError" class="error-banner">
      <span class="error-banner__icon">⚠️</span>
      <span class="error-banner__text">加载客户失败：{{ currentCustomerError }}</span>
      <button class="btn btn--primary btn--sm" @click="retryFetch">重试</button>
    </div>

    <div v-else-if="!currentCustomer" class="empty-state">
      <p>客户不存在</p>
      <button class="btn btn--ghost" @click="router.push('/crm/customers')">返回列表</button>
    </div>

    <div v-else class="customer-detail-content">
      <!-- Customer Header Card -->
      <Card class="customer-header-card">
        <template #header>
          <div class="customer-header">
            <div class="customer-header__avatar">
              {{ getAvatarText(currentCustomer.name) }}
            </div>
            <div class="customer-header__info">
              <h2 class="customer-header__name">{{ currentCustomer.name }}</h2>
              <StatusBadge
                v-if="stageInfo"
                :status="stageInfo.status"
                :label="stageInfo.label"
              />
              <span v-else class="text-muted stage-empty">暂无阶段</span>
            </div>
            <div class="customer-header__meta">
              <span class="meta-item">📅 创建: {{ formatTime(currentCustomer.created_at) }}</span>
              <span class="meta-item">🔄 更新: {{ formatTime(currentCustomer.updated_at) }}</span>
            </div>
          </div>
        </template>

        <div class="customer-basic-info">
          <div class="info-row">
            <span class="info-label">邮箱:</span>
            <span class="info-value">{{ currentCustomer.email || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">手机号:</span>
            <span class="info-value">{{ currentCustomer.phone || '-' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">公司:</span>
            <span class="info-value">{{ currentCustomer.company || '-' }}</span>
          </div>
        </div>

        <!-- Tags -->
        <div class="customer-tags-section" v-if="currentCustomer.tags.length > 0">
          <h4 class="section-title">标签</h4>
          <div class="tags-list">
            <span
              v-for="tag in currentCustomer.tags"
              :key="tag.id"
              class="tag-badge"
              :style="tag.color ? { backgroundColor: tag.color + '22' } : {}"
            >
              {{ tag.name }}
            </span>
          </div>
        </div>
      </Card>

      <!-- Tabs -->
      <div class="tabs-container">
        <Tabs v-model="activeTab" :tabs="tabs" />
      </div>

      <!-- Tab Content -->
      <div class="tab-content">
        <!-- Identity Tab -->
        <div v-if="activeTab === 'identity'" class="tab-panel">
          <Card>
            <template #header>
              <div class="card-header-flex">
                <h3>平台身份</h3>
                <button class="btn btn--ghost btn--sm" @click="openAddIdentity">+ 添加身份</button>
              </div>
            </template>
            <div v-if="currentCustomer.identities && currentCustomer.identities.length === 0" class="empty-tab">
              <p class="text-muted">暂无平台身份信息</p>
            </div>
            <div v-else-if="!currentCustomer.identities" class="empty-tab">
              <p class="text-muted">无身份信息</p>
            </div>
            <div v-else class="identity-list">
              <div
                v-for="identity in currentCustomer.identities"
                :key="identity.id"
                class="identity-item"
              >
                <div class="identity-item__platform">
                  <span class="platform-icon">{{ getPlatformIcon(identity.platform) }}</span>
                  <span class="platform-name">{{ platformLabel(identity.platform) }}</span>
                </div>
                <div class="identity-item__info">
                  <div v-if="identity.platform_username" class="info-detail">
                    <span class="detail-label">账号:</span>
                    <span class="detail-value">{{ identity.platform_username }}</span>
                  </div>
                  <div v-if="identity.phone" class="info-detail">
                    <span class="detail-label">手机:</span>
                    <span class="detail-value">{{ identity.phone }}</span>
                  </div>
                  <div v-if="identity.email" class="info-detail">
                    <span class="detail-label">邮箱:</span>
                    <span class="detail-value">{{ identity.email }}</span>
                  </div>
                  <div v-if="identity.external_id" class="info-detail">
                    <span class="detail-label">外部ID:</span>
                    <span class="detail-value">{{ identity.external_id }}</span>
                  </div>
                </div>
                <div class="identity-item__meta">
                  <span class="confidence-badge" :class="getConfidenceClass(identity.confidence)">
                    {{ getConfidenceLabel(identity.confidence) }}
                  </span>
                  <span class="time-text">{{ formatTime(identity.created_at || '') }}</span>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <!-- Leads Tab -->
        <div v-if="activeTab === 'leads'" class="tab-panel">
          <Card>
            <template #header>
              <div class="card-header-flex">
                <h3>相关线索（Lead）</h3>
                <span v-if="leadsTotal" class="tab-count">共 {{ leadsTotal }} 条</span>
              </div>
            </template>
            <div v-if="leadsLoading" class="empty-tab"><LoadingState text="加载中..." /></div>
            <div v-else-if="leadsError" class="error-inline">
              <span>⚠️ 加载线索失败：{{ leadsError }}</span>
              <button class="btn btn--ghost btn--sm" @click="loadLeads">重试</button>
            </div>
            <div v-else-if="leads.length === 0" class="empty-tab">
              <p class="text-muted">暂无关联线索</p>
            </div>
            <div v-else class="lead-list">
              <div v-for="lead in leads" :key="lead.id" class="lead-item">
                <div class="lead-item__main">
                  <StatusBadge
                    :status="getLeadStageStatus(lead.lifecycle_stage_code)"
                    :label="getLeadStageLabel(lead.lifecycle_stage_code)"
                  />
                  <span class="lead-item__status">{{ leadStatusLabel(lead.status) }}</span>
                  <span v-if="lead.intent_score != null" class="lead-item__score">意向分 {{ lead.intent_score }}</span>
                </div>
                <div class="lead-item__meta">
                  <span v-if="lead.source_type" class="text-muted">来源: {{ lead.source_type }}</span>
                  <span class="text-muted">{{ formatTime(lead.updated_at) }}</span>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <!-- Activity Tab -->
        <div v-if="activeTab === 'activity'" class="tab-panel">
          <Card>
            <template #header>
              <div class="card-header-flex">
                <h3>活动记录</h3>
                <span v-if="activitiesTotal" class="tab-count">共 {{ activitiesTotal }} 条</span>
              </div>
            </template>
            <div v-if="activitiesLoading" class="empty-tab"><LoadingState text="加载中..." /></div>
            <div v-else-if="activitiesError" class="error-inline">
              <span>⚠️ 加载活动记录失败：{{ activitiesError }}</span>
              <button class="btn btn--ghost btn--sm" @click="loadActivities">重试</button>
            </div>
            <div v-else-if="activities.length === 0" class="empty-tab">
              <p class="text-muted">暂无活动记录</p>
            </div>
            <div v-else class="activity-list">
              <div v-for="activity in activities" :key="activity.id" class="activity-item">
                <div class="activity-item__type">{{ activity.activity_type }}</div>
                <div class="activity-item__body">
                  <div class="activity-item__title">{{ activity.title }}</div>
                  <div v-if="activity.description" class="activity-item__desc">{{ activity.description }}</div>
                  <div class="activity-item__time text-muted">{{ formatTime(activity.created_at || '') }}</div>
                </div>
              </div>
            </div>
          </Card>
        </div>

        <!-- Conversations Tab -->
        <div v-if="activeTab === 'conversations'" class="tab-panel">
          <Card>
            <template #header>
              <div class="card-header-flex">
                <h3>对话历史</h3>
                <span v-if="conversationsTotal" class="tab-count">共 {{ conversationsTotal }} 条</span>
              </div>
            </template>
            <div v-if="conversationsLoading" class="empty-tab"><LoadingState text="加载中..." /></div>
            <div v-else-if="conversationsError" class="error-inline">
              <span>⚠️ 加载对话历史失败：{{ conversationsError }}</span>
              <button class="btn btn--ghost btn--sm" @click="loadConversations">重试</button>
            </div>
            <div v-else-if="conversations.length === 0" class="empty-tab">
              <p class="text-muted">暂无对话记录</p>
            </div>
            <div v-else class="conversation-list">
              <div v-for="conv in conversations" :key="conv.id" class="conversation-item">
                <div class="conversation-item__main">
                  <span class="conversation-item__channel">{{ conv.channel || '未知渠道' }}</span>
                  <span class="conversation-item__subject">{{ conv.subject || '无主题' }}</span>
                </div>
                <div v-if="conv.summary" class="conversation-item__summary">{{ conv.summary }}</div>
                <div class="conversation-item__meta text-muted">
                  <span v-if="conv.message_count != null">{{ conv.message_count }} 条消息</span>
                  <span>{{ formatTime(conv.updated_at || conv.created_at || '') }}</span>
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <transition name="toast">
      <div
        v-if="toast.visible"
        class="customer-toast"
        :class="`customer-toast--${toast.type}`"
        role="status"
      >
        <span class="customer-toast__icon">{{ toast.type === 'error' ? '⚠️' : '✅' }}</span>
        <span class="customer-toast__text">{{ toast.message }}</span>
      </div>
    </transition>

    <!-- Edit Dialog -->
    <Modal v-if="showEditDialog" title="编辑客户" @close="closeEdit">
      <form novalidate @submit.prevent="handleUpdate">
        <div v-if="formError" class="form-error-banner">
          <span>⚠️</span>
          <span>{{ formError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">客户名称 *</label>
          <input
            v-model="editForm.name"
            class="form-input"
            :class="{ 'form-input--invalid': nameError }"
            placeholder="请输入客户名称"
            maxlength="100"
          />
          <span v-if="nameError" class="form-field-error">{{ nameError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">邮箱</label>
          <input
            v-model="editForm.email"
            class="form-input"
            :class="{ 'form-input--invalid': emailError }"
            type="email"
            placeholder="请输入邮箱（可选）"
          />
          <span v-if="emailError" class="form-field-error">{{ emailError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">手机号</label>
          <input
            v-model="editForm.phone"
            class="form-input"
            :class="{ 'form-input--invalid': phoneError }"
            type="tel"
            placeholder="请输入手机号（可选）"
          />
          <span v-if="phoneError" class="form-field-error">{{ phoneError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">公司</label>
          <input v-model="editForm.company" class="form-input" placeholder="请输入公司名称（可选）" maxlength="200" />
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="closeEdit">取消</button>
          <button type="submit" class="btn btn--primary" :disabled="updating">
            {{ updating ? '保存中...' : '保存修改' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>

    <!-- Add Identity Dialog -->
    <Modal v-if="showAddIdentity" title="添加平台身份" @close="showAddIdentity = false">
      <form novalidate @submit.prevent="handleAddIdentity">
        <div v-if="identityError" class="form-error-banner">
          <span>⚠️</span>
          <span>{{ identityError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">平台 *</label>
          <select v-model="identityForm.platform" class="form-input" :class="{ 'form-input--invalid': !identityForm.platform }">
            <option value="">请选择平台</option>
            <option value="wechat">微信</option>
            <option value="weibo">微博</option>
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
            <option value="bilibili">B站</option>
            <option value="other">其他</option>
          </select>
          <span v-if="!identityForm.platform" class="form-field-error">请选择平台</span>
        </div>
        <div class="form-group">
          <label class="form-label">平台账号ID *</label>
          <input
            v-model="identityForm.platform_account_id"
            class="form-input"
            :class="{ 'form-input--invalid': !identityForm.platform_account_id }"
            placeholder="平台账号唯一标识"
          />
          <span v-if="!identityForm.platform_account_id" class="form-field-error">平台账号ID不能为空</span>
        </div>
        <div class="form-group">
          <label class="form-label">平台用户名</label>
          <input v-model="identityForm.platform_username" class="form-input" placeholder="平台用户名/昵称（可选）" />
        </div>
        <div class="form-group">
          <label class="form-label">手机号</label>
          <input v-model="identityForm.phone" class="form-input" type="tel" placeholder="手机号（可选）" />
        </div>
        <div class="form-group">
          <label class="form-label">邮箱</label>
          <input v-model="identityForm.email" class="form-input" type="email" placeholder="邮箱（可选）" />
        </div>
        <div class="form-group">
          <label class="form-label">外部系统ID</label>
          <input v-model="identityForm.external_id" class="form-input" placeholder="外部系统ID（可选）" />
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="showAddIdentity = false">取消</button>
          <button type="submit" class="btn btn--primary" :disabled="addingIdentity">
            {{ addingIdentity ? '添加中...' : '添加身份' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>

    <!-- Delete Confirm Dialog -->
    <Modal v-if="pendingDelete" title="删除客户" width="440px" @close="pendingDelete = null">
      <div class="customer-confirm">
        <div class="customer-confirm__icon">🗑</div>
        <p class="customer-confirm__text">
          确定要删除客户
          <strong>「{{ pendingDelete.name }}」</strong>吗？
          <div class="customer-confirm__warn">此操作不可恢复，请谨慎操作。</div>
        </p>
        <div class="customer-confirm__footer">
          <button class="btn btn--ghost" @click="pendingDelete = null">取消</button>
          <button class="btn btn--danger" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCustomerStore } from '@/stores/customer'
import { useLeadStore } from '@/stores/lead'
import type { Customer, CustomerIdentityRequest, Lead, LifecycleStage } from '@/api/types'
import type { CustomerActivity, CustomerConversation } from '@/api/customer'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Tabs from '@/components/common/Tabs.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'
import LoadingState from '@/components/common/LoadingState.vue'

const route = useRoute()
const router = useRouter()
const customerStore = useCustomerStore()
const leadStore = useLeadStore()

const activeTab = ref('identity')
const currentCustomer = computed(() => customerStore.currentCustomer)
const currentCustomerLoading = computed(() => customerStore.currentCustomerLoading)
const currentCustomerError = computed(() => customerStore.currentCustomerError)
const showEditDialog = ref(false)
const showAddIdentity = ref(false)
const updating = ref(false)
const addingIdentity = ref(false)
const deleting = ref(false)
const pendingDelete = ref<Customer | null>(null)
const formError = ref('')
const identityError = ref('')

const editForm = ref({
  name: '',
  email: '',
  phone: '',
  company: '',
})

const identityForm = ref<CustomerIdentityRequest>({
  platform: '',
  platform_account_id: '',
})

const toast = ref<{ visible: boolean; type: 'success' | 'error'; message: string }>({
  visible: false,
  type: 'success',
  message: '',
})
let toastTimer: ReturnType<typeof setTimeout> | null = null

function showToast(type: 'success' | 'error', message: string) {
  toast.value = { visible: true, type, message }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => {
    toast.value.visible = false
  }, 3000)
}

// Tab data
const leads = ref<Lead[]>([])
const leadsLoading = ref(false)
const leadsError = ref('')
const leadsTotal = ref(0)
const activities = ref<CustomerActivity[]>([])
const activitiesLoading = ref(false)
const activitiesError = ref('')
const activitiesTotal = ref(0)
const conversations = ref<CustomerConversation[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const conversationsTotal = ref(0)

// Lifecycle stages
const stages = ref<LifecycleStage[]>([])

// Tab config
const tabs = [
  { value: 'identity', label: '平台身份' },
  { value: 'leads', label: '相关线索' },
  { value: 'activity', label: '活动记录' },
  { value: 'conversations', label: '对话历史' },
]

// 前端校验
const nameError = computed(() => (editForm.value.name.trim() ? '' : '客户名称不能为空'))
const emailError = computed(() => {
  if (!editForm.value.email.trim()) return ''
  return /^\S+@\S+\.\S+$/.test(editForm.value.email.trim()) ? '' : '邮箱格式不正确'
})
const phoneError = computed(() => {
  if (!editForm.value.phone.trim()) return ''
  return /^[\d+\-() ]{5,20}$/.test(editForm.value.phone.trim()) ? '' : '手机号格式不正确'
})

// 阶段信息：基于 lifecycle stages + 客户线索（Customer 实体无 stage 字段，阶段由关联 Lead 推导）
const stageInfo = computed(() => {
  if (!currentCustomer.value) return null
  const stageCode = leads.value[0]?.lifecycle_stage_code
  if (!stageCode) return null
  const found = stages.value.find(s => s.code === stageCode)
  return {
    status: stageStatus(stageCode, found),
    label: found ? found.name : stageCode,
  }
})

function stageStatus(stageCode: string, stage?: LifecycleStage): string {
  // 基于阶段名称关键字给出状态颜色
  if (stage) {
    const s = stage.name + stageCode
    if (s.includes('成交') || s.includes('客户') || s.includes('won')) return 'success'
    if (s.includes('流失') || s.includes('churned') || s.includes('lost')) return 'error'
    if (s.includes('高意向') || s.includes('商机') || s.includes('negotiation')) return 'warning'
  }
  return 'info'
}

onMounted(async () => {
  const id = route.params.id as string
  await loadStages()
  await fetchCustomer(id)
  // 阶段徽章依赖第一条 Lead 的生命周期阶段，故提前加载；活动/对话按需懒加载
  await loadLeads()
})

onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer)
})

watch(
  () => route.params.id,
  async (newId, oldId) => {
    if (newId && newId !== oldId) {
      activeTab.value = 'identity'
      await fetchCustomer(newId as string)
    }
  },
)

async function fetchCustomer(id: string) {
  customerStore.clearCurrentCustomer()
  try {
    await customerStore.fetchCustomer(id)
  } catch (error) {
    console.error('Failed to fetch customer:', error)
    // error is captured in currentCustomerError by the store
  }
}

function retryFetch() {
  const id = route.params.id as string
  fetchCustomer(id)
}

async function loadStages() {
  try {
    stages.value = await leadStore.fetchLifecycleStages()
  } catch (error) {
    console.error('Failed to load lifecycle stages:', error)
  }
}

async function loadLeads() {
  const id = route.params.id as string
  if (!id) return
  leadsLoading.value = true
  leadsError.value = ''
  try {
    const data = await customerStore.fetchCustomerLeads(id)
    leads.value = data || []
    leadsTotal.value = leads.value.length
  } catch (error) {
    leadsError.value = error instanceof Error && error.message ? error.message : '请求失败'
    console.error('Failed to fetch customer leads:', error)
  } finally {
    leadsLoading.value = false
  }
}

async function loadActivities() {
  const id = route.params.id as string
  if (!id) return
  activitiesLoading.value = true
  activitiesError.value = ''
  try {
    const data = await customerStore.fetchCustomerActivities(id)
    activities.value = data || []
    activitiesTotal.value = activities.value.length
  } catch (error) {
    activitiesError.value = error instanceof Error && error.message ? error.message : '请求失败'
    console.error('Failed to fetch activities:', error)
  } finally {
    activitiesLoading.value = false
  }
}

async function loadConversations() {
  const id = route.params.id as string
  if (!id) return
  conversationsLoading.value = true
  conversationsError.value = ''
  try {
    const data = await customerStore.fetchCustomerConversations(id)
    conversations.value = data || []
    conversationsTotal.value = conversations.value.length
  } catch (error) {
    conversationsError.value = error instanceof Error && error.message ? error.message : '请求失败'
    console.error('Failed to fetch conversations:', error)
  } finally {
    conversationsLoading.value = false
  }
}

// 切换 tab 时按需加载
watch(activeTab, async tab => {
  const id = route.params.id as string
  if (!id) return
  if (tab === 'leads' && leads.value.length === 0 && !leadsError.value) await loadLeads()
  if (tab === 'activity' && activities.value.length === 0 && !activitiesError.value) await loadActivities()
  if (tab === 'conversations' && conversations.value.length === 0 && !conversationsError.value)
    await loadConversations()
})

function handleEdit() {
  if (!currentCustomer.value) return
  editForm.value = {
    name: currentCustomer.value.name,
    email: currentCustomer.value.email || '',
    phone: currentCustomer.value.phone || '',
    company: currentCustomer.value.company || '',
  }
  formError.value = ''
  showEditDialog.value = true
}

function closeEdit() {
  showEditDialog.value = false
  formError.value = ''
}

async function handleUpdate() {
  if (!currentCustomer.value) return
  if (nameError.value || emailError.value || phoneError.value) {
    formError.value = '请修正表单中标记的字段后再提交'
    return
  }
  updating.value = true
  formError.value = ''
  try {
    await customerStore.updateCustomer(currentCustomer.value.id, {
      name: editForm.value.name.trim(),
      email: editForm.value.email.trim() || undefined,
      phone: editForm.value.phone.trim() || undefined,
      company: editForm.value.company.trim() || undefined,
    })
    showToast('success', '客户已更新')
    closeEdit()
    await fetchCustomer(route.params.id as string)
  } catch (error) {
    formError.value = error instanceof Error && error.message ? error.message : '保存失败'
    console.error('Failed to update customer:', error)
  } finally {
    updating.value = false
  }
}

function openAddIdentity() {
  identityForm.value = {
    platform: '',
    platform_account_id: '',
  }
  identityError.value = ''
  showAddIdentity.value = true
}

async function handleAddIdentity() {
  if (!currentCustomer.value || !identityForm.value.platform || !identityForm.value.platform_account_id) {
    identityError.value = '请填写平台与平台账号ID'
    return
  }
  addingIdentity.value = true
  identityError.value = ''
  try {
    await customerStore.addCustomerIdentity(currentCustomer.value.id, {
      platform: identityForm.value.platform,
      platform_account_id: identityForm.value.platform_account_id.trim(),
      platform_username: identityForm.value.platform_username?.trim() || undefined,
      phone: identityForm.value.phone?.trim() || undefined,
      email: identityForm.value.email?.trim() || undefined,
      external_id: identityForm.value.external_id?.trim() || undefined,
    })
    showToast('success', '身份已添加')
    showAddIdentity.value = false
    // 刷新当前客户以拉取最新身份
    await fetchCustomer(route.params.id as string)
  } catch (error) {
    identityError.value = error instanceof Error && error.message ? error.message : '添加身份失败'
    console.error('Failed to add identity:', error)
  } finally {
    addingIdentity.value = false
  }
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  deleting.value = true
  try {
    await customerStore.deleteCustomer(pendingDelete.value.id)
    showToast('success', '客户已删除')
    pendingDelete.value = null
    router.push('/crm/customers')
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : '删除失败'
    showToast('error', message)
    console.error('Failed to delete customer:', error)
  } finally {
    deleting.value = false
  }
}

// 辅助
function getAvatarText(name: string): string {
  return name ? name.charAt(0).toUpperCase() : '?'
}

function getPlatformIcon(platform: string): string {
  const icons: Record<string, string> = {
    wechat: '💬',
    weibo: '📢',
    douyin: '🎵',
    xiaohongshu: '📕',
    bilibili: '📺',
    other: '🌐',
  }
  return icons[platform] || '🌐'
}

function platformLabel(platform: string): string {
  const labels: Record<string, string> = {
    wechat: '微信',
    weibo: '微博',
    douyin: '抖音',
    xiaohongshu: '小红书',
    bilibili: 'B站',
    other: '其他',
  }
  return labels[platform] || platform
}

function getLeadStageStatus(stageCode?: string): string {
  if (!stageCode) return 'info'
  return stageStatus(stageCode, stages.value.find(s => s.code === stageCode))
}

function getLeadStageLabel(stageCode?: string): string {
  if (!stageCode) return '-'
  const found = stages.value.find(s => s.code === stageCode)
  return found ? found.name : stageCode
}

function leadStatusLabel(status?: string): string {
  const labels: Record<string, string> = {
    new: '新线索',
    contacted: '已联系',
    qualified: '已验证',
    proposal: '已提案',
    negotiation: '谈判中',
    won: '已成交',
    lost: '已流失',
  }
  return labels[status || ''] || status || '-'
}

function getConfidenceLabel(confidence?: string): string {
  const labels: Record<string, string> = {
    high: '高置信',
    medium: '中置信',
    low: '低置信',
  }
  return labels[confidence || ''] || (confidence || '-')
}

function getConfidenceClass(confidence?: string): string {
  const classes: Record<string, string> = {
    high: 'confidence-high',
    medium: 'confidence-medium',
    low: 'confidence-low',
  }
  return classes[confidence || ''] || ''
}

function formatTime(time?: string): string {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}
</script>

<style scoped>
.customer-detail-content {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-5);
}

.customer-header-card {
  margin-bottom: 0;
}

.customer-header {
  display: flex;
  align-items: flex-start;
  gap: var(--spacing-5);
}

.customer-header__avatar {
  width: 72px;
  height: 72px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-3xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.customer-header__info {
  flex: 1;
}

.customer-header__name {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-2xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.stage-empty {
  font-size: var(--font-size-xs);
}

.customer-header__meta {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
  margin-top: var(--spacing-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.customer-basic-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--spacing-3);
  margin-top: var(--spacing-4);
  padding-top: var(--spacing-4);
  border-top: 1px solid var(--color-border);
}

.info-row {
  display: flex;
  gap: var(--spacing-2);
}

.info-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  min-width: 60px;
}

.info-value {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.customer-tags-section {
  margin-top: var(--spacing-4);
  padding-top: var(--spacing-4);
  border-top: 1px solid var(--color-border);
}

.section-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0 0 var(--spacing-3);
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
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.error-banner {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  color: #991b1b;
  font-size: var(--font-size-sm);
  margin-bottom: var(--spacing-4);
}

.error-banner__icon {
  font-size: var(--font-size-lg);
}

.error-banner__text {
  flex: 1;
}

.empty-state {
  padding: var(--spacing-8);
  text-align: center;
  color: var(--color-text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
  align-items: center;
}

.tabs-container {
  margin-top: var(--spacing-5);
}

.tab-content {
  margin-top: var(--spacing-4);
}

.tab-count {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.card-header-flex {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.empty-tab {
  padding: var(--spacing-8) 0;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-2);
}

.error-inline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-3);
  padding: var(--spacing-3);
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  color: #991b1b;
  font-size: var(--font-size-sm);
}

.identity-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.identity-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.identity-item__platform {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  min-width: 120px;
}

.platform-icon {
  font-size: var(--font-size-xl);
}

.platform-name {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.identity-item__info {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-3);
}

.info-detail {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.detail-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.detail-value {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.identity-item__meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--spacing-1);
}

.confidence-badge {
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.confidence-high {
  background: #dcfce7;
  color: #16a34a;
}

.confidence-medium {
  background: #fef9c3;
  color: #ca8a04;
}

.confidence-low {
  background: #fee2e2;
  color: #dc2626;
}

.time-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.text-muted {
  color: var(--color-text-muted);
}

/* Lead list */
.lead-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.lead-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-3);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.lead-item__main {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.lead-item__status {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.lead-item__score {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.lead-item__meta {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
  font-size: var(--font-size-xs);
  text-align: right;
}

/* Activity list */
.activity-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.activity-item {
  display: flex;
  gap: var(--spacing-3);
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.activity-item__type {
  flex-shrink: 0;
  min-width: 80px;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-primary);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-primary-light);
  border-radius: var(--radius-sm);
  text-align: center;
  height: fit-content;
}

.activity-item__body {
  flex: 1;
}

.activity-item__title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.activity-item__desc {
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.activity-item__time {
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
}

/* Conversation list */
.conversation-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.conversation-item {
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.conversation-item__main {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.conversation-item__channel {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-primary);
  background: var(--color-primary-light);
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
}

.conversation-item__subject {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.conversation-item__summary {
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.conversation-item__meta {
  margin-top: var(--spacing-2);
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-xs);
}

/* Toast */
.customer-toast {
  position: fixed;
  top: var(--spacing-4);
  left: 50%;
  transform: translateX(-50%);
  z-index: 1100;
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-4);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  box-shadow: var(--shadow-lg);
}

.customer-toast--success {
  background: var(--color-success-light);
  color: #166534;
  border: 1px solid var(--color-success);
}

.customer-toast--error {
  background: var(--color-error-light);
  color: #991b1b;
  border: 1px solid var(--color-error);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}

/* Form */
.form-error-banner {
  display: flex;
  gap: var(--spacing-2);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  color: #991b1b;
  font-size: var(--font-size-sm);
  margin-bottom: var(--spacing-4);
}

.form-input--invalid {
  border-color: var(--color-error) !important;
}

.form-field-error {
  display: block;
  margin-top: var(--spacing-1);
  font-size: var(--font-size-xs);
  color: var(--color-error);
}

/* Delete confirm */
.customer-confirm {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.customer-confirm__icon {
  font-size: 34px;
  text-align: center;
}

.customer-confirm__text {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  line-height: 1.7;
  text-align: center;
}

.customer-confirm__warn {
  margin-top: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: #b91c1c;
  background: var(--color-error-light);
  border: 1px solid #fecaca;
  border-radius: var(--radius-md);
  padding: var(--spacing-2) var(--spacing-3);
  text-align: center;
}

.customer-confirm__footer {
  display: flex;
  justify-content: center;
  gap: 10px;
}
</style>
