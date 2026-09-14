import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { workflowApi } from '@/api/workflow'
import type {
  Workflow,
  WorkflowDetailTree,
  WorkflowListParams,
  WorkflowListResponse,
  CreateWorkflowRequest,
  UpdateWorkflowRequest,
  ExecutionLog,
} from '@/api/types'

export const useWorkflowStore = defineStore('workflow', () => {
  // State
  const workflows = ref<Workflow[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentWorkflow = ref<Workflow | null>(null)
  const currentWorkflowLoading = ref(false)
  const executionLogs = ref<ExecutionLog[]>([])
  const executionLogsTotal = ref(0)
  const executionLogsLoading = ref(false)

  // Getters
  const workflowList = computed(() => workflows.value)
  const hasWorkflows = computed(() => workflows.value.length > 0)

  // Actions
  async function fetchWorkflows(params?: WorkflowListParams): Promise<WorkflowListResponse> {
    loading.value = true
    try {
      const data = await workflowApi.list(params)
      workflows.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[WorkflowStore] Failed to fetch workflows:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchWorkflow(id: string) {
    currentWorkflowLoading.value = true
    try {
      currentWorkflow.value = await workflowApi.detail(id)
      return currentWorkflow.value
    } catch (error) {
      console.error('[WorkflowStore] Failed to fetch workflow:', error)
      throw error
    } finally {
      currentWorkflowLoading.value = false
    }
  }

  async function createWorkflow(data: CreateWorkflowRequest): Promise<Workflow> {
    try {
      const workflow = await workflowApi.create(data)
      await fetchWorkflows()
      return workflow
    } catch (error) {
      console.error('[WorkflowStore] Failed to create workflow:', error)
      throw error
    }
  }

  async function updateWorkflow(id: string, data: UpdateWorkflowRequest): Promise<Workflow> {
    try {
      const workflow = await workflowApi.update(id, data)
      const index = workflows.value.findIndex((w) => w.id === id)
      if (index !== -1) workflows.value[index] = workflow
      if (currentWorkflow.value?.id === id) currentWorkflow.value = workflow
      return workflow
    } catch (error) {
      console.error('[WorkflowStore] Failed to update workflow:', error)
      throw error
    }
  }

  async function deleteWorkflow(id: string): Promise<void> {
    try {
      await workflowApi.delete(id)
      workflows.value = workflows.value.filter((w) => w.id !== id)
      if (currentWorkflow.value?.id === id) currentWorkflow.value = null
    } catch (error) {
      console.error('[WorkflowStore] Failed to delete workflow:', error)
      throw error
    }
  }

  async function activateWorkflow(id: string): Promise<Workflow> {
    const workflow = await workflowApi.activate(id)
    const index = workflows.value.findIndex((w) => w.id === id)
    if (index !== -1) workflows.value[index] = workflow
    return workflow
  }

  async function pauseWorkflow(id: string): Promise<Workflow> {
    const workflow = await workflowApi.pause(id)
    const index = workflows.value.findIndex((w) => w.id === id)
    if (index !== -1) workflows.value[index] = workflow
    return workflow
  }

  async function fetchExecutionLogs(
    workflowId: string,
    params?: { page?: number; page_size?: number; status?: string }
  ) {
    executionLogsLoading.value = true
    try {
      const data = await workflowApi.executionLogs(workflowId, params)
      executionLogs.value = data.items
      executionLogsTotal.value = data.total
      return data.items
    } catch (error) {
      console.error('[WorkflowStore] Failed to fetch execution logs:', error)
      throw error
    } finally {
      executionLogsLoading.value = false
    }
  }

  function clearCurrentWorkflow() {
    currentWorkflow.value = null
    executionLogs.value = []
    executionLogsTotal.value = 0
  }

  return {
    // State
    workflows,
    total,
    loading,
    currentWorkflow,
    currentWorkflowLoading,
    executionLogs,
    executionLogsTotal,
    executionLogsLoading,
    // Getters
    workflowList,
    hasWorkflows,
    // Actions
    fetchWorkflows,
    fetchWorkflow,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    activateWorkflow,
    pauseWorkflow,
    fetchExecutionLogs,
    clearCurrentWorkflow,
  }
})
