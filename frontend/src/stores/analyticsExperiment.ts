import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analyticsExperimentApi } from '@/api/analytics'
import type {
  Experiment,
  ExperimentCreate,
  ExperimentResult,
  ExperimentResultCreate,
  ExperimentStatusUpdate,
  ExperimentUpdate,
  ExperimentResultSummaryResponse,
} from '@/api/analytics-types'

/** 实验状态（与后端 EXPERIMENT_STATUSES 一致） */
export const EXPERIMENT_STATUSES = [
  'draft',
  'running',
  'paused',
  'completed',
  'terminated',
] as const

export type ExperimentStatus = (typeof EXPERIMENT_STATUSES)[number]

/**
 * 状态机合法转换（镜像后端 EXPERIMENT_TRANSITIONS）：
 * draft → running / terminated
 * running → paused / completed / terminated
 * paused → running / terminated
 * completed / terminated → 终态
 */
export const EXPERIMENT_TRANSITIONS: Record<ExperimentStatus, ExperimentStatus[]> = {
  draft: ['running', 'terminated'],
  running: ['paused', 'completed', 'terminated'],
  paused: ['running', 'terminated'],
  completed: [],
  terminated: [],
}

export function allowedTransitions(status: string): ExperimentStatus[] {
  return EXPERIMENT_TRANSITIONS[status as ExperimentStatus] ?? []
}

/** 状态中文标签 */
export const EXPERIMENT_STATUS_LABELS: Record<ExperimentStatus, string> = {
  draft: '草稿',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  terminated: '已终止',
}

export const EXPERIMENT_STATUS_COLORS: Record<ExperimentStatus, string> = {
  draft: '#8a94a6',
  running: '#2f9e6b',
  paused: '#d98a2b',
  completed: '#3b7ddd',
  terminated: '#d9534f',
}

export function experimentStatusLabel(status: string): string {
  return EXPERIMENT_STATUS_LABELS[status as ExperimentStatus] ?? status
}

export function experimentStatusColor(status: string): string {
  return EXPERIMENT_STATUS_COLORS[status as ExperimentStatus] ?? '#8a94a6'
}

/**
 * 实验管理 store（Phase 6 / P6AN-12，对接 P6AN-08 API）。
 *
 * - 列表：分页 + 状态过滤；
 * - CRUD：创建（draft）/ 更新 / 软删除；
 * - 状态机：按 EXPERIMENT_TRANSITIONS 校验合法转换；terminated 必须带 reason；
 * - 结果：快照列表 + P6AN-08 变组对比摘要。
 *
 * 错误语义（沿用 P6AN-01/08）：
 * - 404 实验/结果不存在；
 * - 409 流量分配违例 / 非法状态转换 / 终止无原因；
 * 失败时保留旧数据降级展示。
 */
