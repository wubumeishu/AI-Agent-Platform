import { defineStore } from 'pinia'
import { ref } from 'vue'
import { tagApi } from '@/api/tag'
import type {
  Tag,
  TagListParams,
  CreateTagRequest,
  UpdateTagRequest,
  PaginatedResponse,
} from '@/api/types'

export const useTagStore = defineStore('tag', () => {
  // State
  const tags = ref<Tag[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentTag = ref<Tag | null>(null)
  const currentTagLoading = ref(false)
  const allTags = ref<Tag[]>([])

  // Actions
  async function fetchTags(params?: TagListParams): Promise<PaginatedResponse<Tag>> {
    loading.value = true
    try {
      const data = await tagApi.list(params)
      tags.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[TagStore] Failed to fetch tags:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchTag(id: string) {
    currentTagLoading.value = true
    try {
      const tag = await tagApi.detail(id)
      currentTag.value = tag
      return tag
    } catch (error) {
      console.error('[TagStore] Failed to fetch tag:', error)
      throw error
    } finally {
      currentTagLoading.value = false
    }
  }

  async function createTag(data: CreateTagRequest): Promise<Tag> {
    try {
      const tag = await tagApi.create(data)
      tags.value.unshift(tag)
      return tag
    } catch (error) {
      console.error('[TagStore] Failed to create tag:', error)
      throw error
    }
  }

  async function updateTag(id: string, data: UpdateTagRequest): Promise<Tag> {
    try {
      const tag = await tagApi.update(id, data)
      const index = tags.value.findIndex(t => t.id === id)
      if (index !== -1) {
        tags.value[index] = tag
      }
      if (currentTag.value?.id === id) {
        currentTag.value = tag
      }
      return tag
    } catch (error) {
      console.error('[TagStore] Failed to update tag:', error)
      throw error
    }
  }

  async function deleteTag(id: string): Promise<void> {
    try {
      await tagApi.delete(id)
      tags.value = tags.value.filter(t => t.id !== id)
      if (currentTag.value?.id === id) {
        currentTag.value = null
      }
    } catch (error) {
      console.error('[TagStore] Failed to delete tag:', error)
      throw error
    }
  }

  async function fetchAllTags(): Promise<Tag[]> {
    try {
      const allTagsData = await tagApi.all()
      allTags.value = allTagsData
      return allTagsData
    } catch (error) {
      console.error('[TagStore] Failed to fetch all tags:', error)
      throw error
    }
  }

  function clearCurrentTag() {
    currentTag.value = null
  }

  return {
    // State
    tags,
    total,
    loading,
    currentTag,
    currentTagLoading,
    allTags,
    // Actions
    fetchTags,
    fetchTag,
    createTag,
    updateTag,
    deleteTag,
    fetchAllTags,
    clearCurrentTag,
  }
})
