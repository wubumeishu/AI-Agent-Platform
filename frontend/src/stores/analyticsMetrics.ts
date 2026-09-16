import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  analyticsConversationApi,
  analyticsMetricDefinitionApi,
} from '@/api/analytics'
import { useAnalyticsOptionsStore } from './analyticsOptions'
import type {
  ConversationMetricsResponse,
  ConversationMetricsParams,
  MetricDefinition,
  MetricDefinitionListParams,
  MetricDefinitionListResponse,
} from '@/api/analytics-types'

/**
 * Analytics 指标 store（Phase 6 / P6AN-10 框架）。
 *
 * 承载 P6AN-04 会话质量与效率指标（headline 指标 + 分维度拆解）以及
 * 指标定义（/analytics/metrics 注册表）。P6AN-12 的指标 UI 直接消费本 store。
 *
 * 状态机与 dashboardStore / funnelStore 保持一致：
 * loading / error / hasLoaded / 失败时保留旧数据降级。
 */
export const useAnalyticsMetricsStore = defineStore('analyticsMetrics', () => {
  const options = useAnalyticsOptionsStore()

  // ---- P6AN-04 会话质量与效率指标 ----
  const conversationMetrics = ref<ConversationMetricsResponse | null>(null)
  const metricsLoading = ref(false)
  const metricsError = ref<string | null>(null)
  const metricsHasLoaded = ref(false)

  /** 无数据（has_data=false 或 sample_size=0）时 UI 展示空态而非 0% */
  const conversationMetricsEmpty = computed(() => {
    if (!conversationMetrics.value) return false
    return !conversationMetrics.value.has_data || conversationMetrics.value.sample_size === 0
  })

  /**
   * 拉取 P6AN-04 会话指标。复用 options 的 Agent / 渠道过滤；
   * range 预设与 intent_type / accuracy_threshold 通过 extra 透传。
   */
  async function fetchConversationMetrics(
    extra?: Partial<ConversationMetricsParams>
  ): Promise<ConversationMetricsResponse | null> {
    metricsLoading.value = true
    metricsError.value = null
    try {
      const data = await analyticsConversationApi.metrics({
        agent_id: options.agentId ?? undefined,
        channel: options.channel ?? undefined,
        ...extra,
      })
      conversationMetrics.value = data
      metricsHasLoaded.value = true
      return data
    } catch (err) {
      metricsError.value = (err as Error)?.message || '会话指标加载失败'
      if (!metricsHasLoaded.value) conversationMetrics.value = null
      return null
    } finally {
      metricsLoading.value = false
    }
  }

  // ---- 指标定义注册表 ----
  const metricDefinitions = ref<MetricDefinition[]>([])
  const metricDefinitionsTotal = ref(0)
  const metricDefinitionsLoading = ref(false)
  const metricDefinitionsError = ref<string | null>(null)

  async function fetchMetricDefinitions(
    params?: MetricDefinitionListParams
  ): Promise<MetricDefinitionListResponse | null> {
    metricDefinitionsLoading.value = true
    metricDefinitionsError.value = null
    try {
      const data = await analyticsMetricDefinitionApi.list(params)
      metricDefinitions.value = data.items
      metricDefinitionsTotal.value = data.total
      return data
    } catch (err) {
      metricDefinitionsError.value = (err as Error)?.message || '指标定义加载失败'
      metricDefinitions.value = []
      metricDefinitionsTotal.value = 0
      return null
    } finally {
      metricDefinitionsLoading.value = false
    }
  }

  function reset() {
    conversationMetrics.value = null
    metricsError.value = null
    metricsHasLoaded.value = false
    metricDefinitions.value = []
    metricDefinitionsTotal.value = 0
    metricDefinitionsError.value = null
  }

  return {
    // P6AN-04 会话指标
    conversationMetrics,
    metricsLoading,
    metricsError,
    metricsHasLoaded,
    conversationMetricsEmpty,
    fetchConversationMetrics,
    // 指标定义注册表
    metricDefinitions,
    metricDefinitionsTotal,
    metricDefinitionsLoading,
    metricDefinitionsError,
    fetchMetricDefinitions,
    reset,
  }
})
