import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { channelApi } from '@/api/channel'
import type { Channel, ChannelListParams } from '@/api/private_domain'
import type { PaginatedResponse } from '@/api/client'

export const useChannelStore = defineStore('channel', () => {
  // State
  const channels = ref<Channel[]>([])
  const total = ref(0)
  const loading = ref(false)
  const currentChannel = ref<Channel | null>(null)
  const currentChannelLoading = ref(false)

  // Getters
  const channelList = computed(() => channels.value)
  const hasChannels = computed(() => channels.value.length > 0)

  // Actions
  async function fetchChannels(params?: ChannelListParams): Promise<PaginatedResponse<Channel>> {
    loading.value = true
    try {
      const data = await channelApi.list(params)
      channels.value = data.items
      total.value = data.total
      return data
    } catch (error) {
      console.error('[ChannelStore] Failed to fetch channels:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchChannel(id: string) {
    currentChannelLoading.value = true
    try {
      const channel = await channelApi.detail(id)
      currentChannel.value = channel
      return channel
    } catch (error) {
      console.error('[ChannelStore] Failed to fetch channel:', error)
      throw error
    } finally {
      currentChannelLoading.value = false
    }
  }

  async function createChannel(data: import('@/api/private_domain').CreateChannelRequest) {
    try {
      const channel = await channelApi.create(data)
      channels.value.unshift(channel)
      return channel
    } catch (error) {
      console.error('[ChannelStore] Failed to create channel:', error)
      throw error
    }
  }

  async function updateChannel(id: string, data: Partial<Channel>) {
    try {
      const channel = await channelApi.update(id, data)
      const index = channels.value.findIndex(c => c.id === id)
      if (index !== -1) {
        channels.value[index] = channel
      }
      if (currentChannel.value?.id === id) {
        currentChannel.value = channel
      }
      return channel
    } catch (error) {
      console.error('[ChannelStore] Failed to update channel:', error)
      throw error
    }
  }

  async function deleteChannel(id: string) {
    try {
      await channelApi.delete(id)
      channels.value = channels.value.filter(c => c.id !== id)
      if (currentChannel.value?.id === id) {
        currentChannel.value = null
      }
    } catch (error) {
      console.error('[ChannelStore] Failed to delete channel:', error)
      throw error
    }
  }

  function clearCurrentChannel() {
    currentChannel.value = null
  }

  return {
    // State
    channels,
    total,
    loading,
    currentChannel,
    currentChannelLoading,
    // Getters
    channelList,
    hasChannels,
    // Actions
    fetchChannels,
    fetchChannel,
    createChannel,
    updateChannel,
    deleteChannel,
    clearCurrentChannel,
  }
})
