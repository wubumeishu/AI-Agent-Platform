import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { nurtureApi } from '@/api/nurture'
import type { NurturePlan } from '@/api/private_domain'
import type { PaginatedResponse } from '@/api/client'

export const useNurtureStore = defineStore('nurture', () => {
  // State
  const nurturePlans = ref<NurturePlan[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentNurture = ref<NurturePlan | null>(null)
  const currentNurtureLoading = ref(false)

  // Getters
  const nurtureList = computed(() => nurturePlans.value)
  const hasNurturePlans = computed(() => nurturePlans.value.length > 0)

  // Actions
  async function fetchNurturePlans(params?: { page?: number; page_size?: number; status?: string; channel_id?: string }): Promise<PaginatedResponse<NurturePlan>> {
    loading.value = true
    try {
      const data = await nurtureApi.list(params)
      nurturePlans.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[NurtureStore] Failed to fetch nurture plans:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchNurturePlan(id: string) {
    currentNurtureLoading.value = true
    try {
      const plan = await nurtureApi.detail(id)
      currentNurture.value = plan
      return plan
    } catch (error) {
      console.error('[NurtureStore] Failed to fetch nurture plan:', error)
      throw error
    } finally {
      currentNurtureLoading.value = false
    }
  }

  async function createNurture(data: import('@/api/private_domain').CreateNurtureRequest) {
    try {
      const plan = await nurtureApi.create(data)
      nurturePlans.value.unshift(plan)
      return plan
    } catch (error) {
      console.error('[NurtureStore] Failed to create nurture plan:', error)
      throw error
    }
  }

  async function updateNurture(id: string, data: Partial<NurturePlan>) {
    try {
      const plan = await nurtureApi.update(id, data)
      const index = nurturePlans.value.findIndex(p => p.id === id)
      if (index !== -1) {
        nurturePlans.value[index] = plan
      }
      if (currentNurture.value?.id === id) {
        currentNurture.value = plan
      }
      return plan
    } catch (error) {
      console.error('[NurtureStore] Failed to update nurture plan:', error)
      throw error
    }
  }

  async function deleteNurture(id: string) {
    try {
      await nurtureApi.delete(id)
      nurturePlans.value = nurturePlans.value.filter(p => p.id !== id)
      if (currentNurture.value?.id === id) {
        currentNurture.value = null
      }
    } catch (error) {
      console.error('[NurtureStore] Failed to delete nurture plan:', error)
      throw error
    }
  }

  async function startNurture(id: string) {
    try {
      await nurtureApi.start(id)
      const plan = nurturePlans.value.find(p => p.id === id)
      if (plan) {
        plan.status = 'active'
      }
      if (currentNurture.value?.id === id) {
        currentNurture.value.status = 'active'
      }
    } catch (error) {
      console.error('[NurtureStore] Failed to start nurture plan:', error)
      throw error
    }
  }

  async function pauseNurture(id: string) {
    try {
      await nurtureApi.pause(id)
      const plan = nurturePlans.value.find(p => p.id === id)
      if (plan) {
        plan.status = 'paused'
      }
      if (currentNurture.value?.id === id) {
        currentNurture.value.status = 'paused'
      }
    } catch (error) {
      console.error('[NurtureStore] Failed to pause nurture plan:', error)
      throw error
    }
  }

  async function completeNurture(id: string) {
    try {
      await nurtureApi.complete(id)
      const plan = nurturePlans.value.find(p => p.id === id)
      if (plan) {
        plan.status = 'completed'
      }
      if (currentNurture.value?.id === id) {
        currentNurture.value.status = 'completed'
      }
    } catch (error) {
      console.error('[NurtureStore] Failed to complete nurture plan:', error)
      throw error
    }
  }

  async function archiveNurture(id: string) {
    try {
      await nurtureApi.archive(id)
      const plan = nurturePlans.value.find(p => p.id === id)
      if (plan) {
        plan.status = 'archived'
      }
      if (currentNurture.value?.id === id) {
        currentNurture.value.status = 'archived'
      }
    } catch (error) {
      console.error('[NurtureStore] Failed to archive nurture plan:', error)
      throw error
    }
  }

  function clearCurrentNurture() {
    currentNurture.value = null
  }

  return {
    // State
    nurturePlans,
    total,
    loading,
    currentNurture,
    currentNurtureLoading,
    // Getters
    nurtureList,
    hasNurturePlans,
    // Actions
    fetchNurturePlans,
    fetchNurturePlan,
    createNurture,
    updateNurture,
    deleteNurture,
    startNurture,
    pauseNurture,
    completeNurture,
    archiveNurture,
    clearCurrentNurture,
  }
})
