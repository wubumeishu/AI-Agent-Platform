import { api } from './client'
import type {
  Tag,
  TagListParams,
  CreateTagRequest,
  UpdateTagRequest,
  PaginatedResponse,
} from './types'

export const tagApi = {
  // 列出标签
  list(params?: TagListParams): Promise<PaginatedResponse<Tag>> {
    return api.get<PaginatedResponse<Tag>>('/crm/tags', { params })
  },

  // 创建标签
  create(data: CreateTagRequest): Promise<Tag> {
    return api.post<Tag>('/crm/tags', data)
  },

  // 获取详情
  detail(id: string): Promise<Tag> {
    return api.get<Tag>(`/crm/tags/${id}`)
  },

  // 更新标签
  update(id: string, data: UpdateTagRequest): Promise<Tag> {
    return api.put<Tag>(`/crm/tags/${id}`, data)
  },

  // 删除标签
  delete(id: string): Promise<void> {
    return api.delete<void>(`/crm/tags/${id}`)
  },

  // 获取所有标签（不分页，用于下拉选择）
  all(): Promise<Tag[]> {
    return api.get<Tag[]>('/crm/tags/all')
  },
}
