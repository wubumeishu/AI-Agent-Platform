<template>
  <div class="agent-detail-view" v-loading="currentAgentLoading">
    <PageHeader title="Agent 详情" show-back>
      <template #actions>
        <div class="detail-actions">
          <button 
            v-if="currentAgent?.status !== 'running'"
            class="btn btn--success"
            @click="handleStart"
          >
            ▶ 启动
          </button>
          <button 
            v-else
            class="btn btn--warning"
            @click="handleStop"
          >
            ⏹ 停止
          </button>
          <button class="btn btn--danger" @click="handleDelete">删除</button>
        </div>
      </template>
    </PageHeader>

    <div v-if="!currentAgent" class="empty-state">
      <p>Agent 不存在</p>
    </div>

    <div v-else>
      <!-- Agent Info Card -->
      <Card class="agent-info-card">
        <template #header>
          <div class="agent-info-card__header">
            <div class="agent-info-card__avatar">
              <span class="avatar-icon">{{ currentAgent.icon || '🤖' }}</span>
            </div>
            <div class="agent-info-card__info">
              <h2>{{ currentAgent.name }}</h2>
              <StatusBadge :status="currentAgent.status" />
            </div>
          </div>
        </template>
        <p class="agent-description">{{ currentAgent.description || '暂无描述' }}</p>
        <div class="agent-info-card__meta">
          <span>创建时间: {{ formatTime(currentAgent.created_at) }}</span>
          <span>更新时间: {{ formatTime(currentAgent.updated_at) }}</span>
        </div>
      </Card>

      <!-- Tabs -->
      <div class="tabs-container">
        <Tabs v-model="activeTab" :tabs="tabs" />
      </div>

      <!-- Tab Content -->
      <div class="tab-content">
        <!-- Persona Tab -->
        <div v-if="activeTab === 'persona'" class="tab-panel">
          <Card>
            <template #header>
              <h3>已绑定 Persona</h3>
            </template>
            
            <div v-if="currentAgent.persona" class="persona-binding">
              <div class="persona-binding__info">
                <div class="persona-binding__icon">🎭</div>
                <div>
                  <h4>{{ currentAgent.persona.name }}</h4>
                  <p class="persona-binding__desc">{{ currentAgent.persona.description }}</p>
                  <div class="persona-binding__params">
                    <span class="param-chip">{{ toneLabel(currentAgent.persona.personality.tone) }}</span>
                    <span class="param-chip">{{ lengthLabel(currentAgent.persona.personality.reply_length) }}</span>
                    <span class="param-chip">{{ proactivenessLabel(currentAgent.persona.personality.proactiveness) }}</span>
                  </div>
                </div>
              </div>
              <button class="btn btn--ghost" @click="router.push(`/personas/${currentAgent.persona.id}`)">
                编辑 Persona
              </button>
            </div>
            
            <div v-else class="no-persona">
              <p class="text-muted">未配置 Persona</p>
              <button class="btn btn--primary mt-4" @click="router.push('/personas')">
                前往配置 Persona
              </button>
            </div>
          </Card>
        </div>

        <!-- Accounts Tab -->
        <div v-if="activeTab === 'accounts'" class="tab-panel">
          <Card>
            <template #header>
              <h3>绑定账号</h3>
            </template>
            
            <div v-if="currentAgent.accounts && currentAgent.accounts.length > 0" class="accounts-list">
              <div v-for="account in currentAgent.accounts" :key="account.id" class="account-item">
                <div class="account-item__info">
                  <span class="account-item__name">{{ account.name }}</span>
                  <span class="account-item__platform">{{ getPlatformName(account.platform_id) }}</span>
                </div>
                <StatusBadge :status="account.status" />
              </div>
            </div>
            
            <div v-else class="empty-state">
              <p>暂无绑定账号</p>
              <button class="btn btn--primary mt-4" @click="router.push('/accounts')">
                添加账号
              </button>
            </div>
          </Card>
        </div>

        <!-- Config Tab -->
        <div v-if="activeTab === 'config'" class="tab-panel">
          <Card>
            <template #header>
              <h3>LLM 配置</h3>
            </template>
            <div class="config-section">
              <p class="text-muted">AI Provider 和 Model 配置（V1 预留）</p>
            </div>
          </Card>
          
          <Card class="mt-4">
            <template #header>
              <h3>工具配置</h3>
            </template>
            <div class="config-section">
              <p class="text-muted">可用工具开关（V1 预留）</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agent'
