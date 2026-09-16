// Phase 6 / P6AN-10: Analytics 前端框架 — 类型层
//
// 与后端 Pydantic schema 严格对齐（backend/app/schemas/*.py）：
// - dashboard.py            (P6AN-02 Dashboard 概览)
// - analytics.py            (P6AN-03 漏斗 / P6AN-08 Experiment)
// - lead_conversion.py      (P6AN-05 线索转化)
// - agent_performance.py    (P6AN-07 Agent 效能)
// - private_domain_conversion.py (P6AN-06 私域转化)
//
// 约定（与后端文档一致）：
// - 所有比率/代理值分母为 0 时为 null，前端必须按 "无数据" 渲染，
//   不得显示 0%（0% 是有意义的数值，null 是"分母为空"）。
// - P6AN-06 私域漏斗的 *_percent 字段是 0-100 的百分数（分母为 0 时返回 0.0），
//   与 P6AN-02/05/07 的 [0,1] 比率语义不同，渲染时注意区分。

// ===== P6AN-02 Dashboard 概览 =====

export interface DashboardRange {
  start: string
  end: string
  days: number
}

export interface AgentsOverview {
  total: number
  active: number
}

export interface ConversationsOverview {
  new: number
  active: number
  total_messages: number
  avg_messages_per_new_conversation: number | null
}

export interface MessagesOverview {
  total: number
  sent: number
  delivered: number
  failed: number
  success_rate: number | null
}

export interface ConversionOverview {
  new_leads: number
  total_leads: number
  closed_leads: number
  conversion_rate: number | null
}

export interface AgentStat {
  agent_id: string
  agent_name: string | null
  conversations: number
  messages: number
  message_success_rate: number | null
}

export interface DashboardOverviewResponse {
  range: DashboardRange
  agents: AgentsOverview
  conversations: ConversationsOverview
  messages: MessagesOverview
  conversion: ConversionOverview
  by_agent: AgentStat[]
  computed_at: string
  cached: boolean
  cache_ttl_seconds: number
}

export interface DashboardOverviewParams {
  /** ISO 8601 窗口起点（含），naive 视为 UTC；与 end 同时给出时优先生效 */
  time_range_start?: string
  /** ISO 8601 窗口终点（不含） */
  time_range_end?: string
  /** 无显式 range 时回看 N 天（1..365，默认 30） */
  days?: number
  /** Agent 维度过滤（UUID） */
  agent_id?: string
  /** 限定渠道（web / wechat / douyin / xiaohongshu / …） */
  channel?: string
}

// ===== P6AN-03 获客漏斗 =====

export interface FunnelStage {
  key: string
  name: string
  /** 该 stage 对应的 Lead.status（无法解析时为 null） */
  status: string | null
  /** 到达（累计）数量 */
  count: number
  /** 本阶段/上一阶段，首阶段或零分母为 null */
  conversion_rate: number | null
  /** 本阶段/顶部，零分母为 null */
  overall_rate: number | null
}

export interface FunnelResponse {
  funnel_code: string
  stages: FunnelStage[]
  total: number
  /** 端到端 顶→底 转化率（空数据为 null） */
  conversion_rate: number | null
  filters: Record<string, unknown>
}

export interface FunnelParams {
  agent_id?: string
  platform_id?: string
  /** 7d | 30d | 90d | 365d | all（lead.created_at 窗口预设） */
  range?: string
  /** ISO date/datetime 下界（覆盖 range）。后端 query 参数名为 from。 */
  from?: string
  /** ISO date/datetime 上界（exclusive，覆盖 range）。后端 query 参数名为 to。 */
  to?: string
  funnel_code?: string
}

// ===== P6AN-05 线索转化 =====

export interface LeadConversionMetrics {
  total_leads: number
  /** lead.status 计数 */
  status_counts: Record<string, number>
  /** 各阶段到达计数 */
  stage_reached_counts: Record<string, number>
  /** 各阶段转化率（[0,1]，零分母为 null） */
  conversion_rates: Record<string, number | null>
  avg_conversion_cycle_days: number | null
}

