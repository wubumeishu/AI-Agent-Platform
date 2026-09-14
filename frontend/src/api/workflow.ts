import { api } from './client'
import type {
  Workflow,
  WorkflowDetailTree,
  WorkflowListParams,
  WorkflowListResponse,
  CreateWorkflowRequest,
  UpdateWorkflowRequest,
  ExecutionLogListResponse,
} from './types'

export const workflowApi = {
  // 列出 Workflows
  list(params?: WorkflowListParams): Promise<WorkflowListResponse> {
    return api.get<WorkflowListResponse>('/workflows', { params })
  },

  // 创建 Workflow
  create(data: CreateWorkflowRequest): Promise<Workflow> {
    return api.post<Workflow>('/workflows', data)
  },

  // 获取详情（扁平记录）
  detail(id: string): Promise<Workflow> {
    return api.get<Workflow>(`/workflows/${id}`)
  },

  // 获取嵌套详情树 (workflow -> triggers -> conditions -> actions)
  detailTree(id: string): Promise<WorkflowDetailTree> {
    return api.get<WorkflowDetailTree>(`/workflows/${id}/detail`)
  },

  // 更新 Workflow（局部更新，含状态切换 active/paused）
  update(id: string, data: UpdateWorkflowRequest): Promise<Workflow> {
    return api.put<Workflow>(`/workflows/${id}`, data)
  },

  // 删除 Workflow（级联软删子树）
  delete(id: string): Promise<void> {
    return api.delete<void>(`/workflows/${id}`)
  },

  // 启动 / 暂停（通过 status 更新实现）
  activate(id: string): Promise<Workflow> {
    return api.put<Workflow>(`/workflows/${id}`, { status: 'active' })
  },

  pause(id: string): Promise<Workflow> {
    return api.put<Workflow>(`/workflows/${id}`, { status: 'paused' })
  },

  // 执行历史（execution-logs，按 workflow 过滤）
  executionLogs(
    id: string,
    params?: { page?: number; page_size?: number; status?: string }
  ): Promise<ExecutionLogListResponse> {
    return api.get<ExecutionLogListResponse>('/execution-logs', {
      params: { workflow_id: id, ...params },
    })
  },
}
