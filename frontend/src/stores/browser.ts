import { defineStore } from 'pinia'
import { ref } from 'vue'
import { browserApi } from '@/api/browser'
import type { BrowserProfile, BrowserProviderStatus, PaginatedResponse } from '@/api/types'

export const useBrowserStore = defineStore('browser', () => {
  // State
  const profiles = ref<BrowserProfile[]>([])
  const providerStatus = ref<BrowserProviderStatus | null>(null)
  const loading = ref(false)

  // Actions
  async function fetchProfiles(): Promise<PaginatedResponse<BrowserProfile>> {
    loading.value = true
    try {
      const data = await browserApi.listProfiles()
      profiles.value = data.items
      return data
    } catch (error) {
      console.error('[BrowserStore] Failed to fetch profiles:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchProviderStatus() {
    try {
      const status = await browserApi.getBitBrowserStatus()
      providerStatus.value = status
      return status
    } catch (error) {
      console.error('[BrowserStore] Failed to fetch provider status:', error)
      throw error
    }
  }

  async function testConnection() {
    try {
      return await browserApi.testBitBrowserConnection()
    } catch (error) {
      console.error('[BrowserStore] Failed to test connection:', error)
      throw error
    }
  }

  async function createProfile(data: { name: string; provider: string }) {
    try {
      const profile = await browserApi.createProfile(data)
      profiles.value.unshift(profile)
      return profile
    } catch (error) {
      console.error('[BrowserStore] Failed to create profile:', error)
      throw error
    }
  }

  async function deleteProfile(id: string) {
    try {
      await browserApi.deleteProfile(id)
      profiles.value = profiles.value.filter(p => p.id !== id)
    } catch (error) {
      console.error('[BrowserStore] Failed to delete profile:', error)
      throw error
    }
  }

  return {
    // State
    profiles,
    providerStatus,
    loading,
    // Actions
    fetchProfiles,
    fetchProviderStatus,
    testConnection,
    createProfile,
    deleteProfile,
  }
})
