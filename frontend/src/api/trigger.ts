import { api } from './client'
import type {
  WorkflowTrigger,
  WorkflowCondition,
  WorkflowAction,
  WorkflowDetailTree,
  CreateTriggerRequest,
  UpdateTriggerRequest,
  CreateConditionRequest,
  UpdateConditionRequest,
  CreateActionRequest,
  UpdateActionRequest,
  TriggerListResponse,
  ConditionListResponse,
  ActionListResponse,
  ExecutionLogListResponse,
} from './types'

/**
 * 触发器 API（嵌套于 Workflow，对齐后端 t_wf_002 嵌套路由 docs/WORKFLOW-CONFIG-API.md）。
 *
 * 层级：/workflows/{wid}/triggers/{tid}[/conditions/{cid}[/actions/{aid}]]
 * 启用/禁用通过 PUT 触发器（{ enabled }）实现。
 */
export const triggerApi = {
  // ---------- 嵌套详情树（一次拉取 triggers -> conditions -> actions） ----------
  detailTree(workflowId: string): Promise<WorkflowDetailTree> {
    return api.get<WorkflowDetailTree>(`/workflows/${workflowId}/detail`)
  },

  // ---------- 触发器（嵌套于 workflow） ----------
  list(workflowId: string): Promise<TriggerListResponse> {
    return api.get<TriggerListResponse>(`/workflows/${workflowId}/triggers`)
  },

  create(workflowId: string, data: CreateTriggerRequest): Promise<WorkflowTrigger> {
    return api.post<WorkflowTrigger>(`/workflows/${workflowId}/triggers`, data)
  },

  update(
    workflowId: string,
    triggerId: string,
    data: UpdateTriggerRequest
  ): Promise<WorkflowTrigger> {
    return api.put<WorkflowTrigger>(
      `/workflows/${workflowId}/triggers/${triggerId}`,
      data
    )
  },

  delete(workflowId: string, triggerId: string): Promise<void> {
    return api.delete<void>(`/workflows/${workflowId}/triggers/${triggerId}`)
  },

  /** 启用 / 禁用触发器（嵌套 API 无专用开关端点，经 PUT 局部更新） */
  setEnabled(workflowId: string, triggerId: string, enabled: boolean): Promise<WorkflowTrigger> {
    return api.put<WorkflowTrigger>(
      `/workflows/${workflowId}/triggers/${triggerId}`,
      { enabled }
    )
  },

  // ---------- 条件（嵌套于触发器） ----------
  listConditions(workflowId: string, triggerId: string): Promise<ConditionListResponse> {
    return api.get<ConditionListResponse>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions`
    )
  },

  createCondition(
    workflowId: string,
    triggerId: string,
    data: CreateConditionRequest
  ): Promise<WorkflowCondition> {
    return api.post<WorkflowCondition>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions`,
      data
    )
  },

  updateCondition(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    data: UpdateConditionRequest
  ): Promise<WorkflowCondition> {
    return api.put<WorkflowCondition>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}`,
      data
    )
  },

  deleteCondition(workflowId: string, triggerId: string, conditionId: string): Promise<void> {
    return api.delete<void>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}`
    )
  },

  // ---------- 动作（嵌套于条件） ----------
  listActions(
    workflowId: string,
    triggerId: string,
    conditionId: string
  ): Promise<ActionListResponse> {
    return api.get<ActionListResponse>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions`
    )
  },

  createAction(
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

  updateAction(
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

  deleteAction(
    workflowId: string,
    triggerId: string,
    conditionId: string,
    actionId: string
  ): Promise<void> {
    return api.delete<void>(
      `/workflows/${workflowId}/triggers/${triggerId}/conditions/${conditionId}/actions/${actionId}`
    )
  },

  // ---------- 执行历史（按 workflow 过滤） ----------
  executionLogs(
    workflowId: string,
    params?: { page?: number; page_size?: number; status?: string }
  ): Promise<ExecutionLogListResponse> {
    return api.get<ExecutionLogListResponse>('/execution-logs', {
      params: { workflow_id: workflowId, ...params },
    })
  },
}
