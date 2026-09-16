import { api } from './client'
import type {
  Platform,
  CreatePlatformRequest,
  PaginatedResponse,
} from './types'

export const platformApi = {
  // 列出平台
  list(): Promise<PaginatedResponse<Platform>> {
    return api.get<PaginatedResponse<Platform>>('/platforms')
  },

  // 创建平台
  create(data: CreatePlatformRequest): Promise<Platform> {
    return api.post<Platform>('/platforms', data)
  },

  // 获取详情
  detail(id: string): Promise<Platform> {
    return api.get<Platform>(`/platforms/${id}`)
  },

  // 更新平台
  update(id: string, data: Partial<CreatePlatformRequest>): Promise<Platform> {
    return api.put<Platform>(`/platforms/${id}`, data)
  },

  // 注销平台
  delete(id: string): Promise<void> {
    return api.delete<void>(`/platforms/${id}`)
  },

  // 测试平台连接
  testConnection(id: string): Promise<{ connected: boolean }> {
    return api.post<{ connected: boolean }>(`/platforms/${id}/test`)
  },
}
