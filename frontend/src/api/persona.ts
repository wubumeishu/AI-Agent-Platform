import { api } from './client'
import type {
  Persona,
  CreatePersonaRequest,
  UpdatePersonaRequest,
  PaginatedResponse,
} from './types'

export const personaApi = {
  // 列出 Persona
  list(): Promise<PaginatedResponse<Persona>> {
    return api.get<PaginatedResponse<Persona>>('/personas')
  },

  // 创建 Persona
  create(data: CreatePersonaRequest): Promise<Persona> {
    return api.post<Persona>('/personas', data)
  },

  // 获取详情
  detail(id: string): Promise<Persona> {
    return api.get<Persona>(`/personas/${id}`)
  },

  // 更新 Persona
  update(id: string, data: UpdatePersonaRequest): Promise<Persona> {
    return api.put<Persona>(`/personas/${id}`, data)
  },

  // 删除 Persona
  delete(id: string): Promise<void> {
    return api.delete<void>(`/personas/${id}`)
  },

  // 获取版本历史
  versions(id: string): Promise<Persona[]> {
    return api.get<Persona[]>(`/personas/${id}/versions`)
  },

  // 克隆为新版
  clone(id: string): Promise<Persona> {
    return api.post<Persona>(`/personas/${id}/clone`)
  },
}
