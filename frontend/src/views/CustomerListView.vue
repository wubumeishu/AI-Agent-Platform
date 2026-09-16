<template>
  <div class="customers-view">
    <PageHeader title="客户管理">
      <template #actions>
        <button class="btn btn--primary" @click="openCreateDialog">
          + 新建客户
        </button>
      </template>
    </PageHeader>

    <!-- 成功/失败 提示条 -->
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

    <!-- Search and Filters -->
    <div class="search-bar">
      <div class="search-bar__input-wrapper">
        <span class="search-bar__icon">🔍</span>
        <input
          v-model="searchQuery"
          class="search-bar__input"
          placeholder="搜索客户名称..."
          @input="handleSearch"
          @keyup.enter="handleSearch"
        />
      </div>
      <div class="search-bar__filters">
        <select v-model="stageFilter" class="search-bar__select" @change="handleFilter">
          <option value="">所有阶段</option>
          <option v-for="stage in lifecycleStages" :key="stage.code" :value="stage.code">
            {{ stage.name }}
          </option>
        </select>
      </div>
      <button class="btn btn--ghost" @click="handleSearch">查询</button>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading && customers.length === 0" full-screen />

    <!-- 加载失败 -->
    <div v-else-if="listError" class="error-banner">
      <span class="error-banner__icon">⚠️</span>
      <span class="error-banner__text">加载客户列表失败：{{ listError }}</span>
      <button class="btn btn--primary btn--sm" @click="fetchCustomers">重试</button>
    </div>

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && customers.length === 0"
      icon="👥"
      title="暂无客户"
      description="开始添加你的第一个客户"
      :show-action="true"
      action-text="新建客户"
      @action="openCreateDialog"
    />

    <!-- Customer List Table -->
    <div v-else class="customer-table-wrapper">
      <table class="customer-table">
        <thead>
          <tr>
            <th class="col-name">客户名称</th>
            <th class="col-contact">联系方式</th>
            <th class="col-company">公司</th>
            <th class="col-identities">平台身份</th>
            <th class="col-tags">标签</th>
            <th class="col-time">更新时间</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="customer in customers"
            :key="customer.id"
            class="customer-row"
            @click="navigateToDetail(customer.id)"
          >
            <td class="col-name">
              <div class="customer-name">
                <div class="customer-avatar">
                  {{ getAvatarText(customer.name) }}
                </div>
                <span class="customer-name-text">{{ customer.name }}</span>
              </div>
            </td>
            <td class="col-contact">
              <div class="contact-info">
                <span v-if="customer.phone" class="contact-item">📱 {{ customer.phone }}</span>
                <span v-if="customer.email" class="contact-item">✉️ {{ customer.email }}</span>
                <span v-if="!customer.phone && !customer.email" class="text-muted">-</span>
              </div>
            </td>
            <td class="col-company">
              <span class="company-text">{{ customer.company || '-' }}</span>
            </td>
            <td class="col-identities">
              <span class="leads-count">{{ customer.identities_count || 0 }} 个</span>
            </td>
            <td class="col-tags">
              <div class="tags-list">
                <span
                  v-for="tag in customer.tags.slice(0, 2)"
                  :key="tag.id"
                  class="tag-badge"
                >
                  {{ tag.name }}
                </span>
                <span v-if="customer.tags.length > 2" class="tag-more">+{{ customer.tags.length - 2 }}</span>
                <span v-if="customer.tags.length === 0" class="text-muted">-</span>
              </div>
            </td>
            <td class="col-time">
              <span class="time-text">{{ formatTime(customer.updated_at) }}</span>
            </td>
            <td class="col-actions" @click.stop>
              <button class="btn btn--ghost btn--sm" @click="handleEdit(customer)">编辑</button>
              <button class="btn btn--danger btn--sm" @click="pendingDelete = customer">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div class="pagination" v-if="total > 0">
        <button
          class="pagination__btn"
          :disabled="currentPage <= 1"
          @click="handlePageChange(currentPage - 1)"
        >
          ← 上一页
        </button>
        <span class="pagination__info">
          第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条
        </span>
        <button
          class="pagination__btn"
          :disabled="currentPage >= totalPages"
          @click="handlePageChange(currentPage + 1)"
        >
          下一页 →
        </button>
      </div>
    </div>

    <!-- Create/Edit Dialog -->
    <Modal
      v-if="showCreateDialog || showEditDialog"
      :title="editingCustomer ? '编辑客户' : '新建客户'"
      @close="closeDialog"
    >
      <form novalidate @submit.prevent="handleSubmit">
        <div v-if="formError" class="form-error-banner">
          <span>⚠️</span>
          <span>{{ formError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">客户名称 *</label>
          <input
            v-model="formData.name"
            class="form-input"
            :class="{ 'form-input--invalid': nameError }"
            placeholder="请输入客户名称"
            maxlength="100"
            required
          />
          <span v-if="nameError" class="form-field-error">{{ nameError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">邮箱</label>
          <input
            v-model="formData.email"
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
            v-model="formData.phone"
            class="form-input"
            :class="{ 'form-input--invalid': phoneError }"
            type="tel"
            placeholder="请输入手机号（可选）"
          />
          <span v-if="phoneError" class="form-field-error">{{ phoneError }}</span>
        </div>
        <div class="form-group">
          <label class="form-label">公司</label>
          <input
            v-model="formData.company"
            class="form-input"
            placeholder="请输入公司名称（可选）"
            maxlength="200"
          />
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="closeDialog">
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="submitting">
            {{ submitting ? '保存中...' : (editingCustomer ? '保存修改' : '创建客户') }}
          </button>
        </ModalFooter>
      </form>
    </Modal>

    <!-- Delete Confirm Dialog -->
    <Modal v-if="pendingDelete" title="删除客户" width="440px" @close="cancelDelete">
      <div class="customer-confirm">
        <div class="customer-confirm__icon">🗑</div>
        <p class="customer-confirm__text">
          确定要删除客户
          <strong>「{{ pendingDelete.name }}」</strong>吗？
          <div class="customer-confirm__warn">此操作不可恢复，请谨慎操作。</div>
        </p>
        <div class="customer-confirm__footer">
          <button class="btn btn--ghost" @click="cancelDelete">取消</button>
          <button
            class="btn btn--danger"
            :disabled="deleting"
            @click="confirmDelete"
          >
            {{ deleting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useCustomerStore } from '@/stores/customer'
import { useLeadStore } from '@/stores/lead'
import type { Customer } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const customerStore = useCustomerStore()
const leadStore = useLeadStore()

// 列表状态
const PAGE_SIZE = 10
const customers = ref<Customer[]>([])
const total = ref(0)
const loading = ref(false)
const listError = ref('')
const currentPage = ref(1)
const searchQuery = ref('')
const stageFilter = ref('')
const lifecycleStages = ref<{ code: string; name: string }[]>([])

// Toast
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

// 弹窗状态
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingCustomer = ref<Customer | null>(null)
const submitting = ref(false)
const pendingDelete = ref<Customer | null>(null)
const deleting = ref(false)

const formData = ref<{ name: string; email: string; phone: string; company: string }>({
  name: '',
  email: '',
  phone: '',
  company: '',
})

// 前端校验
const nameError = computed(() => {
  if (formData.value.name.trim()) return ''
  return '客户名称不能为空'
})

const emailError = computed(() => {
  if (!formData.value.email.trim()) return ''
  return /^\S+@\S+\.\S+$/.test(formData.value.email.trim()) ? '' : '邮箱格式不正确'
})

const phoneError = computed(() => {
  if (!formData.value.phone.trim()) return ''
  return /^[\d+\-() ]{5,20}$/.test(formData.value.phone.trim()) ? '' : '手机号格式不正确'
})

const formError = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

onMounted(async () => {
  await Promise.all([fetchCustomers(), loadLifecycleStages()])
})

async function loadLifecycleStages() {
  try {
    lifecycleStages.value = await leadStore.fetchLifecycleStages()
  } catch (error) {
    // 阶段加载失败不阻塞列表，仅记录
    console.error('Failed to load lifecycle stages:', error)
  }
}

async function fetchCustomers() {
  loading.value = true
  listError.value = ''
  try {
    const params = {
      skip: (currentPage.value - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      name: searchQuery.value.trim() || undefined,
      stage_code: stageFilter.value || undefined,
    }
    const data = await customerStore.fetchCustomers(params)
    customers.value = data.data
    total.value = data.total
  } catch (error) {
    console.error('Failed to fetch customers:', error)
    listError.value = error instanceof Error && error.message ? error.message : '请求失败'
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchCustomers()
}

function handleFilter() {
  currentPage.value = 1
  fetchCustomers()
}

function handlePageChange(page: number) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
  fetchCustomers()
}

function navigateToDetail(id: string) {
  router.push(`/crm/customers/${id}`)
}

function openCreateDialog() {
  editingCustomer.value = null
  formData.value = { name: '', email: '', phone: '', company: '' }
  formError.value = ''
  showCreateDialog.value = true
}

function handleEdit(customer: Customer) {
  editingCustomer.value = customer
  formData.value = {
    name: customer.name,
    email: customer.email || '',
    phone: customer.phone || '',
    company: customer.company || '',
  }
  formError.value = ''
  showEditDialog.value = true
}

function validateForm(): boolean {
  if (nameError.value || emailError.value || phoneError.value) {
    formError.value = '请修正表单中标记的字段后再提交'
    return false
  }
  return true
}

async function handleSubmit() {
  if (!validateForm()) return

  submitting.value = true
  formError.value = ''
  try {
    if (editingCustomer.value) {
      await customerStore.updateCustomer(editingCustomer.value.id, {
        name: formData.value.name.trim(),
        email: formData.value.email.trim() || undefined,
        phone: formData.value.phone.trim() || undefined,
        company: formData.value.company.trim() || undefined,
      })
      showToast('success', '客户已更新')
    } else {
      await customerStore.createCustomer({
        name: formData.value.name.trim(),
        email: formData.value.email.trim() || undefined,
        phone: formData.value.phone.trim() || undefined,
        company: formData.value.company.trim() || undefined,
      })
      showToast('success', '客户已创建')
    }
    closeDialog()
    await fetchCustomers()
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : '保存失败'
    formError.value = message
    console.error('Failed to save customer:', error)
  } finally {
    submitting.value = false
  }
}

function cancelDelete() {
  pendingDelete.value = null
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  deleting.value = true
  try {
    await customerStore.deleteCustomer(pendingDelete.value.id)
    showToast('success', '客户已删除')
    pendingDelete.value = null
    // 若删完本页最后一条，回退到上一页
    const remaining = total.value - 1
    if (customers.value.length === 1 && currentPage.value > 1) {
      currentPage.value -= 1
    }
    if (remaining <= 0) {
      total.value = 0
      customers.value = []
    }
    await fetchCustomers()
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : '删除失败'
    showToast('error', message)
    console.error('Failed to delete customer:', error)
  } finally {
    deleting.value = false
  }
}

function closeDialog() {
  showCreateDialog.value = false
  showEditDialog.value = false
  editingCustomer.value = null
  formData.value = { name: '', email: '', phone: '', company: '' }
  formError.value = ''
}

function getAvatarText(name: string): string {
  return name ? name.charAt(0).toUpperCase() : '?'
}

function formatTime(time?: string) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}
</script>

<style scoped>
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

.search-bar__select {
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.customer-table-wrapper {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.customer-table {
  width: 100%;
  border-collapse: collapse;
}

.customer-table thead {
  background: var(--color-bg-tertiary);
}

.customer-table th {
  padding: var(--spacing-3) var(--spacing-4);
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.customer-table td {
  padding: var(--spacing-4);
  border-top: 1px solid var(--color-border);
  vertical-align: middle;
}

.customer-row {
  cursor: pointer;
  transition: background var(--transition-fast);
}

.customer-row:hover {
  background: var(--color-bg-tertiary);
}

.col-name {
  width: 200px;
}

.customer-name {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.customer-avatar {
  width: 36px;
  height: 36px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
  flex-shrink: 0;
}

.customer-name-text {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.col-contact {
  width: 180px;
}

.contact-info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.contact-item {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.col-company {
  width: 150px;
}

.company-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.col-identities {
  width: 100px;
}

.leads-count {
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
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.tag-more {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.col-time {
  width: 150px;
}

.time-text {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.col-actions {
  width: 150px;
  white-space: nowrap;
}

.col-actions .btn {
  margin-right: var(--spacing-2);
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

.text-muted {
  color: var(--color-text-muted);
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
