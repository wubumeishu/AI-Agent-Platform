import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { promptTemplateApi } from '@/api/promptTemplate'
import type {
  PromptTemplateListItem,
  PromptTemplateListParams,
  PromptTemplateListResponse,
  CreatePromptTemplateRequest,
  PromptTemplateType,
  PromptCategory,
} from '@/api/types'
import type { UpdatePromptTemplateRequest } from '@/api/promptTemplate'

/** 模板类型选项（中文标签） */
export const PROMPT_TEMPLATE_TYPES: Array<{ value: PromptTemplateType; label: string }> = [
  { value: 'system', label: '系统提示词' },
  { value: 'conversation', label: '对话流程' },
  { value: 'greeting', label: '开场白' },
  { value: 'custom', label: '自定义' },
]

/** 预置分类（PRD §10.2 家族场景预置 + 自定义） */
export const PROMPT_CATEGORIES: Array<{ value: PromptCategory; label: string }> = [
  { value: 'family_story', label: '家族故事生成' },
  { value: 'ancestor_eval', label: '祖先评价' },
  { value: 'relation_query', label: '关系查询' },
  { value: 'holiday_greeting', label: '节日问候' },
  { value: 'custom', label: '自定义' },
]

export const TEMPLATE_TYPE_LABELS: Record<PromptTemplateType, string> = {
  system: '系统提示词',
  conversation: '对话流程',
  greeting: '开场白',
  custom: '自定义',
}

export const CATEGORY_LABELS: Record<string, string> = {
  family_story: '家族故事',
  ancestor_eval: '祖先评价',
  relation_query: '关系查询',
  holiday_greeting: '节日问候',
  custom: '自定义',
}

export const usePromptTemplateStore = defineStore('promptTemplate', () => {
  // ---- State ----
  const templates = ref<PromptTemplateListItem[]>([])
  const total = ref(0)
  const page = ref(1)
  const pageSize = ref(12)
  const loading = ref(false)
  const apiReady = ref(false)

  // 前端过滤项（后端列表接口暂不支持）
  const filterType = ref<'' | PromptTemplateType>('')
  const filterCategory = ref<'' | PromptCategory>('')
  const filterStatus = ref<'' | 'active' | 'archived'>('')
  const search = ref('')

  // 当前页客户端过滤后的视图（状态/关键字过滤）
  const visibleTemplates = computed(() => {
    let list = templates.value
    const kw = search.value.trim().toLowerCase()
    if (kw) {
      list = list.filter((t) => {
        const hay = [t.name, t.description ?? '', t.content, t.category ?? '']
          .join(' ')
          .toLowerCase()
        return hay.includes(kw)
      })
    }
    if (filterStatus.value) {
      list = list.filter((t) =>
        filterStatus.value === 'archived' ? t.is_baseline === false : t.is_baseline === true,
      )
    }
    return list
  })

  // ---- Actions ----
  async function fetchTemplates(params?: PromptTemplateListParams): Promise<PromptTemplateListResponse> {
    loading.value = true
    apiReady.value = false
    try {
      const merged: PromptTemplateListParams = {
        page: params?.page ?? page.value,
        page_size: params?.page_size ?? pageSize.value,
        template_type: params?.template_type ?? (filterType.value || undefined),
        category: params?.category ?? (filterCategory.value || undefined),
      }
      const data = await promptTemplateApi.list(merged)
      templates.value = data.items
      total.value = data.total
      page.value = data.page
      pageSize.value = data.page_size
      apiReady.value = true
      return data
    } catch (error) {
      // 后端未就绪：清空并抛出，由调用方决定占位
      templates.value = []
      total.value = 0
      throw error
    } finally {
      loading.value = false
    }
  }

  async function createTemplate(data: CreatePromptTemplateRequest): Promise<PromptTemplateListItem> {
    const created = await promptTemplateApi.create(data)
    await fetchTemplates()
    return created
  }

  async function updateTemplate(
    id: string,
    data: UpdatePromptTemplateRequest,
  ): Promise<PromptTemplateListItem> {
    const updated = await promptTemplateApi.update(id, data)
    await fetchTemplates()
    return updated
  }

  async function deleteTemplate(id: string): Promise<void> {
    await promptTemplateApi.remove(id)
    await fetchTemplates()
  }

  function setTypeFilter(value: '' | PromptTemplateType) {
    filterType.value = value
    fetchTemplates()
  }

  function setCategoryFilter(value: '' | PromptCategory) {
    filterCategory.value = value
    fetchTemplates()
  }

  function setStatusFilter(value: '' | 'active' | 'archived') {
    filterStatus.value = value
  }

  function setSearchKeyword(value: string) {
    search.value = value
  }

  function setPage(next: number) {
    if (next < 1) return
    page.value = next
    fetchTemplates()
  }

  function hasActiveFilters(): boolean {
    return (
      search.value.trim() !== '' ||
      filterType.value !== '' ||
      filterCategory.value !== '' ||
      filterStatus.value !== ''
    )
  }

  function resetFilters() {
    filterType.value = ''
    filterCategory.value = ''
    filterStatus.value = ''
    search.value = ''
    page.value = 1
    fetchTemplates()
  }

  return {
    templates,
    total,
    page,
    pageSize,
    loading,
    apiReady,
    visibleTemplates,
    filterType,
    filterCategory,
    filterStatus,
    search,
    fetchTemplates,
    createTemplate,
    updateTemplate,
    deleteTemplate,
    setTypeFilter,
    setCategoryFilter,
    setStatusFilter,
    setSearchKeyword,
    setPage,
    hasActiveFilters,
    resetFilters,
  }
})
