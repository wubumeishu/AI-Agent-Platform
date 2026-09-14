// 分页响应
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// Agent 相关类型
export interface Agent {
  id: string
  name: string
  description: string
  status: 'running' | 'stopped' | 'error'
  persona_name?: string
  icon?: string
  created_at: string
  updated_at: string
}

export interface AgentListParams {
  page?: number
  page_size?: number
  status?: string
  search?: string
}

export interface CreateAgentRequest {
  name: string
  description?: string
}

export interface UpdateAgentRequest {
  name?: string
  description?: string
}

// Persona 相关类型
export interface Personality {
  tone: 'professional' | 'friendly' | 'casual' | string
  reply_length: 'concise' | 'detailed' | 'balanced' | string
  proactiveness: 'low' | 'medium' | 'high' | string
  style_boundaries: string[]
}

export interface Persona {
  id: string
  name: string
  description: string
  personality: Personality
  version: number
  parent_id?: string
  icon?: string
  created_at: string
  updated_at: string
}

export interface CreatePersonaRequest {
  name: string
  description?: string
  personality: Personality
}

export interface UpdatePersonaRequest extends Partial<CreatePersonaRequest> {}

// Account 相关类型
export interface Account {
  id: string
  platform_id: string
  name: string
  username?: string
  status: 'connected' | 'disconnected' | 'failed'
  last_login?: string
  created_at: string
  updated_at: string
}

export interface CreateAccountRequest {
  platform_id: string
  name: string
  username?: string
  password?: string
  profile_id?: string
}

export interface UpdateAccountRequest {
  name?: string
  username?: string
  password?: string
}

// Platform 相关类型
export interface Platform {
  id: string
  code: string
  name: string
  capabilities: string[]
  adapter_class?: string
  config?: Record<string, unknown>
  status: 'active' | 'inactive'
  created_at: string
}

export interface CreatePlatformRequest {
  code: string
  name: string
  capabilities: string[]
  adapter_class?: string
  config?: Record<string, unknown>
}

// Browser 相关类型
export interface BrowserProfile {
  id: string
  provider: string
  profile_id: string
  name?: string
  connection_status: 'connected' | 'disconnected'
  created_at: string
  updated_at: string
}

export interface BrowserProviderStatus {
  connected: boolean
  version?: string
  profiles_count: number
}

// Proxy 相关类型
export type ProxyType = 'http' | 'https' | 'socks5'
export type ProxyStatus = 'active' | 'inactive' | 'failed'

export interface Proxy {
  id: string
  name: string
  type: ProxyType
  host: string
  port: number
  username?: string
  status: ProxyStatus
  last_tested?: string
  created_at: string
  updated_at: string
}

export interface CreateProxyRequest {
  name: string
  type: ProxyType
  host: string
  port: number
  username?: string
  password?: string
}

export interface UpdateProxyRequest {
  name?: string
  host?: string
  port?: number
  username?: string
  password?: string
}

// 绑定关系类型
export interface AgentPersonaBinding {
  agent_id: string
  persona_id: string
  is_primary: boolean
  bound_at: string
}

export interface AccountBrowserBinding {
  account_id: string
  profile_id: string
  bound_at: string
}

export interface AccountProxyBinding {
  account_id: string
  proxy_id: string
  bound_at: string
}

// Lead 相关类型
export type LeadStatus = 'new' | 'contacted' | 'qualified' | 'proposal' | 'negotiation' | 'won' | 'lost'
export type SourceType = 'web' | 'referral' | 'ad' | 'social' | 'search' | 'conversation' | 'other'

export interface LeadTag {
  id: string
  name: string
  color?: string
}

