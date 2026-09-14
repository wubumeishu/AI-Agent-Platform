import { api } from './client'
import type {
  Agent,
  AgentListParams,
  CreateAgentRequest,
  UpdateAgentRequest,
  PaginatedResponse,
} from './types'

export const agentApi = {
  // 列出 Agent
  list(params?: AgentListParams): Promise<PaginatedResponse<Agent>> {
    return api.get('/agents', { params })
  },

  // 创建 Agent
  create(data: CreateAgentRequest): Promise<Agent> {
    return api.post('/agents', data)
  },

  // 获取详情
  detail(id: string): Promise<Agent> {
    return api.get(`/agents/${id}`)
  },

  // 更新 Agent
  update(id: string, data: UpdateAgentRequest): Promise<Agent> {
    return api.put(`/agents/${id}`, data)
  },

  // 删除 Agent
  delete(id: string): Promise<void> {
    return api.delete(`/agents/${id}`)
  },

  // 启动 Agent
  start(id: string): Promise<{ status: string }> {
    return api.post(`/agents/${id}/start`)
  },

  // 停止 Agent
  stop(id: string): Promise<{ status: string }> {
    return api.post(`/agents/${id}/stop`)
  },

  // 获取状态
  getStatus(id: string): Promise<{ status: string }> {
    return api.get(`/agents/${id}/status`)
  },
}
