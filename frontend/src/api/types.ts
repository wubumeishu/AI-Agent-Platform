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
