import { api } from './client'
import type {
  Content,
  CreateContentRequest,
  UpdateContentRequest,
} from './private_domain'
import type { PaginatedResponse } from './client'

export const contentApi = {
  // 列出内容
  list(params?: { page?: number; page_size?: number; type?: string; status?: string }): Promise<PaginatedResponse<Content>> {
    return api.get('/private-domain/content', { params })
  },

  // 创建内容
  create(data: CreateContentRequest): Promise<Content> {
    return api.post('/private-domain/content', data)
  },

  // 获取详情
  detail(id: string): Promise<Content> {
    return api.get(`/private-domain/content/${id}`)
  },

  // 更新内容
  update(id: string, data: UpdateContentRequest): Promise<Content> {
    return api.put(`/private-domain/content/${id}`, data)
  },

  // 删除内容
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/content/${id}`)
  },

  // 发布内容
  publish(id: string): Promise<{ status: string }> {
    return api.post(`/private-domain/content/${id}/publish`)
  },
}