export const useAnalyticsExperimentStore = defineStore('analyticsExperiment', () => {
  // ---- 列表 ----
  const experiments = ref<Experiment[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(20)
  const statusFilter = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const hasLoaded = ref(false)

  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

  async function fetchList(): Promise<Experiment[] | null> {
    loading.value = true
    error.value = null
    try {
      const data = await analyticsExperimentApi.list({
        page: page.value,
        page_size: pageSize.value,
        status: statusFilter.value ?? undefined,
      })
      experiments.value = data.items
      total.value = data.total
      hasLoaded.value = true
      return data.items
    } catch (err) {
      error.value = (err as Error)?.message || '实验列表加载失败'
      if (!hasLoaded.value) {
        experiments.value = []
        total.value = 0
      }
      return null
    } finally {
      loading.value = false
    }
  }

  function refresh() {
    return fetchList()
  }

  function setPage(p: number) {
    page.value = p
    void fetchList()
  }

  function setStatusFilter(s: string | null) {
    statusFilter.value = s
    page.value = 1
    void fetchList()
  }

  // ---- 详情 ----
  const current = ref<Experiment | null>(null)

  async function fetchDetail(id: string): Promise<Experiment | null> {
    try {
      current.value = await analyticsExperimentApi.detail(id)
      return current.value
    } catch (err) {
      error.value = (err as Error)?.message || '实验详情加载失败'
      return null
    }
  }

  function clearCurrent() {
    current.value = null
  }

  // ---- 创建 / 更新 ----
  const saving = ref(false)

  async function createExperiment(payload: ExperimentCreate): Promise<Experiment | null> {
    saving.value = true
    error.value = null
    try {
      const exp = await analyticsExperimentApi.create(payload)
      // 创建后刷新列表（若创建者当前在列表页）
      await fetchList()
      return exp
    } catch (err) {
      const e = err as Error & { response?: { status?: number } }
      error.value =
        e.message?.includes('409') || e.response?.status === 409
          ? '流量份额校验失败：带份额的变组份额之和必须为 1.0'
          : e.message || '实验创建失败'
      return null
    } finally {
      saving.value = false
    }
  }

  async function updateExperiment(
    id: string,
    payload: ExperimentUpdate
  ): Promise<Experiment | null> {
    saving.value = true
    error.value = null
    try {
      const exp = await analyticsExperimentApi.update(id, payload)
      current.value = exp
      await fetchList()
      return exp
    } catch (err) {
      const e = err as Error & { response?: { status?: number } }
      error.value =
        e.response?.status === 409
          ? '流量份额校验失败：带份额的变组份额之和必须为 1.0'
          : e.message || '实验更新失败'
      return null
    } finally {
      saving.value = false
    }
  }

  // ---- 状态机 ----
  async function transitionStatus(
    id: string,
    target: ExperimentStatus,
    reason?: string
  ): Promise<Experiment | null> {
    error.value = null
    try {
      const exp = await analyticsExperimentApi.setStatus(id, {
        status: target,
        reason,
      } satisfies ExperimentStatusUpdate)
      current.value = exp
      await fetchList()
      return exp
    } catch (err) {
      const e = err as Error & { response?: { status?: number; data?: unknown } }
      error.value =
        e.response?.status === 409
          ? reason && target === 'terminated'
            ? '终止需要填写原因'
            : '当前状态不允许转换到该状态'
          : e.message || '状态转换失败'
      return null
    }
  }

  // ---- 删除 ----
  async function deleteExperiment(id: string): Promise<boolean> {
    error.value = null
    try {
      await analyticsExperimentApi.remove(id)
      current.value = null
      await fetchList()
      return true
    } catch (err) {
      error.value = (err as Error)?.message || '实验删除失败'
      return false
    }
  }

  // ---- 结果快照 ----
  const results = ref<ExperimentResult[]>([])
  const resultsTotal = ref(0)
  const resultsPage = ref(1)
  const resultsLoading = ref(false)
  const resultsError = ref<string | null>(null)

  async function fetchResults(id: string, page_ = 1): Promise<ExperimentResult[] | null> {
    resultsLoading.value = true
    resultsError.value = null
    try {
      const data = await analyticsExperimentApi.results(id, {
        page: page_,
        page_size: 20,
      })
      results.value = data.items
      resultsTotal.value = data.total
      resultsPage.value = data.page
      return data.items
    } catch (err) {
      resultsError.value = (err as Error)?.message || '结果快照加载失败'
      results.value = []
      resultsTotal.value = 0
      return null
    } finally {
      resultsLoading.value = false
    }
  }

  async function createResult(
    id: string,
    payload: ExperimentResultCreate
  ): Promise<ExperimentResult | null> {
    resultsError.value = null
    try {
      const res = await analyticsExperimentApi.createResult(id, payload)
      await fetchResults(id, resultsPage.value)
      return res
    } catch (err) {
      resultsError.value = (err as Error)?.message || '结果快照创建失败'
      return null
    }
  }

  // ---- P6AN-08 变组对比摘要 ----
  const summary = ref<ExperimentResultSummaryResponse | null>(null)
  const summaryLoading = ref(false)
  const summaryError = ref<string | null>(null)
  /** p 值判注阈值（默认 0.05，仅判注不做推断） */
  const significanceThreshold = ref(0.05)

  async function fetchSummary(
    id: string,
    threshold?: number
  ): Promise<ExperimentResultSummaryResponse | null> {
    summaryLoading.value = true
    summaryError.value = null
    if (threshold !== undefined) significanceThreshold.value = threshold
    try {
      const data = await analyticsExperimentApi.resultSummary(id, {
        significance_threshold: significanceThreshold.value,
      })
      summary.value = data
      return data
    } catch (err) {
      summaryError.value = (err as Error)?.message || '对比摘要加载失败'
      if (!summary.value) summary.value = null
      return null
    } finally {
      summaryLoading.value = false
    }
  }

  function reset() {
    experiments.value = []
    total.value = 0
    error.value = null
    hasLoaded.value = false
    current.value = null
    results.value = []
    resultsTotal.value = 0
    resultsError.value = null
    summary.value = null
    summaryError.value = null
  }

  return {
    // 列表
    experiments,
    total,
    page,
    pageSize,
    statusFilter,
    loading,
    error,
    hasLoaded,
    totalPages,
    fetchList,
    refresh,
    setPage,
    setStatusFilter,
    // 详情
    current,
    fetchDetail,
    clearCurrent,
    // CRUD
    saving,
    createExperiment,
    updateExperiment,
    deleteExperiment,
    // 状态机
    transitionStatus,
    // 结果
    results,
    resultsTotal,
    resultsPage,
    resultsLoading,
    resultsError,
    fetchResults,
    createResult,
    // P6AN-08 摘要
    summary,
    summaryLoading,
    summaryError,
    significanceThreshold,
    fetchSummary,
    reset,
  }
})
