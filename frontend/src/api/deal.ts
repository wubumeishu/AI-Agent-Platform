import { api } from './client'
import type {
  DealPipeline,
  DealStage,
  DealItem,
  DealTransition,
  DealPipelineStats,
  AccountPipelineStats,
  CreatePipelineRequest,
  UpdatePipelineRequest,
  CreateDealRequest,
  UpdateDealRequest,
  PaginatedResponse,
} from './private_domain'

export const pipelineApi = {
  // 列出商机漏斗
  list(params?: {
    account_id: string
    pipeline_type?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<DealPipeline>> {
    return api.get('/private-domain/pipelines', { params })
  },

  // 创建商机漏斗
  create(data: CreatePipelineRequest): Promise<DealPipeline> {
    return api.post('/private-domain/pipelines', data)
  },

  // 获取详情
  detail(id: string, account_id: string): Promise<DealPipeline> {
    return api.get(`/private-domain/pipelines/${id}`, { params: { account_id } })
  },

  // 更新商机漏斗
  update(id: string, data: UpdatePipelineRequest): Promise<DealPipeline> {
    return api.put(`/private-domain/pipelines/${id}`, data)
  },

  // 删除商机漏斗
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/pipelines/${id}`)
  },

  // 获取阶段列表
  listStages(pipeline_id: string): Promise<DealStage[]> {
    return api.get(`/private-domain/pipelines/${pipeline_id}/stages`)
  },

  // 创建阶段
  createStage(pipeline_id: string, data: { name: string; order?: number; probability?: number }): Promise<DealStage> {
    return api.post(`/private-domain/pipelines/${pipeline_id}/stages`, data)
  },

  // 更新阶段
  updateStage(stage_id: string, data: { name?: string; order?: number; probability?: number; status?: string }): Promise<DealStage> {
    return api.put(`/private-domain/stages/${stage_id}`, data)
  },

  // 删除阶段
  deleteStage(stage_id: string): Promise<void> {
    return api.delete(`/private-domain/stages/${stage_id}`)
  },

  // 获取统计
  stats(pipeline_id: string): Promise<DealPipelineStats> {
    return api.get(`/private-domain/pipelines/${pipeline_id}/stats`)
  },

  // 获取账户统计
  accountStats(account_id: string): Promise<AccountPipelineStats[]> {
    return api.get('/private-domain/account-stats', { params: { account_id } })
  },
}

export const dealApi = {
  // 列出商机
  list(params?: {
    account_id: string
    pipeline_id?: string
    stage_id?: string
    status?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<DealItem>> {
    return api.get('/private-domain/deals', { params })
  },

  // 创建商机
  create(data: CreateDealRequest): Promise<DealItem> {
    return api.post('/private-domain/deals', data)
  },

  // 获取详情
  detail(id: string, account_id: string): Promise<DealItem> {
    return api.get(`/private-domain/deals/${id}`, { params: { account_id } })
  },

  // 更新商机
  update(id: string, data: UpdateDealRequest): Promise<DealItem> {
    return api.put(`/private-domain/deals/${id}`, data)
  },

  // 删除商机
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/deals/${id}`)
  },

  // 流转阶段
  transition(id: string, data: DealTransition): Promise<DealItem> {
    return api.post(`/private-domain/deals/${id}/transition`, data)
  },
}
