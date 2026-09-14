import { api } from './client'
import type {
  NurturePlan,
  CreateNurtureRequest,
  UpdateNurtureRequest,
} from './private_domain'
import type { PaginatedResponse } from './client'

export const nurtureApi = {
  // 列出培育计划
  list(params?: { page?: number; page_size?: number; status?: string; channel_id?: string }): Promise<PaginatedResponse<NurturePlan>> {
    return api.get('/private-domain/nurture-plans', { params })
  },

  // 创建培育计划
  create(data: CreateNurtureRequest): Promise<NurturePlan> {
    return api.post('/private-domain/nurture-plans', data)
  },

  // 获取详情
  detail(id: string): Promise<NurturePlan> {
    return api.get(`/private-domain/nurture-plans/${id}`)
  },

  // 更新培育计划
  update(id: string, data: UpdateNurtureRequest): Promise<NurturePlan> {
    return api.put(`/private-domain/nurture-plans/${id}`, data)
  },

  // 删除培育计划
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/nurture-plans/${id}`)
  },

  // 启动培育计划
  start(id: string): Promise<{ status: string }> {
    return api.post(`/private-domain/nurture-plans/${id}/transition?new_status=active`)
  },

  // 暂停培育计划
  pause(id: string): Promise<{ status: string }> {
    return api.post(`/private-domain/nurture-plans/${id}/transition?new_status=paused`)
  },

  // 完成培育计划
  complete(id: string): Promise<{ status: string }> {
    return api.post(`/private-domain/nurture-plans/${id}/transition?new_status=completed`)
  },

  // 归档培育计划
  archive(id: string): Promise<{ status: string }> {
    return api.post(`/private-domain/nurture-plans/${id}/transition?new_status=archived`)
  },
}
