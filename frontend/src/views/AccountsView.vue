<template>
  <div class="accounts-view">
    <PageHeader title="账号管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建账号
        </button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="filters-bar">
      <div class="filters-bar__left">
        <select v-model="filterPlatform" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部平台</option>
          <option v-for="platform in platforms" :key="platform.id" :value="platform.code">
            {{ platform.name }}
          </option>
        </select>
        <select v-model="filterStatus" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部状态</option>
          <option value="connected">已连接</option>
          <option value="disconnected">未连接</option>
          <option value="failed">失败</option>
        </select>
      </div>
      <div class="filters-bar__right">
        <span class="text-muted">{{ filteredAccounts.length }} 个账号</span>
      </div>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && filteredAccounts.length === 0"
      icon="👤"
      title="暂无账号"
      description="添加你的社交媒体账号"
      :show-action="true"
      action-text="新建账号"
      @action="showCreateDialog = true"
    />

    <!-- Account List -->
    <div v-else class="account-grid">
      <AccountCard
        v-for="account in filteredAccounts"
        :key="account.id"
        :account="account"
        @click="navigateToDetail(account.id)"
        @test="testConnection(account.id)"
      />
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建账号"
      @close="showCreateDialog = false"
    >
      <AccountCreateDialog
        :platforms="platforms"
        @submit="handleCreate"
        @cancel="showCreateDialog = false"
        :creating="creating"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountStore } from '@/stores/account'
import { usePlatformStore } from '@/stores/platform'
import type { Account, Platform } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import AccountCard from '@/components/account/AccountCard.vue'
import { showToast } from '@/utils/toast'
import AccountCreateDialog from '@/components/account/AccountCreateDialog.vue'

const router = useRouter()
const accountStore = useAccountStore()
const platformStore = usePlatformStore()

const accounts = ref<Account[]>([])
const platforms = ref<Platform[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

// 筛选状态
const filterPlatform = ref('')
const filterStatus = ref('')

// 筛选后的账号列表
const filteredAccounts = computed(() => {
  return accounts.value.filter(account => {
    if (filterPlatform.value && account.platform_id !== filterPlatform.value) return false
    if (filterStatus.value && account.status !== filterStatus.value) return false
    return true
  })
})

onMounted(async () => {
  await Promise.all([
    fetchPlatforms(),
    fetchAccounts()
  ])
})

async function fetchPlatforms() {
  try {
    const data = await platformStore.fetchPlatforms()
    platforms.value = data.items
  } catch (error) {
    console.error('Failed to fetch platforms:', error)
  }
}

async function fetchAccounts() {
  loading.value = true
  try {
    const params: any = {}
    if (filterPlatform.value) params.platform = filterPlatform.value
    if (filterStatus.value) params.status = filterStatus.value
    
    const data = await accountStore.fetchAccounts(params)
    accounts.value = data.items
  } catch (error) {
    console.error('Failed to fetch accounts:', error)
  } finally {
    loading.value = false
  }
}

function handleFilter() {
  fetchAccounts()
}

function navigateToDetail(id: string) {
  router.push(`/accounts/${id}`)
}

async function testConnection(id: string) {
  try {
    const result = await accountStore.testConnection(id)
    // 使用 toast 提示而非 alert
    showToast(result.connected ? '连接成功' : '连接失败：请检查平台配置', result.connected ? 'success' : 'error')
  } catch (error) {
    console.error('Failed to test connection:', error)
    showToast('连接测试失败，请检查平台配置', 'error')
  }
}

async function handleCreate(data: any) {
  creating.value = true
  try {
    await accountStore.createAccount(data)
    showToast('账号创建成功', 'success')
    showCreateDialog.value = false
    await fetchAccounts()
  } catch (error: any) {
    console.error('Failed to create account:', error)
    showToast(error?.message || '账号创建失败，请检查平台配置后重试', 'error')
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.filters-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-5);
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.filters-bar__left {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.form-select--sm {
  padding: var(--spacing-1) var(--spacing-2);
  font-size: var(--font-size-sm);
}

.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.text-muted {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
</style>
