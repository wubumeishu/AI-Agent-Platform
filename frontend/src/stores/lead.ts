import { defineStore } from 'pinia'
import { ref } from 'vue'
import { leadApi } from '@/api/lead'
import type {
  Lead,
  LeadListParams,
  LeadListResponse,
  CreateLeadRequest,
  UpdateLeadRequest,
  LifecycleStage,
  LifecycleTransition,
} from '@/api/types'

export const useLeadStore = defineStore('lead', () => {
  // State
  const leads = ref<Lead[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentLead = ref<Lead | null>(null)
  const currentLeadLoading = ref(false)
  const lifecycleStages = ref<LifecycleStage[]>([])

  // Actions
  async function fetchLeads(params?: LeadListParams): Promise<LeadListResponse> {
    loading.value = true
    try {
      const data = await leadApi.list(params)
      leads.value = data.data
      total.value = data.total
      return data
    } catch (error) {
      console.error('[LeadStore] Failed to fetch leads:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchLead(id: string) {
    currentLeadLoading.value = true
    try {
      const lead = await leadApi.detail(id)
      currentLead.value = lead
      return lead
    } catch (error) {
      console.error('[LeadStore] Failed to fetch lead:', error)
      throw error
    } finally {
      currentLeadLoading.value = false
    }
  }

  async function createLead(data: CreateLeadRequest): Promise<Lead> {
    try {
      const lead = await leadApi.create(data)
      // 刷新列表
      await fetchLeads()
      return lead
    } catch (error) {
      console.error('[LeadStore] Failed to create lead:', error)
      throw error
    }
  }

  async function updateLead(id: string, data: UpdateLeadRequest): Promise<Lead> {
    try {
      const lead = await leadApi.update(id, data)
      // 更新列表中的 Lead
      const index = leads.value.findIndex(l => l.id === id)
      if (index !== -1) {
        leads.value[index] = lead
      }
      // 更新当前 Lead
      if (currentLead.value?.id === id) {
        currentLead.value = lead
      }
      return lead
    } catch (error) {
      console.error('[LeadStore] Failed to update lead:', error)
      throw error
    }
  }

  async function deleteLead(id: string): Promise<void> {
    try {
      await leadApi.delete(id)
      leads.value = leads.value.filter(l => l.id !== id)
      if (currentLead.value?.id === id) {
        currentLead.value = null
      }
    } catch (error) {
      console.error('[LeadStore] Failed to delete lead:', error)
      throw error
    }
  }

  async function transitionStage(data: LifecycleTransition): Promise<{ stage: string; log_id: string }> {
    try {
      const result = await leadApi.transitionStage(data)
      // 刷新当前 Lead
      if (currentLead.value) {
        await fetchLead(currentLead.value.id)
      }
      // 刷新列表
      await fetchLeads()
      return result
    } catch (error) {
      console.error('[LeadStore] Failed to transition stage:', error)
      throw error
    }
  }

  async function fetchLifecycleStages(): Promise<LifecycleStage[]> {
    try {
      const stages = await leadApi.getLifecycleStages()
      lifecycleStages.value = stages
      return stages
    } catch (error) {
      console.error('[LeadStore] Failed to fetch lifecycle stages:', error)
      throw error
    }
  }

  async function fetchCustomerLeads(customerId: string): Promise<Lead[]> {
    try {
      const leadList = await leadApi.getCustomerLeads(customerId)
      return leadList
    } catch (error) {
      console.error('[LeadStore] Failed to fetch customer leads:', error)
      throw error
    }
  }

  function clearCurrentLead() {
    currentLead.value = null
  }

  return {
    // State
    leads,
    total,
    loading,
    currentLead,
    currentLeadLoading,
    lifecycleStages,
    // Actions
    fetchLeads,
    fetchLead,
    createLead,
    updateLead,
    deleteLead,
    transitionStage,
    fetchLifecycleStages,
    fetchCustomerLeads,
    clearCurrentLead,
  }
})
