import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { contentApi } from '@/api/content'
import type { Content } from '@/api/private_domain'
import type { PaginatedResponse } from '@/api/client'

export const useContentStore = defineStore('content', () => {
  // State
  const contents = ref<Content[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentContent = ref<Content | null>(null)
  const currentContentLoading = ref(false)

  // Getters
  const contentList = computed(() => contents.value)
  const hasContents = computed(() => contents.value.length > 0)

  // Actions
  async function fetchContents(params?: { page?: number; page_size?: number; type?: string; status?: string }): Promise<PaginatedResponse<Content>> {
    loading.value = true
    try {
      const data = await contentApi.list(params)
      contents.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[ContentStore] Failed to fetch contents:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchContent(id: string) {
    currentContentLoading.value = true
    try {
      const content = await contentApi.detail(id)
      currentContent.value = content
      return content
    } catch (error) {
      console.error('[ContentStore] Failed to fetch content:', error)
      throw error
    } finally {
      currentContentLoading.value = false
    }
  }

  async function createContent(data: import('@/api/private_domain').CreateContentRequest) {
    try {
      const content = await contentApi.create(data)
      contents.value.unshift(content)
      return content
    } catch (error) {
      console.error('[ContentStore] Failed to create content:', error)
      throw error
    }
  }

  async function updateContent(id: string, data: Partial<Content>) {
    try {
      const content = await contentApi.update(id, data)
      const index = contents.value.findIndex(c => c.id === id)
      if (index !== -1) {
        contents.value[index] = content
      }
      if (currentContent.value?.id === id) {
        currentContent.value = content
      }
      return content
    } catch (error) {
      console.error('[ContentStore] Failed to update content:', error)
      throw error
    }
  }

  async function deleteContent(id: string) {
    try {
      await contentApi.delete(id)
      contents.value = contents.value.filter(c => c.id !== id)
      if (currentContent.value?.id === id) {
        currentContent.value = null
      }
    } catch (error) {
      console.error('[ContentStore] Failed to delete content:', error)
      throw error
    }
  }

  async function publishContent(id: string) {
    try {
      await contentApi.publish(id)
      const content = contents.value.find(c => c.id === id)
      if (content) {
        content.status = 'published'
      }
      if (currentContent.value?.id === id) {
        currentContent.value.status = 'published'
      }
    } catch (error) {
      console.error('[ContentStore] Failed to publish content:', error)
      throw error
    }
  }

  function clearCurrentContent() {
    currentContent.value = null
  }

  return {
    // State
    contents,
    total,
    loading,
    currentContent,
    currentContentLoading,
    // Getters
    contentList,
    hasContents,
    // Actions
    fetchContents,
    fetchContent,
    createContent,
    updateContent,
    deleteContent,
    publishContent,
    clearCurrentContent,
  }
})