export interface LeadConversionGroup {
  /** agent 名称或小写渠道码 */
  key: string
  label: string
  metrics: LeadConversionMetrics
}

export interface LeadConversionFilters {
  agent_id: string | null
  channel: string | null
  from_date: string | null
  to_date: string | null
  group_by: string
  window_basis: string
}

export interface LeadConversionResponse {
  filters: LeadConversionFilters
  totals: LeadConversionMetrics
  groups: LeadConversionGroup[]
}

export interface LeadConversionParams {
  agent_id?: string
  channel?: string
  from_date?: string
  to_date?: string
  /** overall | agent | channel */
  group_by?: string
}

// ===== P6AN-07 Agent 效能 =====

export type AgentPerformanceSortKey =
  | 'conversations'
  | 'messages'
  | 'activity'
  | 'conversion_rate'
  | 'satisfaction'
  | 'customers'
  | 'name'
  | 'created_at'

export type AgentPerformanceRange = '7d' | '30d' | '90d' | '365d' | 'all'

export interface AgentPerformanceMetrics {
  agent_id: string
  agent_name: string
  status: string | null
  total_customers: number
  active_customers: number
  conversation_count: number
  message_count: number
  lead_count: number
  converted_lead_count: number
  /** [0,1]，lead_count == 0 时为 null */
  conversion_rate: number | null
  /** [0,1] 情绪代理分（positive=1.0/neutral=0.5/negative=0.0），无数据为 null */
  satisfaction_proxy: number | null
  satisfaction_sample: number
  sentiment_breakdown: Record<string, number>
  /** 24 桶 UTC 小时消息量直方图 */
  active_hours: number[]
  /** 消息量峰值小时（0-23），无消息为 null */
  peak_hour: number | null
}

export interface AgentPerformanceLeaderboardResponse {
  items: AgentPerformanceMetrics[]
  total_agents: number
  sort_key: string
  order: string
  page: number
  page_size: number
  window: Record<string, string | null>
}

export interface AgentPerformanceParams {
  range?: AgentPerformanceRange
  since?: string
  until?: string
  sort?: AgentPerformanceSortKey
  order?: 'asc' | 'desc'
  status?: string
  name?: string
  page?: number
  page_size?: number
}

/**
 * P6AN-07 单 Agent KPI 块：
 * GET /analytics/agents/performance/metrics/{agent_id}
 * 返回 { metrics, window } 信封（与排行榜的裸 KPI 块不同）。
 * Agent 不存在 → 404；无数据 → 零值 KPI 块（不是错误）。
 */
export interface AgentPerformanceSingleResponse {
  metrics: AgentPerformanceMetrics
  /** 实际应用的窗口（ISO-8601 since/until，或 all-time 预设标记） */
  window: Record<string, string | null>
}

// ===== P6AN-06 私域转化 =====

export interface PDCWindow {
  since: string
  until: string
  default_applied: boolean
}

export interface PDCFunnel {
  base_customers: number
  reached_customers: number
  interacted_customers: number
  converted_customers: number
  /** 0-100 百分数（分母为 0 → 0.0，与 [0,1] 比率语义不同） */
  reach_rate_percent: number
  interaction_rate_percent: number
  conversion_rate_percent: number
  reach_rate_overall_percent: number
  interaction_rate_overall_percent: number
  conversion_rate_overall_percent: number
}

export interface PDCltv {
  won_deal_count: number
  total_won_value_cents: number
  avg_won_deal_value_cents: number
  ltv_proxy_cents_per_reached: number
  currencies: string[]
}

export interface PDCNurtureExecution {
  total_attempts: number
  success_attempts: number
  executed_attempts: number
  execution_rate_percent: number
}

export interface PDCFollowUp {
  completed: number
  total: number
  completion_rate_percent: number
}

