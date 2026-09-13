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
            <StatusBadge :status="(currentAccount.status as any)" />
          </div>
        </template>
        <div class="account-info-card__meta">
          <span>平台: {{ getPlatformName(currentAccount.platform_id) }}</span>
          <span v-if="currentAccount.last_login">
            最后登录: {{ formatTime(currentAccount.last_login) }}
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
          <Card>
            <template #header>
              <h3>绑定 Agent</h3>
            </template>
            <p class="text-muted">暂无绑定的 Agent</p>
          </Card>
        </div>

        <!-- Browser Binding Tab -->
        <div v-if="activeTab === 'browser'" class="tab-panel">
          <Card>
            <template #header>
              <h3>绑定 Browser</h3>
            </template>
            <p class="text-muted">暂无绑定的 Browser Profile</p>
          </Card>
        </div>

        <!-- Proxy Binding Tab -->
        <div v-if="activeTab === 'proxy'" class="tab-panel">
          <Card>
            <template #header>
              <h3>绑定 Proxy</h3>
            </template>
            <p class="text-muted">暂无绑定的 Proxy</p>
          </Card>
        </div>
      </div>

      <!-- Connection Status -->
      <Card class="mt-5">
        <template #header>
          <h3>连接状态</h3>
        </template>
        <div class="connection-status">
          <StatusBadge :status="(currentAccount?.status as any)" />
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

const route = useRoute()
const accountStore = useAccountStore()

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
  const id = route.params.id as string
  await fetchAccount(id)
})

watch(() => route.params.id, async (newId) => {
  if (newId) await fetchAccount(newId as string)
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
  const id = route.params.id as string
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
