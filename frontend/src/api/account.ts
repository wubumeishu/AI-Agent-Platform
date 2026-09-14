import { api } from './client'
import type {
  Account,
  CreateAccountRequest,
  UpdateAccountRequest,
  PaginatedResponse,
} from './types'

export const accountApi = {
  // 列出账号
  list(params?: { platform?: string; status?: string }): Promise<PaginatedResponse<Account>> {
    return api.get<PaginatedResponse<Account>>('/accounts', { params })
  },

  // 创建账号
  create(data: CreateAccountRequest): Promise<Account> {
    return api.post<Account>('/accounts', data)
  },

  // 获取详情
  detail(id: string): Promise<Account> {
    return api.get<Account>(`/accounts/${id}`)
  },

  // 更新账号
  update(id: string, data: UpdateAccountRequest): Promise<Account> {
    return api.put<Account>(`/accounts/${id}`, data)
  },

  // 删除账号
  delete(id: string): Promise<void> {
    return api.delete<void>(`/accounts/${id}`)
  },

  // 测试连接
  testConnection(id: string): Promise<{ connected: boolean }> {
    return api.post<{ connected: boolean }>(`/accounts/${id}/test-conn`)
  },
}
