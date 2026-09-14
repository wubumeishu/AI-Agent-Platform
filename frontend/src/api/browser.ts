import { api } from './client'
import type { BrowserProfile, BrowserProviderStatus, PaginatedResponse } from './types'

export const browserApi = {
  // 列出 Provider（V1 仅 BitBrowser）
  listProviders(): Promise<string[]> {
    return api.get<string[]>('/browsers/providers')
  },

  // 获取 BitBrowser 连接状态
  getBitBrowserStatus(): Promise<BrowserProviderStatus> {
    return api.get<BrowserProviderStatus>('/browsers/providers/bitbrowser/status')
  },

  // 测试 BitBrowser 连接
  testBitBrowserConnection(): Promise<{ connected: boolean }> {
    return api.post<{ connected: boolean }>('/browsers/providers/bitbrowser/test')
  },

  // 获取 Profile 列表
  listProfiles(): Promise<PaginatedResponse<BrowserProfile>> {
    return api.get<PaginatedResponse<BrowserProfile>>('/browsers/profiles')
  },

  // 创建 Profile
  createProfile(data: { name: string; provider: string }): Promise<BrowserProfile> {
    return api.post<BrowserProfile>('/browsers/profiles', data)
  },

  // 更新 Profile
  updateProfile(id: string, data: Partial<BrowserProfile>): Promise<BrowserProfile> {
    return api.put<BrowserProfile>(`/browsers/profiles/${id}`, data)
  },

  // 删除 Profile
  deleteProfile(id: string): Promise<void> {
    return api.delete<void>(`/browsers/profiles/${id}`)
  },
}
