import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analyticsDashboardApi } from '@/api/analytics'
import { useAnalyticsOptionsStore } from './analyticsOptions'
import type { DashboardOverviewResponse } from '@/api/analytics-types'

/**
 * Analytics Dashboard store（Phase 6 / P6AN-10，对接 P6AN-02 API）。
 *
 * 数据流：
 *   视图 → store.fetchOverview() → analyticsDashboardApi（读 analyticsOptions 的过滤）
 *   视图 ← overview / loading / error / hasOverview ← store
 *
 * 过滤条件放在 analyticsOptions store（时间窗口 / Agent / 渠道），
 * 本 store 在 fetch 时读取并透传给 API，视图无需逐层传 props。
 */
export const useAnalyticsDashboardStore = defineStore('analyticsDashboard', () => {
  const options = useAnalyticsOptionsStore()

  const overview = ref<DashboardOverviewResponse | null>(null)
  const loading = ref(false)
  /** 加载失败的错误文案（null = 无错误） */
  const error = ref<string | null>(null)
  /** 是否有一次成功的 fetch（区分"从未加载"与"加载失败"） */
  const hasLoaded = ref(false)

  const hasOverview = computed(() => overview.value !== null)

  /** 最近一次成功加载时间（用于 UI 提示"更新于 …"） */
  const lastUpdated = ref<Date | null>(null)

  async function fetchOverview(force = false): Promise<DashboardOverviewResponse | null> {
    // 已有数据且非强制刷新时复用（避免过滤未变时的重复请求）
    if (!force && hasLoaded.value && !loading.value) return overview.value

    loading.value = true
    error.value = null
    try {
      const data = await analyticsDashboardApi.overview({
        days: options.days,
        agent_id: options.agentId ?? undefined,
        channel: options.channel ?? undefined,
      })
      overview.value = data
      hasLoaded.value = true
      lastUpdated.value = new Date()
      return data
    } catch (err) {
      error.value = (err as Error)?.message || 'Dashboard 概览加载失败'
      // 失败时保留旧数据（若有），让 UI 可以降级展示 + 顶部错误条
      if (!hasLoaded.value) overview.value = null
      return null
    } finally {
      loading.value = false
    }
  }

  /** 过滤条件变化后刷新（选项 store 的 watcher 会调用） */
  async function refresh(): Promise<DashboardOverviewResponse | null> {
    return fetchOverview(true)
  }

  function reset() {
    overview.value = null
    error.value = null
    hasLoaded.value = false
    lastUpdated.value = null
  }

  return {
    overview,
    loading,
    error,
    hasLoaded,
    hasOverview,
    lastUpdated,
    fetchOverview,
    refresh,
    reset,
  }
})
