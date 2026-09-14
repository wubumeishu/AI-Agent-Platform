import { api } from './client'
import type {
  WorkflowAction,
  CreateActionRequest,
  UpdateActionRequest,
  ActionListResponse,
} from './types'

/**
 * 动作 API（嵌套于 Workflow > Trigger > Condition，对齐后端 t_wf_002 嵌套路由）。
 *
 * 路径：/workflows/{wid}/triggers/{tid}/conditions/{cid}/actions
 * 动作没有独立顶层端点，必须经由其所属的条件访问。
 */
export const actionApi = {
  list(
    workflowId: string,
    triggerId: string,
    conditionId: string
  ): Promise<ActionListResponse> {
    return api.get<ActionListResponse>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions`
    )
  },

  create(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    data: CreateActionRequest
  ): Promise<WorkflowAction> {
    return api.post<WorkflowAction>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions`,
      data
    )
  },

  update(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    actionId: string,
    data: UpdateActionRequest
  ): Promise<WorkflowAction> {
    return api.put<WorkflowAction>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions/${actionId}`,
      data
    )
  },

  delete(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    actionId: string
  ): Promise<void> {
    return api.delete<void>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions/${actionId}`
    )
  },
}
