import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { pipelineApi, dealApi } from '@/api/deal'
import type {
  DealPipeline,
  DealStage,
  DealItem,
  DealPipelineStats,
  AccountPipelineStats,
  CreatePipelineRequest,
  UpdatePipelineRequest,
  CreateDealRequest,
  UpdateDealRequest,
  DealTransition,
} from '@/api/private_domain'
import type { PaginatedResponse } from '@/api/client'

export const useDealStore = defineStore('deal', () => {
  // Pipeline State
  const pipelines = ref<DealPipeline[]>([])
  const pipelinesTotal = ref(0)
  const pipelinesLoading = ref(false)
  const currentPipeline = ref<DealPipeline | null>(null)
  const currentPipelineLoading = ref(false)
  const pipelineStages = ref<DealStage[]>([])
  const pipelineStats = ref<DealPipelineStats | null>(null)
  const accountStats = ref<AccountPipelineStats[]>([])

  // Deal Item State
  const deals = ref<DealItem[]>([])
  const dealsTotal = ref(0)
  const dealsLoading = ref(false)
  const currentDeal = ref<DealItem | null>(null)
  const currentDealLoading = ref(false)

  // Getters
  const pipelineList = computed(() => pipelines.value)
  const hasPipelines = computed(() => pipelines.value.length > 0)
  const dealList = computed(() => deals.value)
  const hasDeals = computed(() => deals.value.length > 0)

  // Pipeline Actions
  async function fetchPipelines(params?: {
    account_id: string
    pipeline_type?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<DealPipeline>> {
    pipelinesLoading.value = true
    try {
      const data = await pipelineApi.list(params)
      pipelines.value = data.items
      pipelinesTotal.value = data.total
      return data
    } catch (error) {
      console.error('[DealStore] Failed to fetch pipelines:', error)
      throw error
    } finally {
      pipelinesLoading.value = false
    }
  }

  async function fetchPipeline(id: string, account_id: string) {
    currentPipelineLoading.value = true
    try {
      const pipeline = await pipelineApi.detail(id, account_id)
      currentPipeline.value = pipeline
      // Fetch stages
      const stages = await pipelineApi.listStages(id)
      pipelineStages.value = stages
      return pipeline
    } catch (error) {
      console.error('[DealStore] Failed to fetch pipeline:', error)
      throw error
    } finally {
      currentPipelineLoading.value = false
    }
  }

  async function createPipeline(data: CreatePipelineRequest) {
    try {
      const pipeline = await pipelineApi.create(data)
      pipelines.value.unshift(pipeline)
      return pipeline
    } catch (error) {
      console.error('[DealStore] Failed to create pipeline:', error)
      throw error
    }
  }

  async function updatePipeline(id: string, data: UpdatePipelineRequest) {
    try {
      const pipeline = await pipelineApi.update(id, data)
      const index = pipelines.value.findIndex(p => p.id === id)
      if (index !== -1) {
        pipelines.value[index] = pipeline
      }
      if (currentPipeline.value?.id === id) {
        currentPipeline.value = pipeline
      }
      return pipeline
    } catch (error) {
      console.error('[DealStore] Failed to update pipeline:', error)
      throw error
    }
  }

  async function deletePipeline(id: string) {
    try {
      await pipelineApi.delete(id)
      pipelines.value = pipelines.value.filter(p => p.id !== id)
      if (currentPipeline.value?.id === id) {
        currentPipeline.value = null
      }
    } catch (error) {
      console.error('[DealStore] Failed to delete pipeline:', error)
      throw error
    }
  }

  async function fetchPipelineStats(pipeline_id: string) {
    try {
      const stats = await pipelineApi.stats(pipeline_id)
      pipelineStats.value = stats
      return stats
    } catch (error) {
      console.error('[DealStore] Failed to fetch pipeline stats:', error)
      throw error
    }
  }

  async function fetchAccountStats(account_id: string) {
    try {
      const stats = await pipelineApi.accountStats(account_id)
      accountStats.value = stats
      return stats
    } catch (error) {
      console.error('[DealStore] Failed to fetch account stats:', error)
      throw error
    }
  }

  // Stage Actions
  async function createStage(pipeline_id: string, data: { name: string; order?: number; probability?: number }) {
    try {
      const stage = await pipelineApi.createStage(pipeline_id, data)
      pipelineStages.value.push(stage)
      return stage
    } catch (error) {
      console.error('[DealStore] Failed to create stage:', error)
      throw error
    }
  }

  async function updateStage(stage_id: string, data: { name?: string; order?: number; probability?: number; status?: string }) {
    try {
      const stage = await pipelineApi.updateStage(stage_id, data)
      const index = pipelineStages.value.findIndex(s => s.id === stage_id)
      if (index !== -1) {
        pipelineStages.value[index] = stage
      }
      return stage
    } catch (error) {
      console.error('[DealStore] Failed to update stage:', error)
      throw error
    }
  }

  async function deleteStage(stage_id: string) {
    try {
      await pipelineApi.deleteStage(stage_id)
      pipelineStages.value = pipelineStages.value.filter(s => s.id !== stage_id)
    } catch (error) {
      console.error('[DealStore] Failed to delete stage:', error)
      throw error
    }
  }

  // Deal Item Actions
  async function fetchDeals(params?: {
    account_id: string
    pipeline_id?: string
    stage_id?: string
    status?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<DealItem>> {
    dealsLoading.value = true
    try {
      const data = await dealApi.list(params)
      deals.value = data.items
      dealsTotal.value = data.total
      return data
    } catch (error) {
      console.error('[DealStore] Failed to fetch deals:', error)
      throw error
    } finally {
      dealsLoading.value = false
    }
  }

  async function fetchDeal(id: string, account_id: string) {
    currentDealLoading.value = true
    try {
      const deal = await dealApi.detail(id, account_id)
      currentDeal.value = deal
      return deal
    } catch (error) {
      console.error('[DealStore] Failed to fetch deal:', error)
      throw error
    } finally {
      currentDealLoading.value = false
    }
  }

  async function createDeal(data: CreateDealRequest) {
    try {
      const deal = await dealApi.create(data)
      deals.value.unshift(deal)
      return deal
    } catch (error) {
      console.error('[DealStore] Failed to create deal:', error)
      throw error
    }
  }

  async function updateDeal(id: string, data: UpdateDealRequest) {
    try {
      const deal = await dealApi.update(id, data)
      const index = deals.value.findIndex(d => d.id === id)
      if (index !== -1) {
        deals.value[index] = deal
      }
      if (currentDeal.value?.id === id) {
        currentDeal.value = deal
      }
      return deal
    } catch (error) {
      console.error('[DealStore] Failed to update deal:', error)
      throw error
    }
  }

  async function deleteDeal(id: string) {
    try {
      await dealApi.delete(id)
      deals.value = deals.value.filter(d => d.id !== id)
      if (currentDeal.value?.id === id) {
        currentDeal.value = null
      }
    } catch (error) {
      console.error('[DealStore] Failed to delete deal:', error)
      throw error
    }
  }

  async function transitionDeal(id: string, data: DealTransition) {
    try {
      const deal = await dealApi.transition(id, data)
      const index = deals.value.findIndex(d => d.id === id)
      if (index !== -1) {
        deals.value[index] = deal
      }
      if (currentDeal.value?.id === id) {
        currentDeal.value = deal
      }
      return deal
    } catch (error) {
      console.error('[DealStore] Failed to transition deal:', error)
      throw error
    }
  }

  function clearCurrentPipeline() {
    currentPipeline.value = null
    pipelineStages.value = []
    pipelineStats.value = null
  }

  function clearCurrentDeal() {
    currentDeal.value = null
  }

  return {
    // Pipeline State
    pipelines,
    pipelinesTotal,
    pipelinesLoading,
    currentPipeline,
    currentPipelineLoading,
    pipelineStages,
    pipelineStats,
    accountStats,
    // Deal Item State
    deals,
    dealsTotal,
    dealsLoading,
    currentDeal,
    currentDealLoading,
    // Getters
    pipelineList,
    hasPipelines,
    dealList,
    hasDeals,
    // Pipeline Actions
    fetchPipelines,
    fetchPipeline,
    createPipeline,
    updatePipeline,
    deletePipeline,
    fetchPipelineStats,
    fetchAccountStats,
    // Stage Actions
    createStage,
    updateStage,
    deleteStage,
    // Deal Item Actions
    fetchDeals,
    fetchDeal,
    createDeal,
    updateDeal,
    deleteDeal,
    transitionDeal,
    clearCurrentPipeline,
    clearCurrentDeal,
  }
})
