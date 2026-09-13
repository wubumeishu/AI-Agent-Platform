<template>
  <div class="agent-detail-view" v-loading="currentAgentLoading">
    <PageHeader title="Agent 详情" show-back>
      <template #actions>
        <button class="btn btn--danger" @click="handleDelete">删除</button>
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
            <div class="agent-info-card__avatar">🤖</div>
            <div class="agent-info-card__info">
              <h2>{{ currentAgent.name }}</h2>
              <StatusBadge :status="currentAgent.status" />
            </div>
          </div>
        </template>
        <p>{{ currentAgent.description || '暂无描述' }}</p>
        <div class="agent-info-card__meta">
          <span>创建时间: {{ formatTime(currentAgent.created_at) }}</span>
          <span>更新时间: {{ formatTime(currentAgent.updated_at) }}</span>
        </div>
      </Card>

      <!-- Tabs -->
      <div class="tabs-container">
        <Tabs
          v-model="activeTab"
          :tabs="tabs"
        />
      </div>

      <!-- Tab Content -->
      <div class="tab-content">
        <!-- Persona Tab -->
        <div v-if="activeTab === 'persona'" class="tab-panel">
          <Card>
            <template #header>
              <h3>当前 Persona</h3>
            </template>
            <div v-if="currentAgent.persona">
              <p><strong>名称:</strong> {{ currentAgent.persona.name }}</p>
              <p><strong>描述:</strong> {{ currentAgent.persona.description }}</p>
              <div class="personality-params">
                <h4>性格参数</h4>
                <div class="param-grid">
                  <div class="param-item">
                    <span class="param-label">语气:</span>
                    <span class="param-value">{{ (currentAgent as any).persona?.personality?.tone }}</span>
                  </div>
                  <div class="param-item">
                    <span class="param-label">回复长度:</span>
                    <span class="param-value">{{ (currentAgent as any).persona?.personality?.reply_length }}</span>
                  </div>
                  <div class="param-item">
                    <span class="param-label">主动性:</span>
                    <span class="param-value">{{ (currentAgent as any).persona?.personality?.proactiveness }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else>
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
            <p class="text-muted">暂无绑定账号</p>
          </Card>
        </div>

        <!-- Config Tab -->
        <div v-if="activeTab === 'config'" class="tab-panel">
          <Card>
            <template #header>
              <h3>Agent 配置</h3>
            </template>
            <div class="config-section">
              <h4>LLM 配置</h4>
              <p class="text-muted">AI Provider 和 Model 配置</p>
            </div>
            <div class="config-section">
              <h4>工具配置</h4>
              <p class="text-muted">可用工具开关</p>
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
const currentAgent = ref<any>(null)
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
    currentAgent.value = agent
  } catch (error) {
    console.error('Failed to fetch agent:', error)
  } finally {
    currentAgentLoading.value = false
  }
}

async function handleDelete() {
  if (!confirm('确定要删除这个 Agent 吗？')) return
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

.tabs-container {
  margin-top: var(--spacing-5);
}

.tab-content {
  margin-top: var(--spacing-4);
}

.personality-params {
  margin-top: var(--spacing-4);
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-3);
  margin-top: var(--spacing-2);
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.param-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.param-value {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.config-section {
  padding: var(--spacing-4) 0;
  border-bottom: 1px solid var(--color-border);
}

.config-section:last-child {
  border-bottom: none;
}

.config-section h4 {
  margin: 0 0 var(--spacing-2);
}

.text-muted {
  color: var(--color-text-muted);
}

.mt-4 {
  margin-top: var(--spacing-4);
}
</style>
