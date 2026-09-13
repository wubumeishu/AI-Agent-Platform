import { defineStore } from 'pinia'
import { ref } from 'vue'
import { proxyApi } from '@/api/proxy'
import type { Proxy, CreateProxyRequest, UpdateProxyRequest, PaginatedResponse } from '@/api/types'

export const useProxyStore = defineStore('proxy', () => {
  // State
  const proxies = ref<Proxy[]>([])
  const loading = ref(false)

  // Actions
  async function fetchProxies(): Promise<PaginatedResponse<Proxy>> {
    loading.value = true
    try {
      const data = await proxyApi.list()
      proxies.value = data.items
      return data
    } catch (error) {
      console.error('[ProxyStore] Failed to fetch proxies:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function createProxy(data: CreateProxyRequest) {
    try {
      const proxy = await proxyApi.create(data)
      proxies.value.unshift(proxy)
      return proxy
    } catch (error) {
      console.error('[ProxyStore] Failed to create proxy:', error)
      throw error
    }
  }

  async function updateProxy(id: string, data: UpdateProxyRequest) {
    try {
      const proxy = await proxyApi.update(id, data)
      const index = proxies.value.findIndex(p => p.id === id)
      if (index !== -1) {
        proxies.value[index] = proxy
      }
      return proxy
    } catch (error) {
      console.error('[ProxyStore] Failed to update proxy:', error)
      throw error
    }
  }

  async function deleteProxy(id: string) {
    try {
      await proxyApi.delete(id)
      proxies.value = proxies.value.filter(p => p.id !== id)
    } catch (error) {
      console.error('[ProxyStore] Failed to delete proxy:', error)
      throw error
    }
  }

  async function testConnection(id: string) {
    try {
      return await proxyApi.testConnection(id)
    } catch (error) {
      console.error('[ProxyStore] Failed to test connection:', error)
      throw error
    }
  }

  return {
    // State
    proxies,
    loading,
    // Actions
    fetchProxies,
    createProxy,
    updateProxy,
    deleteProxy,
    testConnection,
  }
})
