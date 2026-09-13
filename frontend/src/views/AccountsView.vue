<template>
  <div class="accounts-view">
    <PageHeader title="账号管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建账号
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && accounts.length === 0"
      icon="👤"
      title="暂无账号"
      description="添加你的社交媒体账号"
      :show-action="true"
      action-text="新建账号"
      @action="showCreateDialog = true"
    />

    <!-- Account List -->
    <div v-else class="account-grid">
      <div
        v-for="account in accounts"
        :key="account.id"
        class="account-card"
        @click="navigateToDetail(account.id)"
      >
        <div class="account-card__header">
          <div class="account-card__platform">
            <span class="platform-icon">{{ getPlatformIcon(account.platform_id) }}</span>
            <span class="platform-name">{{ getPlatformName(account.platform_id) }}</span>
          </div>
          <StatusBadge :status="account.status" />
        </div>
        <div class="account-card__content">
          <h3 class="account-card__name">{{ account.name }}</h3>
          <p v-if="account.username" class="account-card__username">@{{ account.username }}</p>
        </div>
        <div class="account-card__footer">
          <button
            class="btn btn--ghost btn--sm"
            @click.stop="testConnection(account.id)"
          >
            测试连接
          </button>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建账号"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">平台</label>
          <select v-model="createForm.platform_id" class="form-select" required>
            <option value="wechat">微信</option>
            <option value="douyin">抖音</option>
            <option value="weibo">微博</option>
            <option value="xiaohongshu">小红书</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">账号名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入账号名称"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">用户名</label>
          <input
            v-model="createForm.username"
            class="form-input"
            placeholder="请输入用户名（可选）"
          />
        </div>
        <div class="form-group">
          <label class="form-label">密码</label>
          <input
            v-model="createForm.password"
            type="password"
            class="form-input"
            placeholder="请输入密码"
          />
        </div>
        <ModalFooter>
          <button
            type="button"
            class="btn btn--ghost"
            @click="showCreateDialog = false"
          >
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="creating">
            {{ creating ? '创建中...' : '创建' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountStore } from '@/stores/account'
import type { Account } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const accountStore = useAccountStore()

const accounts = ref<Account[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  platform_id: 'wechat',
  name: '',
  username: '',
  password: '',
})

const platformMap: Record<string, { name: string; icon: string }> = {
  wechat: { name: '微信', icon: '💬' },
  douyin: { name: '抖音', icon: '🎵' },
  weibo: { name: '微博', icon: '📢' },
  xiaohongshu: { name: '小红书', icon: '📕' },
}

onMounted(async () => {
  await fetchAccounts()
})

async function fetchAccounts() {
  loading.value = true
  try {
    const data = await accountStore.fetchAccounts()
    accounts.value = data.items
  } catch (error) {
    console.error('Failed to fetch accounts:', error)
  } finally {
    loading.value = false
  }
}

function getPlatformIcon(platformId: string) {
  return platformMap[platformId]?.icon || '📱'
}

function getPlatformName(platformId: string) {
  return platformMap[platformId]?.name || platformId
}

async function handleCreate() {
  if (!createForm.value.name.trim()) return
  
  creating.value = true
  try {
    await accountStore.createAccount(createForm.value)
    showCreateDialog.value = false
    createForm.value = {
      platform_id: 'wechat',
      name: '',
      username: '',
      password: '',
    }
    await fetchAccounts()
  } catch (error) {
    console.error('Failed to create account:', error)
  } finally {
    creating.value = false
  }
}

function navigateToDetail(id: string) {
  router.push(`/accounts/${id}`)
}

async function testConnection(id: string) {
  try {
    const result = await accountStore.testConnection(id)
    alert(result.connected ? '连接成功！' : '连接失败')
  } catch (error) {
    console.error('Failed to test connection:', error)
    alert('连接测试失败')
  }
}
</script>

<style scoped>
.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.account-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.account-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.account-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.account-card__platform {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.platform-icon {
  font-size: 24px;
}

.platform-name {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.account-card__content {
  margin-bottom: var(--spacing-3);
}

.account-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.account-card__username {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin: 0;
}

.account-card__footer {
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