export interface LifecycleLog {
  id: string
  old_stage_code?: string
  new_stage_code: string
  transition_reason?: string
  operator?: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface Lead {
  id: string
  customer_id?: string
  lifecycle_stage_code?: string
  intent_score?: number
  source_type?: SourceType
  source_id?: string
  status: LeadStatus
  notes?: string
  operator?: string
  tags: LeadTag[]
  lifecycle_logs?: LifecycleLog[]
  created_at: string
  updated_at: string
}

export interface LeadListParams {
  customer_id?: string
  status?: LeadStatus
  lifecycle_stage?: string
  skip?: number
  limit?: number
}

export interface LeadListResponse {
  total: number
  skip: number
  limit: number
  data: Lead[]
}

export interface CreateLeadRequest {
  customer_id?: string
  lifecycle_stage_code?: string
  intent_score?: number
  source_type?: SourceType
  source_id?: string
  status?: LeadStatus
  notes?: string
  operator?: string
}

export interface UpdateLeadRequest {
  lifecycle_stage_code?: string
  intent_score?: number
  status?: LeadStatus
  notes?: string
  operator?: string
}

export interface LifecycleTransition {
  lead_id: string
  new_stage_code: string
  reason?: string
  operator?: string
  metadata?: Record<string, unknown>
}

// Lifecycle 相关类型
export interface LifecycleStage {
  code: string
  name: string
  description?: string
  sort_order: number
  config?: Record<string, unknown>
}

export interface LifecycleTransition {
  lead_id: string
  new_stage_code: string
  reason?: string
  operator?: string
  metadata?: Record<string, unknown>
}

// Customer 相关类型
export type CustomerStage = 'prospect' | 'qualified' | 'lead' | 'customer' | 'churned' | string

export interface CustomerIdentity {
  id: string
  platform: string
  platform_account_id?: string
  platform_username?: string
  phone?: string
  email?: string
  external_id?: string
  match_score?: number
  confidence?: string
  source?: string
  created_at?: string
}

export interface CustomerTag {
  id: string
  name: string
  color?: string
}

export interface Customer {
  id: string
  name: string
  email?: string
  phone?: string
  company?: string
  avatar_url?: string
  stage?: CustomerStage
  tags: CustomerTag[]
  identities: CustomerIdentity[]
  created_at: string
  updated_at: string
}

export interface CustomerListParams {
  page?: number
  page_size?: number
  name?: string
  phone?: string
  email?: string
  tag_ids?: string
  stage_code?: string
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export interface CustomerListResponse {
  total: number
  skip: number
  limit: number
  data: Customer[]
}

export interface CreateCustomerRequest {
  name: string
  email?: string
  phone?: string
  company?: string
}

export interface UpdateCustomerRequest {
  name?: string
  email?: string
  phone?: string
  company?: string
}

// Tag 相关类型
export type TagColor = 'blue' | 'green' | 'yellow' | 'red' | 'purple' | 'gray' | string

export interface Tag {
  id: string
  name: string
  description?: string
  color?: TagColor
  parent_id?: string
  level?: number
  customer_count?: number
  lead_count?: number
  created_at: string
  updated_at: string
}

export interface TagListParams {
  page?: number
  page_size?: number
  search?: string
  parent_id?: string
}

export interface CreateTagRequest {
  name: string
  description?: string
  color?: TagColor
  parent_id?: string
}

export interface UpdateTagRequest {
  name?: string
  description?: string
  color?: TagColor
  parent_id?: string
}

// ============ Workflow 相关类型 (Phase 4, 对齐后端 t_wf_001/t_wf_002 嵌套 API) ============

export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived'
export type WorkflowType = 'auto' | 'manual'
// manual=手动 / scheduled=单次定时 / event=事件 / cron=周期 Cron
export type TriggerType = 'manual' | 'scheduled' | 'event' | 'cron'
export type ActionType =
  | 'conversation'
  | 'message'
  | 'tag'
  | 'status_change'
  | 'notification'
  | 'custom'
export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'
  | 'timeout'
export type ConditionLogic = 'and' | 'or'
export type ConditionOperator =
  | 'eq'
  | 'neq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'in'
  | 'not_in'
  | 'contains'
  | 'regex'

// 触发器 (spec 为类型相关配置: cron/scheduled/event 各自必填键)
export interface WorkflowTrigger {
  id: string
  workflow_id: string
  name?: string
  trigger_type: TriggerType
  spec: Record<string, unknown>
  enabled: boolean
  created_at?: string
  updated_at?: string
}

// 条件 (嵌套于触发器下；detail 树中携带所属条件下的动作)
export interface WorkflowCondition {
  id: string
  trigger_id?: string
  name?: string
  expression: Record<string, unknown>
  logic: ConditionLogic
  priority: number
  /** 仅 detail 树：该条件下的动作 */
  actions?: WorkflowAction[]
  created_at?: string
  updated_at?: string
}

// 动作 (嵌套于条件下)
export interface WorkflowAction {
  id: string
  condition_id?: string
  name?: string
  action_type: ActionType
  params: Record<string, unknown>
  priority: number
  created_at?: string
  updated_at?: string
}

// 嵌套详情树 (GET /workflows/:id/detail, 对齐后端 WorkflowDetailResponse)
export interface WorkflowDetailTree {
  id?: string
  name: string
  description?: string
  workflow_type?: WorkflowType
  status?: WorkflowStatus
  config?: Record<string, unknown>
  execution_policy?: Record<string, unknown>
  version?: number
  created_at?: string
  updated_at?: string
  triggers: Array<
    WorkflowTrigger & {
      conditions: Array<WorkflowCondition & { actions: WorkflowAction[] }>
    }
  >
}

// 工作流主实体
export interface Workflow {
  id: string
  name: string
  description?: string
  workflow_type: WorkflowType
  status: WorkflowStatus
  config?: Record<string, unknown>
  execution_policy?: Record<string, unknown>
  version?: number
  created_at?: string
  updated_at?: string
}

export interface WorkflowListParams {
  page?: number
  page_size?: number
  status?: WorkflowStatus
  workflow_type?: WorkflowType
  search?: string
}

export interface WorkflowListResponse {
  items: Workflow[]
  total: number
  page: number
  page_size: number
}

export interface CreateWorkflowRequest {
  name: string
  description?: string
  workflow_type?: WorkflowType
  status?: WorkflowStatus
  config?: Record<string, unknown>
  execution_policy?: Record<string, unknown>
}

export interface UpdateWorkflowRequest {
  name?: string
  description?: string
  workflow_type?: WorkflowType
  status?: WorkflowStatus
  config?: Record<string, unknown>
  execution_policy?: Record<string, unknown>
}

// 触发器 / 条件 / 动作 请求体 (嵌套 API, 见 docs/WORKFLOW-CONFIG-API.md)
export interface CreateTriggerRequest {
  name?: string
  trigger_type: TriggerType
  spec: Record<string, unknown>
  enabled?: boolean
}

export interface UpdateTriggerRequest {
  name?: string
  trigger_type?: TriggerType
  spec?: Record<string, unknown>
  enabled?: boolean
}

export interface CreateConditionRequest {
  name?: string
  expression: Record<string, unknown>
  logic?: ConditionLogic
  priority?: number
}

export interface UpdateConditionRequest {
  name?: string
  expression?: Record<string, unknown>
  logic?: ConditionLogic
  priority?: number
}

export interface CreateActionRequest {
  name?: string
  action_type?: ActionType
  params?: Record<string, unknown>
  priority?: number
}

export interface UpdateActionRequest {
  name?: string
  action_type?: ActionType
  params?: Record<string, unknown>
  priority?: number
}

// 嵌套列表响应 (后端 TriggerListResponse / ConditionListResponse / ActionListResponse)
export interface TriggerListResponse {
  items: WorkflowTrigger[]
  total: number
}

export interface ConditionListResponse {
  items: WorkflowCondition[]
  total: number
}

export interface ActionListResponse {
  items: WorkflowAction[]
  total: number
}

// 执行日志 (对齐后端 ExecutionLogResponse)
export interface ExecutionLog {
  id: string
  execution_type: string
  trigger_type: string
  status: ExecutionStatus
  workflow_id?: string
  input_params?: Record<string, unknown>
  output_result?: Record<string, unknown>
  error_message?: string
  error_code?: string
  retry_count?: number
  started_at?: string
  finished_at?: string
  duration_ms?: number
  metadata?: Record<string, unknown>
  created_at?: string
}

export interface ExecutionLogListResponse {
  items: ExecutionLog[]
  total: number
  page: number
  page_size: number
}

// ===== P1-002: Prompt 模板管理系统 类型 =====
// 对齐 PRD 数据模型；后端若字段不一致，仅需调整 api 层。

export type PromptTemplateStatus = 'active' | 'archived'

/** 变量值映射（渲染输入）：变量名 → 值 */
export type PromptVariableValues = Record<string, string>

export interface VariableDef {
  name: string
  description: string
  defaultValue?: string
  required: boolean
}

export interface PromptTemplate {
  id: string
  name: string
  category: string
  tags: string[]
  content: string
  variables: VariableDef[]
  status: PromptTemplateStatus
  created_at: string
  updated_at: string
  created_by: string
}

// 版本历史条目
export interface PromptTemplateVersion {
  version: number
  content: string
  variables: VariableDef[]
  changed_at: string
  changed_by: string
  change_note?: string
}

// 模板更新请求体（生成新版本）
export interface UpdatePromptRequest {
  name?: string
  category?: string
  content?: string
  variables?: VariableDef[]
  tags?: string[]
  change_note?: string
}

// 模板创建请求体
export interface CreatePromptRequest {
  name: string
  category: string
  content: string
  variables?: VariableDef[]
  tags?: string[]
}

// Prompt 编辑表单统一提交载荷（PUT /prompt-templates/{id}，对齐后端 PromptTemplateUpdate）
export interface PromptFormEditPayload {
  name: string
  content: string
  template_type: PromptTemplateType
  /** 分类标识；null = 未分类 */
  category: string | null
  description: string | null
  /** 内容中出现的 {{variable}} 占位符名（自动提取） */
  variables: string[]
  /** 变量定义（必填/默认值/说明，P1-002 G 表单扩展） */
  variable_defs: VariableDef[]
  /** 标签（P1 功能） */
  tags: string[]
  /** 变更说明（后端暂未持久化，预留） */
  change_note?: string
}

// 版本对比
export type DiffType = 'added' | 'removed' | 'modified' | 'unchanged'

export interface DiffLine {
  type: DiffType
  oldLine?: number
  newLine?: number
  oldContent?: string
  newContent?: string
}

// ===== P1-002 列表页（Prompt 模板管理）API 类型 =====
// 字段名对齐后端 app/schemas/prompt_template.py 的 PromptTemplateResponse（snake_case）。
// 说明：与上方 PRD 数据模型（PromptTemplate，camel/下划线混合）并存；
// 列表页与 promptTemplate.ts 客户端使用本组类型，版本历史 demo 继续使用上方类型。

export type PromptTemplateType = 'system' | 'conversation' | 'greeting' | 'custom'

export type PromptCategory =
  | 'family_story'
  | 'ancestor_eval'
  | 'relation_query'
  | 'holiday_greeting'
  | 'custom'
  | (string & {})

export interface PromptTemplateListItem {
  id: string
  name: string
  description?: string
  content: string
  template_type: PromptTemplateType
  category?: string
  /** 模板中 {{variable}} 变量名列表（后端自动提取） */
  variables?: string[]
  version: number
  is_baseline?: boolean
  created_at: string
  updated_at: string
}

export interface PromptTemplateListParams {
  page?: number
  page_size?: number
  template_type?: string
  category?: string
  /** 客户端侧状态筛选（启用/归档），后端列表接口暂不支持，前端过滤 */
  status?: 'active' | 'archived'
  /** 客户端侧关键字搜索，后端列表接口暂不支持，前端过滤 */
  search?: string
}

export interface PromptTemplateListResponse {
  items: PromptTemplateListItem[]
  total: number
  page: number
  page_size: number
}

export interface CreatePromptTemplateRequest {
  name: string
  description?: string
  content: string
  template_type: PromptTemplateType
  category?: string
  variables?: string[]
  is_baseline?: boolean
}
