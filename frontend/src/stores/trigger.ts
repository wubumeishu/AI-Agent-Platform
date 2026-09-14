import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { triggerApi } from '@/api/trigger'
import type {
  WorkflowTrigger,
  WorkflowCondition,
  CreateTriggerRequest,
  UpdateTriggerRequest,
  CreateConditionRequest,
  UpdateConditionRequest,
} from '@/api/types'

/**
 * 触发器 Store（嵌套模型：workflow -> triggers -> conditions）。
 *
 * 一个 workflow 下可挂多个触发器；每个触发器下可挂多个条件。
 * 这里把「触发器 + 各触发器的条件」统一维护，供详情页 / 配置对话框消费。
 */
export const useTriggerStore = defineStore('trigger', () => {
  // State
  const triggers = ref<WorkflowTrigger[]>([])
  const conditionsByTrigger = ref<Record<string, WorkflowCondition[]>>({})
  const loading = ref(false)
  const conditionsLoading = ref(false)

  // Getters
  const triggerList = computed(() => triggers.value)
  const hasTriggers = computed(() => triggers.value.length > 0)
  const conditionsOf = (triggerId: string) =>
    conditionsByTrigger.value[triggerId] ?? []

  // ---- 拉取某 workflow 的全部触发器及其条件 / 动作（嵌套详情树，单次调用） ----
  async function fetchTriggers(workflowId: string) {
    loading.value = true
    conditionsLoading.value = true
    try {
      const tree = await triggerApi.detailTree(workflowId)
      triggers.value = (tree.triggers ?? []).map((t) => ({
        ...t,
        conditions: undefined,
      })) as WorkflowTrigger[]
      conditionsByTrigger.value = {}
      for (const node of tree.triggers ?? []) {
        const condList = (node.conditions ?? []) as WorkflowCondition[]
        for (const c of condList) c.actions = c.actions ?? []
        conditionsByTrigger.value[node.id] = condList
      }
      return triggers.value
    } catch (error) {
      console.error('[TriggerStore] Failed to fetch triggers:', error)
      throw error
    } finally {
      loading.value = false
      conditionsLoading.value = false
    }
  }

  // ---- 触发器 CRUD ----
  async function createTrigger(
    workflowId: string,
    data: CreateTriggerRequest
  ): Promise<WorkflowTrigger> {
    try {
      const trigger = await triggerApi.create(workflowId, data)
      triggers.value.push(trigger)
      conditionsByTrigger.value[trigger.id] = []
      return trigger
    } catch (error) {
      console.error('[TriggerStore] Failed to create trigger:', error)
      throw error
    }
  }

  async function updateTrigger(
    workflowId: string,
    triggerId: string,
    data: UpdateTriggerRequest
  ): Promise<WorkflowTrigger> {
    try {
      const trigger = await triggerApi.update(workflowId, triggerId, data)
      const index = triggers.value.findIndex((t) => t.id === triggerId)
      if (index !== -1) triggers.value[index] = trigger
      return trigger
    } catch (error) {
      console.error('[TriggerStore] Failed to update trigger:', error)
      throw error
    }
  }

  async function deleteTrigger(workflowId: string, triggerId: string) {
    try {
      await triggerApi.delete(workflowId, triggerId)
      triggers.value = triggers.value.filter((t) => t.id !== triggerId)
      delete conditionsByTrigger.value[triggerId]
    } catch (error) {
      console.error('[TriggerStore] Failed to delete trigger:', error)
      throw error
    }
  }

  /** 启用 / 禁用 */
  async function setTriggerEnabled(
    workflowId: string,
    triggerId: string,
    enabled: boolean
  ): Promise<WorkflowTrigger> {
    try {
      const trigger = await triggerApi.setEnabled(workflowId, triggerId, enabled)
      const index = triggers.value.findIndex((t) => t.id === triggerId)
      if (index !== -1) triggers.value[index] = trigger
      return trigger
    } catch (error) {
      console.error('[TriggerStore] Failed to toggle trigger:', error)
      throw error
    }
  }

  // ---- 条件 CRUD（嵌套于触发器） ----
  async function createCondition(
    workflowId: string,
    triggerId: string,
    data: CreateConditionRequest
  ): Promise<WorkflowCondition> {
    try {
      const cond = await triggerApi.createCondition(workflowId, triggerId, data)
      const list = conditionsByTrigger.value[triggerId] ?? []
      list.push(cond)
      conditionsByTrigger.value[triggerId] = list
      return cond
    } catch (error) {
      console.error('[TriggerStore] Failed to create condition:', error)
      throw error
    }
  }

  async function updateCondition(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    data: UpdateConditionRequest
  ): Promise<WorkflowCondition> {
    try {
      const cond = await triggerApi.updateCondition(
        workflowId,
        triggerId,
        conditionId,
        data
      )
      const list = conditionsByTrigger.value[triggerId]
      if (!list) return cond
      const index = list.findIndex((c) => c.id === conditionId)
      if (index !== -1) list[index] = cond
      return cond
    } catch (error) {
      console.error('[TriggerStore] Failed to update condition:', error)
      throw error
    }
  }

  async function deleteCondition(
    workflowId: string,
    triggerId: string,
    conditionId: string
  ) {
    try {
      await triggerApi.deleteCondition(workflowId, triggerId, conditionId)
      const list = conditionsByTrigger.value[triggerId]
      if (list) {
        conditionsByTrigger.value[triggerId] = list.filter(
          (c) => c.id !== conditionId
        )
      }
    } catch (error) {
      console.error('[TriggerStore] Failed to delete condition:', error)
      throw error
    }
  }

  function clearTriggers() {
    triggers.value = []
    conditionsByTrigger.value = {}
  }

  return {
    // State
    triggers,
    conditionsByTrigger,
    loading,
    conditionsLoading,
    // Getters
    triggerList,
    hasTriggers,
    conditionsOf,
    // Actions
    fetchTriggers,
    createTrigger,
    updateTrigger,
    deleteTrigger,
    setTriggerEnabled,
    createCondition,
    updateCondition,
    deleteCondition,
    clearTriggers,
  }
})
