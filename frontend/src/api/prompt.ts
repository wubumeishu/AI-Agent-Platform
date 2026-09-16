import { api } from './client'
import type {
  PromptTemplate,
  PromptTemplateVersion,
  UpdatePromptRequest,
} from './types'

/**
 * Prompt 模板管理 API 客户端（P1-002）
 * 端点约定对齐 PRD §4.2 版本管理部分：
 * - GET  /prompts/:id/versions            版本列表
 * - GET  /prompts/:id/versions/:version   版本详情
 * - POST /prompts/:id/versions/:version/rollback  回滚
 * 后端 t_p002_api_version 若端点不一致，仅需调整本文件。
 */
export const promptApi = {
  // 获取模板详情
  detail(id: string): Promise<PromptTemplate> {
    return api.get<PromptTemplate>(`/prompts/${id}`)
  },

  // 更新模板（生成新版本）
  update(id: string, data: UpdatePromptRequest): Promise<PromptTemplate> {
    return api.put<PromptTemplate>(`/prompts/${id}`, data)
  },

  // 版本列表（按时间倒序）
  versions(id: string): Promise<PromptTemplateVersion[]> {
    return api.get<PromptTemplateVersion[]>(`/prompts/${id}/versions`)
  },

  // 指定版本详情
  versionDetail(id: string, version: number): Promise<PromptTemplateVersion> {
    return api.get<PromptTemplateVersion>(`/prompts/${id}/versions/${version}`)
  },

  // 回滚到指定版本
  rollback(id: string, version: number): Promise<PromptTemplate> {
    return api.post<PromptTemplate>(`/prompts/${id}/versions/${version}/rollback`)
  },
}
