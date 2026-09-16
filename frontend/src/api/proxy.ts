import { api } from './client'
import type { Proxy, CreateProxyRequest, UpdateProxyRequest, PaginatedResponse } from './types'

export const proxyApi = {
  // 列出代理
  list(): Promise<PaginatedResponse<Proxy>> {
    return api.get<PaginatedResponse<Proxy>>('/proxies')
  },

  // 创建代理
  create(data: CreateProxyRequest): Promise<Proxy> {
    return api.post<Proxy>('/proxies', data)
  },

  // 获取详情
  detail(id: string): Promise<Proxy> {
    return api.get<Proxy>(`/proxies/${id}`)
  },

  // 更新代理
  update(id: string, data: UpdateProxyRequest): Promise<Proxy> {
    return api.put<Proxy>(`/proxies/${id}`, data)
  },

  // 删除代理
  delete(id: string): Promise<void> {
    return api.delete<void>(`/proxies/${id}`)
  },

  // 测试连通性
  testConnection(id: string): Promise<{ connected: boolean }> {
    return api.post<{ connected: boolean }>(`/proxies/${id}/test`)
  },
}
