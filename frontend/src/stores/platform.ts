import { defineStore } from 'pinia'
import { ref } from 'vue'
import { platformApi } from '@/api/platform'
import type { Platform, CreatePlatformRequest, PaginatedResponse } from '@/api/types'

export const usePlatformStore = defineStore('platform', () => {
  // State
  const platforms = ref<Platform[]>([])
  const loading = ref(false)

  // Actions
  async function fetchPlatforms(): Promise<PaginatedResponse<Platform>> {
    loading.value = true
    try {
      const data = await platformApi.list()
      platforms.value = data.items
      return data
    } catch (error) {
      console.error('[PlatformStore] Failed to fetch platforms:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function createPlatform(data: CreatePlatformRequest) {
    try {
      const platform = await platformApi.create(data)
      platforms.value.unshift(platform)
      return platform
    } catch (error) {
      console.error('[PlatformStore] Failed to create platform:', error)
      throw error
    }
  }

  async function deletePlatform(id: string) {
    try {
      await platformApi.delete(id)
      platforms.value = platforms.value.filter(p => p.id !== id)
    } catch (error) {
      console.error('[PlatformStore] Failed to delete platform:', error)
      throw error
    }
  }

  return {
    // State
    platforms,
    loading,
    // Actions
    fetchPlatforms,
    createPlatform,
    deletePlatform,
  }
})
