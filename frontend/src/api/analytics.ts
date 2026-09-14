import { api } from './client'
import type {
  DashboardOverviewParams,
  DashboardOverviewResponse,
  FunnelParams,
  FunnelResponse,
  LeadConversionParams,
  LeadConversionResponse,
  AgentPerformanceParams,
  AgentPerformanceLeaderboardResponse,
  PDCParams,
  PDCResponse,
  ConversationMetricsParams,
  ConversationMetricsResponse,
  MetricDefinition,
  MetricDefinitionListParams,
  MetricDefinitionListResponse,
  ExperimentListResponse,
  ExperimentResultSummaryResponse,
} from './analytics-types'

/**
 * Analytics API 层（Phase 6 / P6AN-10）。
 *
 * P6AN-10 范围：Dashboard 概览（P6AN-02）真实对接；
 * 漏斗 / 转化 / Agent 效能 / 实验端点一并提供 typed client，
 * 供 P6AN-11（漏斗/转化）与 P6AN-12（实验）直接复用，避免重复建层。
 *
 * 注意：这些路由是 FastAPI 原生路由，返回裸模型（非 {code,message,data}
 * 信封），client.ts 的响应拦截器会自动透传，无需信封解包。
 */

// ---- P6AN-02 Dashboard 概览 ----
export const analyticsDashboardApi = {
  /**
   * GET /analytics/dashboard/overview
   *
   * - time_range_start / time_range_end（ISO 8601）同时给出时优先于 days
   * - agent_id / channel 为可选维度过滤
   * - 服务端 5min 响应缓存；cached 标记由后端按服务时刻打戳
   */
  overview(params?: DashboardOverviewParams): Promise<DashboardOverviewResponse> {
    return api.get<DashboardOverviewResponse>(
      '/analytics/dashboard/overview',
      { params }
    )
  },
}

// ---- P6AN-04 会话质量与效率 ----
export const analyticsConversationApi = {
  /**
   * GET /analytics/conversations — P6AN-04 AI 会话质量与效率指标。
   * range 未知值后端回退 30d；空范围返回 has_data=false 的安全默认值（永不 500）。
   */
  metrics(
    params?: ConversationMetricsParams
  ): Promise<ConversationMetricsResponse> {
    return api.get<ConversationMetricsResponse>('/analytics/conversations', {
      params,
    })
  },
}

// ---- 指标定义（/analytics/metrics CRUD） ----
export const analyticsMetricDefinitionApi = {
  list(
    params?: MetricDefinitionListParams
  ): Promise<MetricDefinitionListResponse> {
    return api.get<MetricDefinitionListResponse>('/analytics/metrics', {
      params,
    })
  },

  detail(metricId: string): Promise<MetricDefinition> {
    return api.get<MetricDefinition>(
      `/analytics/metrics/${metricId}`
    )
  },
}

// ---- P6AN-03 获客漏斗 ----
export const analyticsFunnelApi = {
  /** GET /analytics/funnel — 内置/自定义漏斗的阶段到达量 + 转化率 */
  funnel(params?: FunnelParams): Promise<FunnelResponse> {
    return api.get<FunnelResponse>('/analytics/funnel', { params })
  },
}

// ---- P6AN-05 线索转化 ----
export const analyticsLeadConversionApi = {
  /** GET /analytics/leads/conversion — 线索转化指标（总览 + 分组） */
  conversion(params?: LeadConversionParams): Promise<LeadConversionResponse> {
    return api.get<LeadConversionResponse>(
      '/analytics/leads/conversion',
      { params }
    )
  },
}

// ---- P6AN-07 Agent 效能 ----
export const analyticsAgentPerformanceApi = {
  /** GET /analytics/agents/performance — Agent 效能排行榜 */
  leaderboard(
    params?: AgentPerformanceParams
  ): Promise<AgentPerformanceLeaderboardResponse> {
    return api.get<AgentPerformanceLeaderboardResponse>(
      '/analytics/agents/performance',
      { params }
    )
  },
}

// ---- P6AN-06 私域转化 ----
export const analyticsPrivateDomainApi = {
  /** GET /analytics/private-domain/conversion — 私域转化 + LTV + ROI 输入 */
  conversion(params?: PDCParams): Promise<PDCResponse> {
    return api.get<PDCResponse>('/analytics/private-domain/conversion', {
      params,
    })
  },
}

// ---- P6AN-08 实验 ----
export const analyticsExperimentApi = {
  /** GET /analytics/experiments — 实验列表（分页 + 状态过滤） */
  list(params?: {
    page?: number
    page_size?: number
    status?: string
  }): Promise<ExperimentListResponse> {
    return api.get<ExperimentListResponse>('/analytics/experiments', {
      params,
    })
  },

  /** GET /analytics/experiments/{id}/results/summary — 变组对比摘要 */
  resultSummary(
    experimentId: string
  ): Promise<ExperimentResultSummaryResponse> {
    return api.get<ExperimentResultSummaryResponse>(
      `/analytics/experiments/${experimentId}/results/summary`
    )
  },
}

export type {
  DashboardOverviewParams,
  DashboardOverviewResponse,
  FunnelParams,
  FunnelResponse,
  LeadConversionParams,
  LeadConversionResponse,
  AgentPerformanceParams,
  AgentPerformanceLeaderboardResponse,
  PDCParams,
  PDCResponse,
  ConversationMetricsParams,
  ConversationMetricsResponse,
  MetricDefinition,
  MetricDefinitionListParams,
  MetricDefinitionListResponse,
  ExperimentListResponse,
  ExperimentResultSummaryResponse,
} from './analytics-types'