import type { Agent } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Tabs from '@/components/common/Tabs.vue'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

const activeTab = ref('persona')
const currentAgent = ref<Agent & { persona?: any; accounts?: any[] }>(null!)
const currentAgentLoading = ref(false)

const tabs = [
  { value: 'persona', label: 'Persona' },
  { value: 'accounts', label: '绑定账号' },
  { value: 'config', label: '配置' },
]

onMounted(async () => {
  const id = route.params.id as string
  await fetchAgent(id)
})

watch(() => route.params.id, async (newId) => {
  if (newId) await fetchAgent(newId as string)
})

async function fetchAgent(id: string) {
  currentAgentLoading.value = true
  try {
    const agent = await agentStore.fetchAgent(id)
    currentAgent.value = agent as any
  } catch (error) {
    console.error('Failed to fetch agent:', error)
  } finally {
    currentAgentLoading.value = false
  }
}

async function handleStart() {
  try {
    await agentStore.startAgent(route.params.id as string)
    await fetchAgent(route.params.id as string)
  } catch (error) {
    console.error('Failed to start agent:', error)
  }
}

async function handleStop() {
  try {
    await agentStore.stopAgent(route.params.id as string)
    await fetchAgent(route.params.id as string)
  } catch (error) {
    console.error('Failed to stop agent:', error)
  }
}

async function handleDelete() {
  if (!confirm('确定要删除这个 Agent 吗？此操作不可恢复。')) return
  try {
    await agentStore.deleteAgent(route.params.id as string)
    router.push('/agents')
  } catch (error) {
    console.error('Failed to delete agent:', error)
  }
}

function formatTime(time: string) {
  return new Date(time).toLocaleString('zh-CN')
}

function toneLabel(tone: string): string {
  const map: Record<string, string> = { professional: '专业', friendly: '友好', casual: '随意' }
  return map[tone] || tone
}

function lengthLabel(length: string): string {
  const map: Record<string, string> = { concise: '简洁', balanced: '适中', detailed: '详细' }
  return map[length] || length
}

function proactivenessLabel(level: string): string {
  const map: Record<string, string> = { low: '被动', medium: '适中', high: '主动' }
  return map[level] || level
}

function getPlatformName(platformId: string): string {
  const map: Record<string, string> = {
    wechat: '微信',
    douyin: '抖音',
    qq: 'QQ',
    enterprise_wechat: '企业微信',
  }
  return map[platformId] || platformId
}
</script>

<style scoped>
.agent-info-card {
  margin-bottom: var(--spacing-5);
}

.agent-info-card__header {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.agent-info-card__avatar {
  width: 64px;
  height: 64px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
}

.agent-info-card__info h2 {
  margin: 0 0 var(--spacing-1);
  font-size: var(--font-size-2xl);
}

.agent-info-card__meta {
  display: flex;
  gap: var(--spacing-4);
  margin-top: var(--spacing-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.agent-description {
  margin: var(--spacing-3) 0;
  color: var(--color-text-secondary);
}

.tabs-container {
  margin-top: var(--spacing-5);
}

.tab-content {
  margin-top: var(--spacing-4);
}

.detail-actions {
  display: flex;
  gap: var(--spacing-2);
}

.persona-binding {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-4);
}

.persona-binding__info {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.persona-binding__icon {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.persona-binding__info h4 {
  margin: 0 0 var(--spacing-1);
}

.persona-binding__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-2);
}

.persona-binding__params {
  display: flex;
  gap: var(--spacing-2);
}

.param-chip {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
}

.no-persona, .empty-state {
  text-align: center;
  padding: var(--spacing-6);
}

.text-muted {
  color: var(--color-text-muted);
}

.mt-4 {
  margin-top: var(--spacing-4);
}

.mt-5 {
  margin-top: var(--spacing-5);
}

.accounts-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.account-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.account-item__info {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.account-item__name {
  font-weight: var(--font-weight-medium);
}

.account-item__platform {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.config-section {
  padding: var(--spacing-4) 0;
  border-bottom: 1px solid var(--color-border);
}

.config-section:last-child {
  border-bottom: none;
}
</style>
