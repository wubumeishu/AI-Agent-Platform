import { api } from './client'
import type {
  PromptTemplateListItem,
  PromptTemplateListParams,
  PromptTemplateListResponse,
  CreatePromptTemplateRequest,
  VariableDef,
} from './types'

/** PUT /prompt-templates/{id} 的请求体（对齐后端 PromptTemplateUpdate，附加字段为前端预留） */
export interface UpdatePromptTemplateRequest {
  name?: string
  description?: string | null
  content?: string
  template_type?: string
  category?: string | null
  /** 内容中自动提取的 {{variable}} 占位符名 */
  variables?: string[]
  is_baseline?: boolean
  /** 标签（后端暂未持久化，pydantic 忽略未知字段，预留 P1） */
  tags?: string[]
  /** 变量定义（说明/默认值/必填；后端暂未持久化，预留 P1） */
  variable_defs?: VariableDef[]
}

/**
 * Prompt 模板列表页 API 客户端（P1-002-F）
 *
 * 端点对齐后端 app/routers/prompt_templates.py（前缀 /api/v1/prompt-templates）：
 * - GET    /prompt-templates/                       列表（分页 / 按类型 / 按分类）
 * - POST   /prompt-templates/                       创建（基线或新版本）
 * - DELETE /prompt-templates/{id}                   软删除
 * - POST   /prompt-templates/{id}/render            渲染（传入变量值）
 * - GET    /prompt-templates/{id}/variables         提取变量定义
 *
 * 说明：
 * - 「状态筛选 / 关键字搜索」后端列表接口暂不支持（仅 template_type / category），
 *   列表页在前端按返回的 items 二次过滤，见 usePromptTemplateStore。
 * - 与 api/prompt.ts（PRD §4.2 版本管理端点 /prompts/:id/versions 约定）并存：
 *   prompt.ts 服务版本历史 demo；本文件服务列表页，二者不互相覆盖。
 */
export const promptTemplateApi = {
  /** 获取模板列表（分页 + 类型/分类筛选） */
  list(params?: PromptTemplateListParams): Promise<PromptTemplateListResponse> {
    const query: Record<string, unknown> = {}
    if (params?.page) query.page = params.page
    if (params?.page_size) query.page_size = params.page_size
    if (params?.template_type) query.template_type = params.template_type
    if (params?.category) query.category = params.category
    return api.get<PromptTemplateListResponse>('/prompt-templates/', { params: query })
  },

  /** 创建模板（默认创建基线版本） */
  create(data: CreatePromptTemplateRequest): Promise<PromptTemplateListItem> {
    return api.post<PromptTemplateListItem>('/prompt-templates/', data)
  },

  /** 更新模板（生成新版本，POST/PUT /prompt-templates/{id}） */
  update(id: string, data: UpdatePromptTemplateRequest): Promise<PromptTemplateListItem> {
    return api.put<PromptTemplateListItem>(`/prompt-templates/${id}`, data)
  },

  /** 软删除模板 */
  remove(id: string): Promise<void> {
    return api.delete<void>(`/prompt-templates/${id}`)
  },

  /** 渲染模板：传入变量值，返回替换后的最终文本 */
  render(id: string, variables: Record<string, string>): Promise<{ content: string }> {
    return api.post<{ content: string }>(`/prompt-templates/${id}/render`, variables)
  },

  /** 提取模板中的变量定义（名称 / 说明 / 默认值） */
  variables(id: string): Promise<{
    template_id: string
    template_name: string
    variables: Array<{ name: string; description?: string; default?: string }>
  }> {
    return api.get(`/prompt-templates/${id}/variables`)
  },
}
