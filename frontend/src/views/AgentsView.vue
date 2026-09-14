<template>
  <div class="agents-view">
    <PageHeader title="Agent 管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建 Agent
        </button>
      </template>
    </PageHeader>

    <!-- Filter Bar -->
    <AgentFilterBar
      :total="agentStore.total"
      @search="handleSearch"
      @filter="handleFilter"
      @sort="handleSort"
    />

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

    <!-- Agent Grid -->
    <div v-else class="agent-grid">
      <AgentCard
        v-for="agent in agents"
        :key="agent.id"
        :agent="agent"
        @click="navigateToDetail(agent.id)"
        @start="handleStart(agent.id)"
        @stop="handleStop(agent.id)"
        @delete="handleDelete(agent.id)"
      />
    </div>

    <!-- Create Dialog -->
    <AgentCreateDialog
      v-if="showCreateDialog"
      :open="showCreateDialog"
      @close="showCreateDialog = false"
      @submit="handleCreate"
    />
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
import AgentFilterBar from '@/components/agent/AgentFilterBar.vue'
import AgentCard from '@/components/agent/AgentCard.vue'
import AgentCreateDialog from '@/components/agent/AgentCreateDialog.vue'

const router = useRouter()
const agentStore = useAgentStore()

const agents = ref<Agent[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
const sortField = ref('created_at')
const sortOrder = ref<'asc' | 'desc'>('desc')

onMounted(async () => {
  await fetchAgents()
})

async function fetchAgents() {
  loading.value = true
  try {
    const params: any = {
      page: 1,
      page_size: 100,
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (searchQuery.value) params.search = searchQuery.value
    
    const data = await agentStore.fetchAgents(params)
    agents.value = data.items
  } catch (error) {
    console.error('Failed to fetch agents:', error)
  } finally {
    loading.value = false
  }
}

function handleSearch(query: string) {
  searchQuery.value = query
  fetchAgents()
}

function handleFilter(filter: { status: string }) {
  statusFilter.value = filter.status
  fetchAgents()
}

function handleSort(sort: { field: string; order: 'asc' | 'desc' }) {
  sortField.value = sort.field
  sortOrder.value = sort.order
  fetchAgents()
}

async function handleCreate(data: { name: string; description?: string; icon?: string }) {
  try {
    await agentStore.createAgent(data)
    showCreateDialog.value = false
    await fetchAgents()
  } catch (error) {
    console.error('Failed to create agent:', error)
  }
}

function navigateToDetail(id: string) {
  router.push(`/agents/${id}`)
}

async function handleStart(id: string) {
  try {
    await agentStore.startAgent(id)
    await fetchAgents()
  } catch (error) {
    console.error('Failed to start agent:', error)
  }
}

async function handleStop(id: string) {
  try {
    await agentStore.stopAgent(id)
    await fetchAgents()
  } catch (error) {
    console.error('Failed to stop agent:', error)
  }
}

async function handleDelete(id: string) {
  if (!confirm('确定要删除这个 Agent 吗？')) return
  try {
    await agentStore.deleteAgent(id)
    await fetchAgents()
  } catch (error) {
    console.error('Failed to delete agent:', error)
  }
}
</script>

<style scoped>
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--spacing-4);
}
</style>
