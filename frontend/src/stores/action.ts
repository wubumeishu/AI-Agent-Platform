import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { actionApi } from '@/api/action'
import type {
  WorkflowAction,
  CreateActionRequest,
  UpdateActionRequest,
} from '@/api/types'

/**
 * 动作 Store（嵌套模型：condition -> actions）。
 *
 * 动作通过其所属的条件访问；这里按条件 id 聚合维护动作列表。
 */
export const useActionStore = defineStore('action', () => {
  const actionsByCondition = ref<Record<string, WorkflowAction[]>>({})
  const loading = ref(false)

  const hasActions = computed(() =>
    Object.values(actionsByCondition.value).some((a) => a.length > 0)
  )

  const actionsOf = (conditionId: string) =>
    actionsByCondition.value[conditionId] ?? []

  async function fetchActions(
    workflowId: string,
    triggerId: string,
    conditionId: string
  ) {
    loading.value = true
    try {
      const res = await actionApi.list(workflowId, triggerId, conditionId)
      actionsByCondition.value[conditionId] = res.items ?? []
      return actionsByCondition.value[conditionId]
    } catch (error) {
      console.error('[ActionStore] Failed to fetch actions:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function createAction(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    data: CreateActionRequest
  ): Promise<WorkflowAction> {
    try {
      const action = await actionApi.create(
        workflowId,
        triggerId,
        conditionId,
        data
      )
      const list = actionsByCondition.value[conditionId] ?? []
      list.push(action)
      actionsByCondition.value[conditionId] = list
      return action
    } catch (error) {
      console.error('[ActionStore] Failed to create action:', error)
      throw error
    }
  }

  async function updateAction(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    actionId: string,
    data: UpdateActionRequest
  ): Promise<WorkflowAction> {
    try {
      const action = await actionApi.update(
        workflowId,
        triggerId,
        conditionId,
        actionId,
        data
      )
      const list = actionsByCondition.value[conditionId]
      if (list) {
        const index = list.findIndex((a) => a.id === actionId)
        if (index !== -1) list[index] = action
      }
      return action
    } catch (error) {
      console.error('[ActionStore] Failed to update action:', error)
      throw error
    }
  }

  async function deleteAction(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    actionId: string
  ) {
    try {
      await actionApi.delete(workflowId, triggerId, conditionId, actionId)
      const list = actionsByCondition.value[conditionId]
      if (list) {
        actionsByCondition.value[conditionId] = list.filter(
          (a) => a.id !== actionId
        )
      }
    } catch (error) {
      console.error('[ActionStore] Failed to delete action:', error)
      throw error
    }
  }

  function clearActions() {
    actionsByCondition.value = {}
  }

  return {
    // State
    actionsByCondition,
    loading,
    // Getters
    hasActions,
    actionsOf,
    // Actions
    fetchActions,
    createAction,
    updateAction,
    deleteAction,
    clearActions,
  }
})
