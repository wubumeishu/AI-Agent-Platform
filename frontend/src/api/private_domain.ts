// Private Domain 相关类型

// 分页响应（复用）
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// 渠道相关类型
export type ChannelType = 'wechat' | 'wechat_work' | 'email' | 'sms' | 'whatsapp' | 'line' | 'other'
export type ChannelStatus = 'active' | 'inactive' | 'paused' | 'online' | 'offline' | 'error'

export interface ChannelListParams {
  account_id?: string
  platform_id?: string
  channel_type?: ChannelType
  status?: ChannelStatus
  page?: number
  page_size?: number
}

export interface Channel {
  id: string
  account_id: string
  platform_id: string
  channel_type: ChannelType
  name: string
  description?: string
  contact_info?: Record<string, unknown>
  avatar_url?: string
  status: ChannelStatus
  connection_status?: string
  last_connection?: string
  contact_count: number
  message_count: number
  tags?: string[]
  extra_config?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CreateChannelRequest {
  account_id: string
  platform_id: string
  channel_type: ChannelType
  name: string
  description?: string
  contact_info?: Record<string, unknown>
  avatar_url?: string
  tags?: string[]
  extra_config?: Record<string, unknown>
}

export interface UpdateChannelRequest {
  platform_id?: string
  name?: string
  description?: string
  contact_info?: Record<string, unknown>
  avatar_url?: string
  status?: ChannelStatus
  connection_status?: string
  tags?: string[]
  extra_config?: Record<string, unknown>
}

// 培育计划相关类型
export type NurtureStatus = 'draft' | 'active' | 'paused' | 'completed' | 'archived'
export type ScheduleType = 'fixed' | 'drip' | 'triggered'

export interface NurtureStep {
  order: number
  delay_hours?: number
  content_id?: string
  action?: string
}

export interface NurturePlan {
  id: string
  account_id: string
  channel_id: string
  name: string
  description?: string
  status: NurtureStatus
  schedule_type: ScheduleType
  schedule_config?: Record<string, unknown>
  sequence_steps?: NurtureStep[]
  trigger_conditions?: Record<string, unknown>[]
  target_segment_id?: string
  created_at: string
  updated_at: string
}

export interface CreateNurtureRequest {
  account_id: string
  channel_id: string
  name: string
  description?: string
  schedule_type?: ScheduleType
  schedule_config?: Record<string, unknown>
  sequence_steps?: NurtureStep[]
  trigger_conditions?: Record<string, unknown>[]
  target_segment_id?: string
}

export interface UpdateNurtureRequest {
  name?: string
  description?: string
  status?: NurtureStatus
  schedule_type?: ScheduleType
  schedule_config?: Record<string, unknown>
  sequence_steps?: NurtureStep[]
  trigger_conditions?: Record<string, unknown>[]
  target_segment_id?: string
}

// 客户群相关类型
export type SegmentType = 'manual' | 'automatic' | 'dynamic'
export type FilterOperator = 'eq' | 'neq' | 'gt' | 'lt' | 'in' | 'contains'

export interface SegmentFilter {
  field: string
  operator: FilterOperator
  value: unknown
}

export interface Segment {
  id: string
  account_id: string
  name: string
  description?: string
  segment_type: SegmentType
  filter_config?: Record<string, unknown>
  filters?: SegmentFilter[]
  member_count: number
  last_synced_at?: string
  created_at: string
  updated_at: string
}

export interface SegmentStats {
  segment_id: string
  total_customers: number
  active_customers: number
  new_customers: number
  churned_customers: number
  engagement_score: number
}

export interface CreateSegmentRequest {
  account_id: string
  name: string
  description?: string
  segment_type?: SegmentType
  filter_config?: Record<string, unknown>
}

export interface UpdateSegmentRequest {
  name?: string
  description?: string
  filter_config?: Record<string, unknown>
}

export interface SegmentMember {
  id: string
  customer_id: string
  added_at: string
  added_by?: string
}

// 商机漏斗相关类型
export type PipelineType = 'sales' | 'marketing' | 'support'
export type DealStatus = 'open' | 'won' | 'lost' | 'draft'
export type DealPriority = 'low' | 'medium' | 'high' | 'urgent'

export interface DealPipeline {
  id: string
  account_id: string
  name: string
  description?: string
  pipeline_type: PipelineType
  is_default: boolean
  stages?: DealStage[]
  created_at: string
  updated_at: string
}

export interface DealStage {
  id: string
  pipeline_id: string
  name: string
  order: number
  probability: number
  status: 'active' | 'inactive'
  config?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DealItem {
  id: string
  pipeline_id: string
  stage_id?: string
  account_id: string
  name: string
  description?: string
  value?: number
  currency: string
  status: DealStatus
  priority?: DealPriority
  expected_close_date?: string
  customer_id?: string
  lead_id?: string
  winner_reason?: string
  loser_reason?: string
  created_at: string
  updated_at: string
}

export interface DealPipelineStats {
  pipeline_id: string
  pipeline_name: string
  pipeline_type: string
  total_deals: number
  open_deals: number
  won_deals: number
  lost_deals: number
  total_value: number
  won_value: number
  open_value: number
  conversion_rate: number
  stages: DealStageStats[]
}

export interface DealStageStats {
  stage_id: string
  stage_name: string
  deal_count: number
  total_value: number
  probability: number
}

export interface AccountPipelineStats {
  pipeline_id: string
  pipeline_name: string
  total_deals: number
  won_deals: number
  conversion_rate: number
  total_value: number
  won_value: number
}

export interface CreateDealRequest {
  account_id: string
  pipeline_id: string
  name: string
  description?: string
  value?: number
  currency?: string
  stage_id?: string
  customer_id?: string
  lead_id?: string
}

export interface UpdateDealRequest {
  name?: string
  description?: string
  value?: number
  expected_close_date?: string
  stage_id?: string
  status?: DealStatus
  winner_reason?: string
  loser_reason?: string
}

export interface DealTransition {
  stage_id: string
  status?: DealStatus
  winner_reason?: string
  loser_reason?: string
}

export interface CreatePipelineRequest {
  account_id: string
  name: string
  description?: string
  pipeline_type?: PipelineType
  is_default?: boolean
  stages?: CreateStageRequest[]
}

export interface UpdatePipelineRequest {
  name?: string
  description?: string
  stages?: CreateStageRequest[]
}

export interface CreateStageRequest {
  name: string
  order?: number
  probability?: number
  config?: Record<string, unknown>
}

// 内容相关类型
export type ContentType = 'text' | 'image' | 'video' | 'pdf' | 'html'
export type ContentStatus = 'draft' | 'published' | 'archived' | 'deleted'

export interface Content {
  id: string
  account_id: string
  channel_id?: string
  content_type: ContentType
  title: string
  summary?: string
  body?: string
  media_urls?: string[]
  tags?: string[]
  category?: string
  status: ContentStatus
  version: number
  usage_count: number
  last_used_at?: string
  created_at: string
  updated_at: string
}

export interface CreateContentRequest {
  account_id: string
  channel_id?: string
  content_type: ContentType
  title: string
  summary?: string
  body?: string
  media_urls?: string[]
  tags?: string[]
  category?: string
}

export interface UpdateContentRequest {
  title?: string
  summary?: string
  body?: string
  media_urls?: string[]
  tags?: string[]
  category?: string
  status?: ContentStatus
}

export interface ContentSearchFilter {
  keyword?: string
  content_type?: ContentType
  category?: string
  status?: ContentStatus
  tag?: string
  min_usage_count?: number
  max_usage_count?: number
  date_from?: string
  date_to?: string
  sort_by?: 'created_at' | 'updated_at' | 'usage_count' | 'title'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

// 跟进任务相关类型
export type TaskType = 'call' | 'email' | 'wechat' | 'meeting' | 'sms' | 'other'
export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled' | 'overdue'

export interface FollowUpTask {
  id: string
  account_id: string
  task_type: TaskType
  title: string
  description?: string
  priority: number
  scheduled_at?: string
  due_date?: string
  reminder_config?: Record<string, unknown>
  status: TaskStatus
  customer_id?: string
  lead_id?: string
  assigned_to?: string
  created_by?: string
  result?: Record<string, unknown>
  notes?: string
  created_at: string
  updated_at: string
}

export interface CreateTaskRequest {
  account_id: string
  task_type: TaskType
  title: string
  description?: string
  priority?: number
  scheduled_at?: string
  due_date?: string
  reminder_config?: Record<string, unknown>
  customer_id?: string
  lead_id?: string
  assigned_to?: string
  status?: TaskStatus
}

export interface UpdateTaskRequest {
  title?: string
  description?: string
  status?: TaskStatus
  priority?: number
  scheduled_at?: string
  due_date?: string
  result?: Record<string, unknown>
  notes?: string
  assigned_to?: string
}
