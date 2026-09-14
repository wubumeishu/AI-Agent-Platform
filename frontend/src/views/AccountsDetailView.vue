<template>
  <div class="account-detail-view" v-loading="currentAccountLoading">
    <PageHeader title="账号详情" show-back />

    <div v-if="!currentAccount" class="empty-state">
      <p>账号不存在</p>
    </div>

    <div v-else>
      <!-- Account Info -->
      <Card class="account-info-card">
        <template #header>
          <div class="account-info-card__header">
            <div class="account-info-card__icon">
              {{ getPlatformIcon(currentAccount.platform_id) }}
            </div>
            <div class="account-info-card__info">
              <h2>{{ currentAccount.name }}</h2>
              <p v-if="currentAccount.username" class="account-info-card__username">
                @{{ currentAccount.username }}
              </p>
            </div>
            <StatusBadge :status="currentAccount.status as any" />
          </div>
        </template>
        <div class="account-info-card__meta">
          <span>平台: {{ getPlatformName(currentAccount.platform_id) }}</span>
          <span v-if="currentAccount.last_login">
            最后登录: {{ formatTime(currentAccount.last_login) }}
          </span>
          <span v-if="currentAccount.created_at">
            创建时间: {{ formatTime(currentAccount.created_at) }}
          </span>
        </div>
      </Card>

      <!-- Tabs -->
      <div class="tabs-container">
        <Tabs v-model="activeTab" :tabs="tabs" />
      </div>

      <!-- Tab Content -->
      <div class="tab-content">
        <!-- Agent Binding Tab -->
        <div v-if="activeTab === 'agent'" class="tab-panel">
          <TabAgentBinding :account-id="accountId" />
        </div>

        <!-- Browser Binding Tab -->
        <div v-if="activeTab === 'browser'" class="tab-panel">
          <TabBrowserBinding :account-id="accountId" />
        </div>

        <!-- Proxy Binding Tab -->
        <div v-if="activeTab === 'proxy'" class="tab-panel">
          <TabProxyBinding :account-id="accountId" />
        </div>
      </div>

      <!-- Connection Status -->
      <Card class="mt-5">
        <template #header>
          <h3>连接状态</h3>
        </template>
        <div class="connection-status">
          <StatusBadge :status="currentAccount?.status as any" />
          <button class="btn btn--primary ml-4" @click="testConnection">
            测试连接
          </button>
        </div>
      </Card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAccountStore } from '@/stores/account'
import type { Account } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Tabs from '@/components/common/Tabs.vue'
import TabAgentBinding from '@/components/account/tabs/TabAgentBinding.vue'
import TabBrowserBinding from '@/components/account/tabs/TabBrowserBinding.vue'
import TabProxyBinding from '@/components/account/tabs/TabProxyBinding.vue'

const route = useRoute()
const accountStore = useAccountStore()

const accountId = ref(route.params.id as string)
const activeTab = ref('agent')
const currentAccount = ref<Account | null>(null)
const currentAccountLoading = ref(false)

const tabs = [
  { value: 'agent', label: 'Agent 绑定' },
  { value: 'browser', label: 'Browser 绑定' },
  { value: 'proxy', label: 'Proxy 绑定' },
]

const platformMap: Record<string, { name: string; icon: string }> = {
  wechat: { name: '微信', icon: '💬' },
  douyin: { name: '抖音', icon: '🎵' },
  weibo: { name: '微博', icon: '📢' },
  xiaohongshu: { name: '小红书', icon: '📕' },
}

onMounted(async () => {
  await fetchAccount(accountId.value)
})

watch(() => route.params.id, async (newId) => {
  if (newId) {
    accountId.value = newId as string
    await fetchAccount(newId as string)
  }
})

async function fetchAccount(id: string) {
  currentAccountLoading.value = true
  try {
    const account = await accountStore.fetchAccount(id)
    currentAccount.value = account
  } catch (error) {
    console.error('Failed to fetch account:', error)
  } finally {
    currentAccountLoading.value = false
  }
}

function getPlatformIcon(platformId: string) {
  return platformMap[platformId]?.icon || '📱'
}

function getPlatformName(platformId: string) {
  return platformMap[platformId]?.name || platformId
}

function formatTime(time: string) {
  return new Date(time).toLocaleString('zh-CN')
}

async function testConnection() {
  try {
    const result = await accountStore.testConnection(accountId.value)
    console.log(result.connected ? '连接成功' : '连接失败')
  } catch (error) {
    console.error('Failed to test connection:', error)
  }
}
</script>

<style scoped>
.account-info-card {
  margin-bottom: var(--spacing-5);
}

.account-info-card__header {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.account-info-card__icon {
  font-size: 40px;
}

.account-info-card__info h2 {
  margin: 0 0 var(--spacing-1);
  font-size: var(--font-size-2xl);
}

.account-info-card__username {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.account-info-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-4);
  margin-top: var(--spacing-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.tabs-container {
  margin-top: var(--spacing-5);
}

.tab-content {
  margin-top: var(--spacing-4);
}

.connection-status {
  display: flex;
  align-items: center;
}

.ml-4 {
  margin-left: var(--spacing-4);
}

.mt-5 {
  margin-top: var(--spacing-5);
}

.text-muted {
  color: var(--color-text-muted);
}
</style>
