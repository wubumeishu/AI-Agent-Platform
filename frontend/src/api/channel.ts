import { api } from './client'
import type {
  Channel,
  ChannelListParams,
  CreateChannelRequest,
  UpdateChannelRequest,
} from './private_domain'
import type { PaginatedResponse } from './client'

export const channelApi = {
  // 列出渠道
  list(params?: ChannelListParams): Promise<PaginatedResponse<Channel>> {
    return api.get('/private-domain/channels', { params })
  },

  // 创建渠道
  create(data: CreateChannelRequest): Promise<Channel> {
    return api.post('/private-domain/channels', data)
  },

  // 获取详情
  detail(id: string): Promise<Channel> {
    return api.get(`/private-domain/channels/${id}`)
  },

  // 更新渠道
  update(id: string, data: UpdateChannelRequest): Promise<Channel> {
    return api.put(`/private-domain/channels/${id}`, data)
  },

  // 删除渠道
  delete(id: string): Promise<void> {
    return api.delete(`/private-domain/channels/${id}`)
  },
}
