import { api } from './client'
import type {
  Lead,
  LeadListParams,
  LeadListResponse,
  CreateLeadRequest,
  UpdateLeadRequest,
  LifecycleTransition,
  LifecycleStage,
} from './types'

export const leadApi = {
  // 列出 Leads
  list(params?: LeadListParams): Promise<LeadListResponse> {
    return api.get<LeadListResponse>('/crm/leads', { params })
  },

  // 创建 Lead
  create(data: CreateLeadRequest): Promise<Lead> {
    return api.post<Lead>('/crm/leads', data)
  },

  // 获取详情
  detail(id: string): Promise<Lead> {
    return api.get<Lead>(`/crm/leads/${id}`)
  },

  // 更新 Lead
  update(id: string, data: UpdateLeadRequest): Promise<Lead> {
    return api.put<Lead>(`/crm/leads/${id}`, data)
  },

  // 删除 Lead
  delete(id: string): Promise<void> {
    return api.delete<void>(`/crm/leads/${id}`)
  },

  // 阶段流转
  transitionStage(data: LifecycleTransition): Promise<{ stage: string; log_id: string }> {
    return api.post<{ stage: string; log_id: string }>('/crm/lifecycle/stages/transition', {
      lead_id: data.lead_id,
      new_stage_code: data.new_stage_code,
      reason: data.reason,
      operator: data.operator,
      metadata: data.metadata,
    })
  },

  // 获取生命周期阶段列表
  getLifecycleStages(): Promise<LifecycleStage[]> {
    return api.get<LifecycleStage[]>('/crm/lifecycle/stages')
  },

  // 获取客户的 Lead
  getCustomerLeads(customerId: string): Promise<Lead[]> {
    return api.get<Lead[]>(`/crm/leads/customer/${customerId}/leads`)
  },
}
