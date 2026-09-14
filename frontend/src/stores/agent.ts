import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { agentApi } from '@/api/agent'
import type { Agent, AgentListParams, PaginatedResponse } from '@/api/types'

export const useAgentStore = defineStore('agent', () => {
  // State
  const agents = ref<Agent[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentAgent = ref<Agent | null>(null)
  const currentAgentLoading = ref(false)

  // Getters
  const agentList = computed(() => agents.value)
  const hasAgents = computed(() => agents.value.length > 0)

  // Actions
  async function fetchAgents(params?: AgentListParams): Promise<PaginatedResponse<Agent>> {
    loading.value = true
    try {
      const data = await agentApi.list(params)
      agents.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[AgentStore] Failed to fetch agents:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchAgent(id: string) {
    currentAgentLoading.value = true
    try {
      const agent = await agentApi.detail(id)
      currentAgent.value = agent
      return agent
    } catch (error) {
      console.error('[AgentStore] Failed to fetch agent:', error)
      throw error
    } finally {
      currentAgentLoading.value = false
    }
  }

  async function createAgent(data: { name: string; description?: string; icon?: string }) {
    try {
      const agent = await agentApi.create(data)
      agents.value.unshift(agent)
      return agent
    } catch (error) {
      console.error('[AgentStore] Failed to create agent:', error)
      throw error
    }
  }

  async function updateAgent(id: string, data: { name?: string; description?: string }) {
    try {
      const agent = await agentApi.update(id, data)
      const index = agents.value.findIndex(a => a.id === id)
      if (index !== -1) {
        agents.value[index] = agent
      }
      if (currentAgent.value?.id === id) {
        currentAgent.value = agent
      }
      return agent
    } catch (error) {
      console.error('[AgentStore] Failed to update agent:', error)
      throw error
    }
  }

  async function deleteAgent(id: string) {
    try {
      await agentApi.delete(id)
      agents.value = agents.value.filter(a => a.id !== id)
      if (currentAgent.value?.id === id) {
        currentAgent.value = null
      }
    } catch (error) {
      console.error('[AgentStore] Failed to delete agent:', error)
      throw error
    }
  }

  async function startAgent(id: string) {
    try {
      await agentApi.start(id)
      const agent = agents.value.find(a => a.id === id)
      if (agent) {
        agent.status = 'active'
      }
      if (currentAgent.value?.id === id) {
        currentAgent.value.status = 'active'
      }
    } catch (error) {
      console.error('[AgentStore] Failed to start agent:', error)
      throw error
    }
  }

  async function stopAgent(id: string) {
    try {
      await agentApi.stop(id)
      const agent = agents.value.find(a => a.id === id)
      if (agent) {
        agent.status = 'inactive'
      }
      if (currentAgent.value?.id === id) {
        currentAgent.value.status = 'inactive'
      }
    } catch (error) {
      console.error('[AgentStore] Failed to stop agent:', error)
      throw error
    }
  }

  function clearCurrentAgent() {
    currentAgent.value = null
  }

  return {
    // State
    agents,
    total,
    loading,
    currentAgent,
    currentAgentLoading,
    // Getters
    agentList,
    hasAgents,
    // Actions
    fetchAgents,
    fetchAgent,
    createAgent,
    updateAgent,
    deleteAgent,
    startAgent,
    stopAgent,
    clearCurrentAgent,
  }
})