export interface PDCROIInputs {
  total_won_value_cents: number
  won_deal_count: number
  reached_customers: number
  base_customers: number
  ltv_proxy_cents_per_reached: number
}

export interface PDCResponse {
  window: PDCWindow
  agent_id: string | null
  account_id: string | null
  funnel: PDCFunnel
  ltv: PDCltv
  nurture_execution: PDCNurtureExecution
  follow_up: PDCFollowUp
  roi_inputs: PDCROIInputs
}

export interface PDCParams {
  agent_id?: string
  account_id?: string
  /** 默认回看 30 天 */
  since?: string
  until?: string
}

// ===== P6AN-04 会话质量与效率 =====

export interface ConversationMetricsPlatformBreakdown {
  channel: string
  conversations: number
  user_messages: number
  avg_duration_seconds: number
  positive_sentiment: number
  with_sentiment: number
  avg_rounds: number
  satisfaction_rate: number
}

export interface ConversationMetricsAgentBreakdown {
  agent_id: string
  agent_name: string | null
  conversations: number
  user_messages: number
  avg_rounds: number
}

export interface ConversationMetricsIntentBreakdown {
  intent_type: string
  total: number
  accurate: number
  avg_confidence: number
  accuracy: number
  is_escalating: boolean
}

export interface ConversationMetricsResponse {
  sample_size: number
  has_data: boolean
  window: Record<string, string>
  filters: Record<string, string | null>
  total_conversations: number
  avg_response_time_seconds: number
  avg_conversation_rounds: number
  /** PROXY：confidence>=阈值且匹配到 action 的 intent / 总 intent；无数据为 0.0 */
  intent_accuracy: number
  human_handoff_rate: number
  /** PROXY：正向情绪会话 / 带情绪标签会话；无数据为 0.0 */
  satisfaction_rate: number
  total_messages: number
  total_user_messages: number
  total_intents: number
  confident_intents: number
  accurate_intents: number
  escalating_intents: number
  handoff_conversations: number
  positive_sentiment: number
  with_sentiment: number
  avg_confidence: number
  avg_duration_seconds: number
  accuracy_threshold: number
  by_platform: ConversationMetricsPlatformBreakdown[]
  by_agent: ConversationMetricsAgentBreakdown[]
  by_intent: ConversationMetricsIntentBreakdown[]
}

export interface ConversationMetricsParams {
  agent_id?: string
  /** 1d | 7d | 30d | 90d | 365d（未知值后端回退 30d） */
  range?: string
  intent_type?: string
  channel?: string
  /** 0.0 - 1.0，intent 准确率阈值 */
  accuracy_threshold?: number
}

// ===== 指标定义（/analytics/metrics CRUD） =====

export interface MetricDefinition {
  id: string
  code: string
  name: string
  description?: string | null
  category: string
  value_type: string
  unit?: string | null
  aggregation?: string | null
  formula: Record<string, unknown>
  source?: string | null
  window_days: number
  enabled: boolean
  account_id?: string | null
  created_at: string
  updated_at: string
}

export interface MetricDefinitionListResponse {
  items: MetricDefinition[]
  total: number
  page: number
  page_size: number
}

export interface MetricDefinitionListParams {
  category?: string
  enabled?: boolean
  page?: number
  page_size?: number
}

// ===== P6AN-08 实验 =====

export interface ExperimentVariant {
  label: string
  /** 0-1 流量份额；P6AN-08 起带份额时全部 variants 份额之和必须 = 1.0（±1e-6），违例 409 */
  share?: number
  config?: Record<string, unknown>
}

export interface Experiment {
  id: string
  code: string
  name: string
  description?: string | null
  hypothesis?: string | null
  /** 后端 primary_metric_code 可空（旧实验未填主指标） */
  primary_metric_code?: string | null
  secondary_metric_codes?: string[]
  /** 原始 variants dict 列表（{label, share?, config?}，share 可缺省） */
  variants: ExperimentVariant[]
  /** draft | running | paused | completed | terminated */
  status: string
  owner?: string | null
  started_at?: string | null
  ended_at?: string | null
  account_id?: string | null
  created_at: string
  updated_at: string
}

