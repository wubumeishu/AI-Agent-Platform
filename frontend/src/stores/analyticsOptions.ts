import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAgentStore } from '@/stores/agent'

/**
 * Analytics 共享过滤器（Phase 6 / P6AN-10）。
 *
 * Dashboard / 漏斗 / 指标三个视图共用的维度过滤状态（时间窗口、Agent、渠道），
 * 各 store 与视图从这里读取过滤条件，避免逐层 prop drilling。
 * 后端端点对这些参数都有默认值；这里 null 表示"不传，用后端默认"。
 *
 * 注意：这里的 channel 是会话/渠道消息上的渠道码（web / wechat / douyin /
 * xiaohongshu / …，即 conversation.channel），不是私域 Channel 实体。
 */
export const useAnalyticsOptionsStore = defineStore('analyticsOptions', () => {
  const agentStore = useAgentStore()

  /** 时间窗口（Dashboard 用 days 参数，1..365） */
  const days = ref<number>(30)

  /** Agent 维度过滤（null = 不过滤） */
  const agentId = ref<string | null>(null)

  /** 渠道码维度过滤（null = 不过滤） */
  const channel = ref<string | null>(null)

  const filterActive = computed(
    () => agentId.value !== null || channel.value !== null
  )

  // ---- Agent 下拉 ----
  const agentsLoaded = ref(false)

  async function loadAgents() {
    if (agentsLoaded.value) return
    try {
      await agentStore.fetchAgents({ page: 1, page_size: 200 })
      agentsLoaded.value = true
    } catch (error) {
      // Agent 列表加载失败不阻塞过滤器本身（过滤选择降级为不可用）
      console.error('[AnalyticsOptions] Failed to load agents:', error)
    }
  }

  function setAgent(agent: string | null) {
    agentId.value = agent ? agent : null
  }

  function setChannel(c: string | null) {
    channel.value = c ? c : null
  }

  /** 渠道码选项（后端文档列出的渠道值） */
  const channelOptions = ['web', 'wechat', 'douyin', 'xiaohongshu']

  function reset() {
    agentId.value = null
    channel.value = null
    days.value = 30
  }

  return {
    days,
    agentId,
    channel,
    filterActive,
    agentsLoaded,
    loadAgents,
    setAgent,
    setChannel,
    channelOptions,
    reset,
  }
})
