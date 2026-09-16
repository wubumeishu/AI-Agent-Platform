import { api } from './client'
import type {
  Customer,
  CustomerIdentityRequest,
  CustomerListParams,
  CustomerListResponse,
  CreateCustomerRequest,
  UpdateCustomerRequest,
  CustomerIdentity,
  Lead,
} from './types'

export const customerApi = {
  // 列出客户（后端分页参数为 skip/limit）
  list(params?: CustomerListParams): Promise<CustomerListResponse> {
    return api.get<CustomerListResponse>('/crm/customers', { params })
  },

  // 创建客户
  create(data: CreateCustomerRequest): Promise<Customer> {
    return api.post<Customer>('/crm/customers', data)
  },

  // 获取详情（含完整 identities 与 tags）
  detail(id: string): Promise<Customer> {
    return api.get<Customer>(`/crm/customers/${id}`)
  },

  // 更新客户
  update(id: string, data: UpdateCustomerRequest): Promise<Customer> {
    return api.put<Customer>(`/crm/customers/${id}`, data)
  },

  // 删除客户（软删除，204）
  delete(id: string): Promise<void> {
    return api.delete<void>(`/crm/customers/${id}`)
  },

  // 添加平台身份
  addIdentity(customerId: string, data: CustomerIdentityRequest): Promise<CustomerIdentity> {
    return api.post<CustomerIdentity>(`/crm/customers/${customerId}/identities`, data)
  },

  // 该客户的所有 Lead（后端返回 {code,message,data} 信封，client 自动解包为数组）
  getLeads(customerId: string): Promise<Lead[]> {
    return api.get<Lead[]>(`/crm/leads/customer/${customerId}/leads`)
  },

  // 该客户的对话历史（Customer 360 API，含信封解包）
  getConversations(
    customerId: string,
    params?: { skip?: number; limit?: number },
  ): Promise<{ total: number; conversations: CustomerConversation[] }> {
    return api.get<{ total: number; conversations: CustomerConversation[] }>(
      `/customers/360/${customerId}/conversations`,
      { params },
    )
  },

  // 该客户的活动记录（Customer 360 API）
  getActivities(
    customerId: string,
    params?: { activity_type?: string; skip?: number; limit?: number },
  ): Promise<{ total: number; activities: CustomerActivity[]; skip: number; limit: number }> {
    return api.get<{ total: number; activities: CustomerActivity[]; skip: number; limit: number }>(
      `/customers/360/${customerId}/activities`,
      { params },
    )
  },
}

export interface CustomerActivity {
  id: string
  activity_type: string
  title: string
  description?: string | null
  related_lead_id?: string | null
  created_at?: string | null
}

export interface CustomerConversation {
  id: string
  channel?: string | null
  subject?: string | null
  status?: string | null
  summary?: string | null
  sentiment?: string | null
  tags?: string[]
  message_count?: number
  created_at?: string | null
  updated_at?: string | null
}
