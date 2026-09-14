import { api } from './client'
import type {
  Segment,
  CreateSegmentRequest,
  UpdateSegmentRequest,
  SegmentStats,
  SegmentMember,
  PaginatedResponse,
} from './private_domain'

export const segmentApi = {
  // 列出客户群
  list(params?: {
    account_id: string
    segment_type?: string
    page?: number
    page_size?: number
  }): Promise<PaginatedResponse<Segment>> {
    return api.get('/private-domain/segments', { params })
  },

  // 创建客户群
  create(data: CreateSegmentRequest): Promise<Segment> {
    return api.post('/private-domain/segments', data)
  },

  // 获取详情
  detail(id: string, account_id: string): Promise<Segment> {
    return api.get(`/private-domain/segments/${id}`, { params: { account_id } })
  },

  // 更新客户群
  update(id: string, data: UpdateSegmentRequest): Promise<Segment> {
    return api.put(`/private-domain/segments/${id}`, data)
  },

  // 删除客户群
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/segments/${id}`)
  },

  // 获取成员列表
  listMembers(id: string, params?: { page?: number; page_size?: number }): Promise<PaginatedResponse<SegmentMember>> {
    return api.get(`/private-domain/segments/${id}/members`, { params })
  },

  // 添加成员
  addMember(id: string, customer_id: string, added_by?: string): Promise<{ success: boolean }> {
    return api.post(`/private-domain/segments/${id}/members`, null, { params: { customer_id, added_by } })
  },

  // 移除成员
  removeMember(id: string, customer_id: string): Promise<{ success: boolean }> {
    return api.delete(`/private-domain/segments/${id}/members/${customer_id}`)
  },

  // 批量添加成员
  bulkAddMembers(id: string, customer_ids: string[], added_by?: string): Promise<{ success: boolean }> {
    return api.post(`/private-domain/segments/${id}/members/bulk`, null, { params: { customer_ids: customer_ids.join(','), added_by } })
  },

  // 同步成员
  sync(id: string): Promise<{ success: boolean; synced_count?: number }> {
    return api.post(`/private-domain/segments/${id}/sync`)
  },

  // 获取统计
  stats(id: string, account_id: string): Promise<SegmentStats> {
    return api.get(`/private-domain/segments/${id}/stats`, { params: { account_id } })
  },
}
