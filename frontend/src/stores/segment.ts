import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { segmentApi } from '@/api/segment'
import type { Segment, SegmentStats, SegmentMember, CreateSegmentRequest, UpdateSegmentRequest } from '@/api/private_domain'
import type { PaginatedResponse } from '@/api/client'

export const useSegmentStore = defineStore('segment', () => {
  // State
  const segments = ref<Segment[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentSegment = ref<Segment | null>(null)
  const currentSegmentLoading = ref(false)
  const segmentStats = ref<SegmentStats | null>(null)
  const segmentMembers = ref<SegmentMember[]>([])
  const membersTotal = ref(0)

  // Getters
  const segmentList = computed(() => segments.value)
  const hasSegments = computed(() => segments.value.length > 0)

  // Actions
  async function fetchSegments(params?: {
    account_id: string
    segment_type?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<Segment>> {
    loading.value = true
    try {
      const data = await segmentApi.list(params)
      segments.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[SegmentStore] Failed to fetch segments:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchSegment(id: string, account_id: string) {
    currentSegmentLoading.value = true
    try {
      const segment = await segmentApi.detail(id, account_id)
      currentSegment.value = segment
      return segment
    } catch (error) {
      console.error('[SegmentStore] Failed to fetch segment:', error)
      throw error
    } finally {
      currentSegmentLoading.value = false
    }
  }

  async function createSegment(data: CreateSegmentRequest) {
    try {
      const segment = await segmentApi.create(data)
      segments.value.unshift(segment)
      return segment
    } catch (error) {
      console.error('[SegmentStore] Failed to create segment:', error)
      throw error
    }
  }

  async function updateSegment(id: string, data: UpdateSegmentRequest) {
    try {
      const segment = await segmentApi.update(id, data)
      const index = segments.value.findIndex(s => s.id === id)
      if (index !== -1) {
        segments.value[index] = segment
      }
      if (currentSegment.value?.id === id) {
        currentSegment.value = segment
      }
      return segment
    } catch (error) {
      console.error('[SegmentStore] Failed to update segment:', error)
      throw error
    }
  }

  async function deleteSegment(id: string) {
    try {
      await segmentApi.delete(id)
      segments.value = segments.value.filter(s => s.id !== id)
      if (currentSegment.value?.id === id) {
        currentSegment.value = null
      }
    } catch (error) {
      console.error('[SegmentStore] Failed to delete segment:', error)
      throw error
    }
  }

  async function fetchSegmentStats(id: string, account_id: string) {
    try {
      const stats = await segmentApi.stats(id, account_id)
      segmentStats.value = stats
      return stats
    } catch (error) {
      console.error('[SegmentStore] Failed to fetch segment stats:', error)
      throw error
    }
  }

  async function fetchSegmentMembers(id: string, params?: { page?: number; page_size?: number }) {
    try {
      const data = await segmentApi.listMembers(id, params)
      segmentMembers.value = data.items
      membersTotal.value = data.total
      return data
    } catch (error) {
      console.error('[SegmentStore] Failed to fetch segment members:', error)
      throw error
    }
  }

  async function addMember(id: string, customer_id: string, added_by?: string) {
    try {
      await segmentApi.addMember(id, customer_id, added_by)
      // Refresh segment data
      if (currentSegment.value?.id === id) {
        await fetchSegment(id, currentSegment.value.account_id)
      }
    } catch (error) {
      console.error('[SegmentStore] Failed to add member:', error)
      throw error
    }
  }

  async function removeMember(id: string, customer_id: string) {
    try {
      await segmentApi.removeMember(id, customer_id)
      // Refresh segment data
      if (currentSegment.value?.id === id) {
        await fetchSegment(id, currentSegment.value.account_id)
      }
    } catch (error) {
      console.error('[SegmentStore] Failed to remove member:', error)
      throw error
    }
  }

  async function syncSegment(id: string) {
    try {
      const result = await segmentApi.sync(id)
      // Refresh segment data
      if (currentSegment.value?.id === id) {
        await fetchSegment(id, currentSegment.value.account_id)
      }
      return result
    } catch (error) {
      console.error('[SegmentStore] Failed to sync segment:', error)
      throw error
    }
  }

  function clearCurrentSegment() {
    currentSegment.value = null
    segmentStats.value = null
    segmentMembers.value = []
  }

  return {
    // State
    segments,
    total,
    loading,
    currentSegment,
    currentSegmentLoading,
    segmentStats,
    segmentMembers,
    membersTotal,
    // Getters
    segmentList,
    hasSegments,
    // Actions
    fetchSegments,
    fetchSegment,
    createSegment,
    updateSegment,
    deleteSegment,
    fetchSegmentStats,
    fetchSegmentMembers,
    addMember,
    removeMember,
    syncSegment,
    clearCurrentSegment,
  }
})
