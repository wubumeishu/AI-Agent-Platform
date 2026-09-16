import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analyticsFunnelApi } from '@/api/analytics'
import { useAnalyticsOptionsStore } from './analyticsOptions'
import type { FunnelResponse, FunnelParams } from '@/api/analytics-types'

/**
 * Analytics 漏斗 store（Phase 6 / P6AN-10 框架）。
 *
 * P6AN-10 只负责把 typed API 接入 + 状态机（loading/error/空态）落地；
 * 漏斗 UI（P6AN-11）直接消费本 store 的 funnel / loading / error / isEmpty。
 */
export const useAnalyticsFunnelStore = defineStore('analyticsFunnel', () => {
  const options = useAnalyticsOptionsStore()

  const funnel = ref<FunnelResponse | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const hasLoaded = ref(false)

  const isEmpty = computed(
    () =>
      hasLoaded.value &&
      funnel.value !== null &&
      funnel.value.stages.length > 0 &&
      funnel.value.total === 0
  )

  /**
   * 拉取获客漏斗。默认复用 options store 的 Agent / 渠道过滤；
   * P6AN-11 的漏斗专属控件（range 预设 / funnel_code）通过 extra 透传。
   */
  async function fetchFunnel(extra?: Partial<FunnelParams>): Promise<FunnelResponse | null> {
    loading.value = true
    error.value = null
    try {
      const data = await analyticsFunnelApi.funnel({
        agent_id: options.agentId ?? undefined,
        ...extra,
      })
      funnel.value = data
      hasLoaded.value = true
      return data
    } catch (err) {
      error.value = (err as Error)?.message || '漏斗数据加载失败'
      if (!hasLoaded.value) funnel.value = null
      return null
    } finally {
      loading.value = false
    }
  }

  function reset() {
    funnel.value = null
    error.value = null
    hasLoaded.value = false
  }

  return {
    funnel,
    loading,
    error,
    hasLoaded,
    isEmpty,
    fetchFunnel,
    reset,
  }
})