/** POST /experiments（创建固定 draft 状态） */
export interface ExperimentCreate {
  /** ^[a-z0-9_-]+$，1-100 字符 */
  code: string
  name: string
  description?: string
  hypothesis?: string
  /** 注册指标 code */
  primary_metric_code?: string | null
  secondary_metric_codes?: string[]
  /** 变组配置，如 [{label:'control',share:0.5,config:{}}] */
  variants?: ExperimentVariant[]
  owner?: string
}

/** PUT /experiments/{id}（code 不可改；variants 变更时重新校验流量分配，违例 409） */
export interface ExperimentUpdate {
  name?: string
  description?: string
  hypothesis?: string
  primary_metric_code?: string | null
  secondary_metric_codes?: string[]
  variants?: ExperimentVariant[]
  owner?: string
}

/**
 * POST /experiments/{id}/status — 状态机（后端按 EXPERIMENT_TRANSITIONS 校验）：
 * draft → running / terminated；running → paused / completed / terminated；
 * paused → running / terminated；completed / terminated 为终态。
 * 非法转换 → 409；terminated 必须带非空 reason。
 */
export interface ExperimentStatusUpdate {
  status: string
  /** 终止原因（status='terminated' 时必填） */
  reason?: string
}

export interface ExperimentListResponse {
  items: Experiment[]
  total: number
  page: number
  page_size: number
}

// ---- P6AN-08 实验结果快照 ----

export interface ExperimentResult {
  id: string
  experiment_id: string
  variant_label: string
  metric_code: string
  sample_size: number
  /** 后端 Decimal 序列化为字符串 */
  metric_value: string
  baseline_value?: string | null
  lift_percent?: string | null
  p_value?: string | null
  is_significant?: boolean | null
  stats?: Record<string, unknown>
  computed_at: string
}

export interface ExperimentResultCreate {
  variant_label: string
  metric_code: string
  sample_size?: number
  /** 数字或数字字符串（后端 Decimal，最多 6 位小数） */
  metric_value: number | string
  baseline_value?: number | string | null
  /** 相对基线提升百分比（0-100 小数形式如 12.5 = 12.5%） */
  lift_percent?: number | string | null
  /** 0-1 */
  p_value?: number | string | null
  is_significant?: boolean | null
  stats?: Record<string, unknown>
  computed_at?: string
}

export interface ExperimentResultListResponse {
  items: ExperimentResult[]
  total: number
  page: number
  page_size: number
}

// ---- P6AN-08 结果对比摘要（GET /experiments/{id}/results/summary） ----

/** 一个变组在某指标下的最新快照行（数值为 Decimal 字符串） */
export interface ExperimentResultSummaryRow {
  variant_label: string
  metric_value: string
  sample_size: number
  baseline_value?: string | null
  computed_at: string
  /** 相对基线变组的提升百分比；基线缺失或为 0 时为 null */
  lift_vs_baseline_percent?: string | null
  p_value?: string | null
  is_significant?: boolean | null
}

export interface ExperimentResultSummaryMetric {
  metric_code: string
  /** 是否为实验主指标 */
  is_primary: boolean
  baseline_variant?: string | null
  /** 纯文字显著性/对比说明（本波不引入统计推断库） */
  note?: string
  variants: ExperimentResultSummaryRow[]
}

export interface ExperimentResultSummaryResponse {
  experiment_id: string
  code: string
  name: string
  status: string
  /** 基线变组 label：优先 'control'，否则第一个变组；无变组为 null */
  baseline_variant: string | null
  significance_threshold: number
  metrics: ExperimentResultSummaryMetric[]
  notes: string[]
}
