<template>
  <div class="agents-view">
    <PageHeader title="Agent 管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建 Agent
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && agents.length === 0"
      icon="🤖"
      title="暂无 Agent"
      description="开始创建你的第一个 AI Agent"
      :show-action="true"
      action-text="新建 Agent"
      @action="showCreateDialog = true"
    />

    <!-- Agent List -->
    <div v-else class="agent-grid">
      <div
        v-for="agent in agents"
        :key="agent.id"
        class="agent-card"
        @click="navigateToDetail(agent.id)"
      >
        <div class="agent-card__header">
          <div class="agent-card__avatar">🤖</div>
          <StatusBadge :status="agent.status" />
        </div>
        <div class="agent-card__content">
          <h3 class="agent-card__name">{{ agent.name }}</h3>
          <p class="agent-card__desc">{{ agent.description || '暂无描述' }}</p>
          <div class="agent-card__footer">
            <span v-if="agent.persona_name" class="agent-card__persona">
              👤 {{ agent.persona_name }}
            </span>
            <span class="agent-card__time">
              {{ formatTime(agent.created_at) }}
            </span>
          </div>
        </div>
        <div class="agent-card__actions" @click.stop>
          <button class="btn btn--ghost btn--sm" @click="startAgent(agent.id)">
            ▶ 启动
          </button>
          <button
            v-if="agent.status === 'running'"
            class="btn btn--ghost btn--sm"
            @click="stopAgent(agent.id)"
          >
            ⏹ 停止
          </button>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建 Agent"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">Agent 名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入 Agent 名称"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">描述</label>
          <textarea
            v-model="createForm.description"
            class="form-textarea"
            placeholder="请输入描述（可选）"
            rows="3"
          ></textarea>
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
import { useAgentStore } from '@/stores/agent'
import type { Agent } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const agentStore = useAgentStore()

const agents = ref<Agent[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  name: '',
  description: '',
})

onMounted(async () => {
  await fetchAgents()
})

async function fetchAgents() {
  loading.value = true
  try {
    const data = await agentStore.fetchAgents()
    agents.value = data.items
  } catch (error) {
    console.error('Failed to fetch agents:', error)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!createForm.value.name.trim()) return
  
  creating.value = true
  try {
    await agentStore.createAgent(createForm.value)
    showCreateDialog.value = false
    createForm.value = { name: '', description: '' }
    await fetchAgents()
  } catch (error) {
    console.error('Failed to create agent:', error)
  } finally {
    creating.value = false
  }
}

function navigateToDetail(id: string) {
  router.push(`/agents/${id}`)
}

async function startAgent(id: string) {
  try {
    await agentStore.startAgent(id)
    await fetchAgents()
  } catch (error) {
    console.error('Failed to start agent:', error)
  }
}

async function stopAgent(id: string) {
  try {
    await agentStore.stopAgent(id)
    await fetchAgents()
  } catch (error) {
    console.error('Failed to stop agent:', error)
  }
}

function formatTime(time: string) {
  return new Date(time).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--spacing-4);
}

.agent-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.agent-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.agent-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--spacing-3);
}

.agent-card__avatar {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.agent-card__content {
  margin-bottom: var(--spacing-4);
}

.agent-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.agent-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-3);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.agent-card__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.agent-card__persona {
  color: var(--color-primary);
}

.agent-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
