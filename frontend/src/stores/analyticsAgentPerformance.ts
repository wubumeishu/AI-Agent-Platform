import { defineStore } from 'pinia'
import { ref } from 'vue'
import { analyticsAgentPerformanceApi } from '@/api/analytics'
import type {
  AgentPerformanceMetrics,
  AgentPerformanceLeaderboardResponse,
  AgentPerformanceRange,
  AgentPerformanceSortKey,
  AgentPerformanceSingleResponse,
} from '@/api/analytics-types'

/** 排序列定义（排行榜表头点击可切换 sort key + 升降序） */
export interface AgentSortColumn {
  key: AgentPerformanceSortKey
  label: string
}

export const AGENT_SORT_COLUMNS: AgentSortColumn[] = [
  { key: 'name', label: '名称' },
  { key: 'conversations', label: '会话' },
  { key: 'messages', label: '消息' },
  { key: 'activity', label: '活跃度' },
  { key: 'conversion_rate', label: '转化率' },
  { key: 'satisfaction', label: '满意度' },
  { key: 'customers', label: '客户' },
]

const RANGES: Array<{ value: AgentPerformanceRange; label: string }> = [
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: '90d', label: '近 90 天' },
  { value: '365d', label: '近 365 天' },
  { value: 'all', label: '全部' },
]

export const AGENT_RANGE_OPTIONS = RANGES

/**
 * Agent 效能排行榜 store（Phase 6 / P6AN-12，对接 P6AN-07 API）。
 *
 * - 排行榜：可切换排序 key / 升降序 / 时间范围，支持分页；
 * - 单 Agent KPI 块：给 Agent 详情页等嵌入场景用（含 24 小时活跃直方图）。
 *
 * 状态机与 dashboardStore 保持一致：loading / error / hasLoaded，
 * 失败时保留旧数据降级展示。
 */
export const useAnalyticsAgentPerformanceStore = defineStore('analyticsAgentPerformance', () => {
  // ---- 排行榜 ----
  const leaderboard = ref<AgentPerformanceLeaderboardResponse | null>(null)
  const leaderboardLoading = ref(false)
  const leaderboardError = ref<string | null>(null)
  const leaderboardHasLoaded = ref(false)

  /** 当前排序（默认按会话数降序，与后端默认一致） */
  const sortKey = ref<AgentPerformanceSortKey>('conversations')
  const sortOrder = ref<'asc' | 'desc'>('desc')
  const range = ref<AgentPerformanceRange>('30d')
  const status = ref<string | null>(null)
  const keyword = ref<string | null>(null)
  const page = ref(1)
  const pageSize = ref(20)

  async function fetchLeaderboard(force = false): Promise<AgentPerformanceLeaderboardResponse | null> {
    if (!force && leaderboardHasLoaded.value && !leaderboardLoading.value) {
      return leaderboard.value
    }
    leaderboardLoading.value = true
    leaderboardError.value = null
    try {
      const data = await analyticsAgentPerformanceApi.leaderboard({
        range: range.value,
        sort: sortKey.value,
        order: sortOrder.value,
        status: status.value ?? undefined,
        name: keyword.value ?? undefined,
        page: page.value,
        page_size: pageSize.value,
      })
      leaderboard.value = data
      leaderboardHasLoaded.value = true
      return data
    } catch (err) {
      leaderboardError.value = (err as Error)?.message || 'Agent 排行榜加载失败'
      if (!leaderboardHasLoaded.value) leaderboard.value = null
      return null
    } finally {
      leaderboardLoading.value = false
    }
  }

  function refresh(): Promise<AgentPerformanceLeaderboardResponse | null> {
    return fetchLeaderboard(true)
  }

  /** 表头点击：同 key 再点切换方向；新 key 默认降序 */
  function toggleSort(key: AgentPerformanceSortKey) {
    if (sortKey.value === key) {
      sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
    } else {
      sortKey.value = key
      sortOrder.value = 'desc'
    }
    page.value = 1
    void refresh()
  }

  function setRange(r: AgentPerformanceRange) {
    range.value = r
    page.value = 1
    void refresh()
  }

  function setStatusFilter(s: string | null) {
    status.value = s
    page.value = 1
    void refresh()
  }

  function setKeyword(k: string | null) {
    keyword.value = k
    page.value = 1
    void refresh()
  }

  function setPage(p: number) {
    page.value = p
    void refresh()
  }

  /**
   * 排行榜空数据判定（窗口内全部 Agent 零活动）。
   * 后端对无数据 Agent 返回零值 KPI 块而非错误，因此空态要看业务字段。
   */
  const leaderboardIsEmpty = (resp: AgentPerformanceLeaderboardResponse | null) =>
    resp !== null &&
    resp.items.every(
      (row) =>
        row.conversation_count === 0 &&
        row.message_count === 0 &&
        row.lead_count === 0 &&
        row.total_customers === 0
    )

  // ---- 单 Agent KPI 块 ----
  const single = ref<AgentPerformanceSingleResponse | null>(null)
  const singleAgentId = ref<string | null>(null)
  const singleLoading = ref(false)
  const singleError = ref<string | null>(null)
  const singleHasLoaded = ref(false)

  async function fetchSingle(
    agentId: string,
    r: AgentPerformanceRange = range.value
  ): Promise<AgentPerformanceSingleResponse | null> {
    singleLoading.value = true
    singleError.value = null
    try {
      const data = await analyticsAgentPerformanceApi.single(agentId, { range: r })
      single.value = data
      singleAgentId.value = agentId
      singleHasLoaded.value = true
      return data
    } catch (err) {
      singleError.value = (err as Error)?.message || 'Agent 效能指标加载失败'
      if (!singleHasLoaded.value || singleAgentId.value !== agentId) {
        single.value = null
        singleAgentId.value = agentId
      }
      return null
    } finally {
      singleLoading.value = false
    }
  }

  function reset() {
    leaderboard.value = null
    leaderboardError.value = null
    leaderboardHasLoaded.value = false
    single.value = null
    singleAgentId.value = null
    singleError.value = null
    singleHasLoaded.value = false
  }

  return {
    // 排行榜
    leaderboard,
    leaderboardLoading,
    leaderboardError,
    leaderboardHasLoaded,
    sortKey,
    sortOrder,
    range,
    status,
    keyword,
    page,
    pageSize,
    fetchLeaderboard,
    refresh,
    toggleSort,
    setRange,
    setStatusFilter,
    setKeyword,
    setPage,
    leaderboardIsEmpty,
    // 单 Agent KPI 块
    single,
    singleAgentId,
    singleLoading,
    singleError,
    singleHasLoaded,
    fetchSingle,
    reset,
  }
})

/** 把 KPI 行格式化为 UI 文本（null = 无数据 → '—'） */
export function formatAgentRate(v: number | null): string {
  return v === null ? '—' : `${(v * 100).toFixed(1)}%`
}

export type { AgentPerformanceMetrics }
