<template>
  <div class="pt-page">
    <!-- Header -->
    <PageHeader title="Prompt 模板管理">
      <template #actions>
        <button
          class="pt-btn pt-btn--primary"
          :disabled="creating || (mockMode && !mockReady)"
          @click="showCreateDialog = true"
        >
          + 新建模板
        </button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="pt-filters">
      <div class="pt-filters__left">
        <div class="pt-search">
          <span class="pt-search__icon">🔍</span>
          <input
            v-model="searchQuery"
            class="pt-search__input"
            placeholder="搜索模板名称 / 内容 / 描述..."
            @input="handleSearchInput"
          />
        </div>
        <select
          v-model="filterCategory"
          class="pt-select"
          @change="handleFilterChange"
        >
          <option value="">全部分类</option>
          <option v-for="c in PROMPT_CATEGORIES" :key="c.value" :value="c.value">
            {{ c.label }}
          </option>
        </select>
        <select
          v-model="filterStatus"
          class="pt-select"
          @change="handleFilterChange"
        >
          <option value="">全部状态</option>
          <option value="active">已启用</option>
          <option value="archived">已归档</option>
        </select>
      </div>
      <div class="pt-filters__right text-muted">
        共 {{ total }} 条
      </div>
    </div>

    <!-- 操作反馈 -->
    <div v-if="flash" class="pt-flash" :class="`pt-flash--${flashType}`">
      <span class="pt-flash__icon">{{ flashIcon }}</span>
      <span>{{ flash }}</span>
    </div>

    <!-- Mock 数据横幅（后端未连接时） -->
    <div v-if="mockMode" class="pt-mock-banner">
      <span class="pt-mock-banner__icon">🧪</span>
      <span>
        Prompt 模板后端服务尚未连接（<code>/api/v1/prompt-templates</code>
        不可达），当前展示<b>示例数据</b>以便验收页面。后端就绪后自动切换为实时数据。
      </span>
      <button class="pt-mock-banner__btn" @click="fetchTemplates">重新连接</button>
    </div>

    <!-- 加载中 -->
    <LoadingState v-if="loading && !mockMode" text="加载模板列表..." />

    <!-- 空状态 -->
    <EmptyState
      v-else-if="items.length === 0"
      icon="📝"
      title="暂无 Prompt 模板"
      :description="
        hasActiveFilters
          ? '没有匹配的结果，试试调整搜索或筛选条件'
          : '还没有任何模板，点击「新建模板」创建你的第一个 Prompt'
      "
      :show-action="!hasActiveFilters && !mockMode"
      action-text="新建模板"
      @action="showCreateDialog = true"
    />

    <!-- 模板卡片网格 -->
    <div v-else class="pt-grid">
      <PromptTemplateCard
        v-for="t in items"
        :key="t.id"
        :item="t"
        :acting-id="actingId"
        @edit="handleEdit"
        @preview="handlePreview"
        @delete="handleDeleteRequest"
      />
    </div>

    <!-- 分页：共 X 条，第 X/Y 页 -->
    <div v-if="total > 0 && !loading" class="pt-pagination">
      <span class="pt-pagination__info">共 {{ total }} 条</span>
      <button
        class="pt-page-btn"
        :disabled="currentPage === 1"
        @click="goPage(currentPage - 1)"
      >
        上一页
      </button>
      <span class="pt-page-btn__current">{{ currentPage }} / {{ pageCount }}</span>
      <button
        class="pt-page-btn"
        :disabled="currentPage >= pageCount"
        @click="goPage(currentPage + 1)"
      >
        下一页
      </button>
    </div>

    <!-- 新建/编辑模板表单（P1-002 G，同一组件双模式；组件自带 Modal） -->
    <PromptFormDialog
      v-if="showCreateDialog"
      key="create"
      title="新建 Prompt 模板"
      :updating="creating"
      :submitted="createSubmitted"
      @submit="handleFormSubmit"
      @close="closeCreateDialog"
    />

    <PromptFormDialog
      v-if="editingItem"
      :key="`edit-${editingItem.id}`"
      :title="`编辑 Prompt 模板 · ${editingItem.name}`"
      :item="editingItem"
      :updating="updating"
      :submitted="editSubmitted"
      @submit="handleFormSubmit"
      @close="closeEditDialog"
    />

    <!-- 预览（复用 P1-002 预览弹窗） -->
    <PromptPreviewDialog
      v-if="previewItem"
      :open="previewItem !== null"
      :title="`预览 · ${previewItem.name}`"
      :content="previewItem.content"
      :variables="previewVars"
      @close="previewItem = null"
    />

    <!-- 删除确认 -->
    <PromptDeleteConfirm
      v-if="deletingItem"
      :item="deletingItem"
      :busy="actingId === deletingItem.id"
      @cancel="deletingItem = null"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PromptTemplateCard from '@/components/prompts/PromptTemplateCard.vue'
import PromptFormDialog from '@/components/prompts/PromptFormDialog.vue'
import PromptDeleteConfirm from '@/components/prompts/PromptDeleteConfirm.vue'
import PromptPreviewDialog from '@/components/prompt/PromptPreviewDialog.vue'
import { usePromptTemplateStore, PROMPT_CATEGORIES } from '@/stores/promptTemplate'
import type {
  PromptTemplateListItem,
  PromptFormEditPayload,
  VariableDef,
} from '@/api/types'

const store = usePromptTemplateStore()
const { loading } = storeToRefs(store)

// ---- 视图本地筛选状态（实时模式下同步给 store；Mock 模式下本地计算） ----
const searchQuery = ref('')
const filterCategory = ref('')
const filterStatus = ref<'' | 'active' | 'archived'>('')
const currentPage = ref(1)

let searchDebounce: number | undefined

// ---- Mock 数据（后端未连接时供视觉验收，字段形状与后端 PromptTemplateResponse 一致） ----
const mockMode = ref(false)
const mockReady = ref(false)

const iso = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86400000).toISOString()

const MOCK_TEMPLATES: PromptTemplateListItem[] = [
  {
    id: 'a1e00001-0000-4000-8000-000000000001',
    name: '系统提示词 · 智能客服',
    description: '客服场景的基线系统提示词，约束角色与回复风格。',
    content:
      '你是一位友善的家谱平台客服助手。请用{{tone}}的语气回复，每次回答不超过{{max_words}}字，涉及隐私信息须按{{privacy_rule}}处理。',
    template_type: 'system',
    category: 'custom',
    variables: ['tone', 'max_words', 'privacy_rule'],
    version: 3,
    is_baseline: true,
    created_at: iso(48),
    updated_at: iso(6),
  },
  {
    id: 'a1e00002-0000-4000-8000-000000000002',
    name: '开场白 · 节日版',
    description: '节日问候场景的开场白模板。',
    content:
      '尊敬的{{user_name}}，今天是{{holiday}}，祝您节日愉快！愿这份问候如{{gift}}般温暖。',
    template_type: 'greeting',
    category: 'holiday_greeting',
    variables: ['user_name', 'holiday', 'gift'],
    version: 2,
    is_baseline: true,
    created_at: iso(40),
    updated_at: iso(2),
  },
  {
    id: 'a1e00003-0000-4000-8000-000000000003',
    name: '家族故事生成',
    description: '根据姓氏与用户信息生成通俗的家族起源故事。',
    content:
      '你是一位家谱专家。请为{{user_name}}介绍{{surname}}姓氏的起源。\n背景信息：\n- 姓氏：{{surname}}\n- 兴趣点：{{interest}}（可选）\n\n请生成一段通俗易懂的介绍，字数在{{word_count}}字以内。',
    template_type: 'conversation',
    category: 'family_story',
    variables: ['user_name', 'surname', 'interest', 'word_count'],
    version: 2,
    is_baseline: true,
    created_at: iso(35),
    updated_at: iso(4),
  },
  {
    id: 'a1e00004-0000-4000-8000-000000000004',
    name: '祖先人物评价',
    description: '为指定祖先人物生成客观评价与事迹回顾。',
    content:
      '请基于史料对{{ancestor_name}}（{{era}}时期人物）进行客观评价，突出其{{contribution}}方面的贡献，语言庄重，篇幅约{{length}}字。',
    template_type: 'conversation',
    category: 'ancestor_eval',
    variables: ['ancestor_name', 'era', 'contribution', 'length'],
    version: 1,
    is_baseline: true,
    created_at: iso(30),
    updated_at: iso(30),
  },
  {
    id: 'a1e00005-0000-4000-8000-000000000005',
    name: '亲属关系查询',
    description: '回答「A 与 B 是什么关系」类问题的系统提示。',
    content:
      '你是家谱关系专家。请根据{{person_a}}与{{person_b}}的血缘路径，用一句{{depth_limit}}层以内的话说明关系，并标注辈分差。',
    template_type: 'system',
    category: 'relation_query',
    variables: ['person_a', 'person_b', 'depth_limit'],
    version: 1,
    is_baseline: true,
    created_at: iso(28),
    updated_at: iso(28),
  },
  {
    id: 'a1e00006-0000-4000-8000-000000000006',
    name: '春节祝福卡片',
    description: '生成春节贺词，适配卡片短文案。',
    content:
      '为{{family_name}}家族写一段春节祝福，风格为{{style}}，不超过{{chars}}字，开头用「{{salutation}}」。',
    template_type: 'greeting',
    category: 'holiday_greeting',
    variables: ['family_name', 'style', 'chars', 'salutation'],
    version: 1,
    is_baseline: true,
    created_at: iso(24),
    updated_at: iso(24),
  },
  {
    id: 'a1e00007-0000-4000-8000-000000000007',
    name: '清明追思文案',
    description: '清明节祭祖场景的追思短文模板。',
    content:
      '请为故去的{{deceased_name}}（{{birth_year}}-{{pass_year}}）写一段清明追思文案，情感基调为{{mood}}，突出其{{virtue}}的品格。',
    template_type: 'greeting',
    category: 'holiday_greeting',
    variables: ['deceased_name', 'birth_year', 'pass_year', 'mood', 'virtue'],
    version: 1,
    is_baseline: true,
    created_at: iso(20),
    updated_at: iso(20),
  },
  {
    id: 'a1e00008-0000-4000-8000-000000000008',
    name: '代码审查助手',
    description: '研发流程中用于代码审查的系统提示。',
    content:
      '请审查以下{{language}}代码片段：\n```\n{{code}}\n```\n按{{review_focus}}重点检查，输出问题清单与修复建议，严重级别标注 {{severity_scale}}。',
    template_type: 'system',
    category: 'custom',
    variables: ['language', 'code', 'review_focus', 'severity_scale'],
    version: 5,
    is_baseline: true,
    created_at: iso(60),
    updated_at: iso(1),
  },
  {
    id: 'a1e00009-0000-4000-8000-000000000009',
    name: '文档生成助手',
    description: '将要点列表扩展为结构化技术文档。',
    content:
      '根据以下要点撰写{{doc_type}}：\n{{outline}}\n目标读者为{{audience}}，每个小节以一句话摘要开头，总篇幅约{{words}}字。',
    template_type: 'custom',
    category: 'custom',
    variables: ['doc_type', 'outline', 'audience', 'words'],
    version: 2,
    is_baseline: true,
    created_at: iso(26),
    updated_at: iso(9),
  },
  {
    id: 'a1e00010-0000-4000-8000-000000000010',
    name: '开场白 · 日常版',
    description: '日常对话场景的轻松开场白。',
    content: '你好{{user_name}}！今天是{{weekday}}，想了解{{topic}}相关的什么内容呢？',
    template_type: 'greeting',
    category: 'custom',
    variables: ['user_name', 'weekday', 'topic'],
    version: 2,
    is_baseline: true,
    created_at: iso(22),
    updated_at: iso(12),
  },
  {
    id: 'a1e00011-0000-4000-8000-000000000011',
    name: '族谱口述史整理',
    description: '将长辈口述内容整理为口述史章节。',
    content:
      '请将以下口述录音转写整理为口述史章节：\n{{transcript}}\n保留讲述者{{speaker}}的原话风格，整理为{{genre}}体裁，标注不确定处为「〔待核〕」。',
    template_type: 'conversation',
    category: 'family_story',
    variables: ['transcript', 'speaker', 'genre'],
    version: 4,
    is_baseline: true,
    created_at: iso(50),
    updated_at: iso(3),
  },
  {
    id: 'a1e00012-0000-4000-8000-000000000012',
    name: '支系寻根问答',
    description: '回答用户寻根问祖类问题的系统提示。',
    content:
      '你是支系寻根顾问。请根据{{surname}}{{branch}}支系的{{region}}地区资料，回答{{question}}，引用出处标注〔{{source}}〕。',
    template_type: 'system',
    category: 'relation_query',
    variables: ['surname', 'branch', 'region', 'question', 'source'],
    version: 1,
    is_baseline: true,
    created_at: iso(15),
    updated_at: iso(15),
  },
  {
    id: 'a1e00013-0000-4000-8000-000000000013',
    name: '家宴座次安排',
    description: '按礼制为家宴安排座次并生成说明。',
    content:
      '为{{host_name}}主持的{{event}}安排{{guest_count}}人座次，遵循{{etiquette}}礼制，长辈{{elders}}坐主位，输出座次表与安排说明。',
    template_type: 'custom',
    category: 'family_story',
    variables: ['host_name', 'event', 'guest_count', 'etiquette', 'elders'],
    version: 1,
    is_baseline: true,
    created_at: iso(10),
    updated_at: iso(10),
  },
  {
    id: 'a1e00014-0000-4000-8000-000000000014',
    name: '中秋团圆寄语（旧版）',
    description: '旧版中秋寄语，已由节日版替代。',
    content: '月圆人团圆。{{family_name}}家族祝您{{holiday}}快乐，常回家看看。',
    template_type: 'greeting',
    category: 'holiday_greeting',
    variables: ['family_name', 'holiday'],
    version: 1,
    is_baseline: false,
    created_at: iso(90),
    updated_at: iso(70),
  },
  {
    id: 'a1e00015-0000-4000-8000-000000000015',
    name: '系统提示词 v1（归档）',
    description: '客服系统提示词的早期版本，归档保留。',
    content: '你是客服助手，请回答{{question}}。',
    template_type: 'system',
    category: 'custom',
    variables: ['question'],
    version: 1,
    is_baseline: false,
    created_at: iso(120),
    updated_at: iso(95),
  },
]

const MOCK_PAGE_SIZE = 9

// ---- 派生数据 ----
const filteredMock = computed(() => {
  let list = MOCK_TEMPLATES
  const cat = filterCategory.value
  if (cat) list = list.filter((t) => t.category === cat)
  if (filterStatus.value) {
    list = list.filter((t) =>
      filterStatus.value === 'archived'
        ? t.is_baseline === false
        : t.is_baseline === true,
    )
  }
  const kw = searchQuery.value.trim().toLowerCase()
  if (kw) {
    list = list.filter((t) =>
      [t.name, t.description ?? '', t.content, t.category ?? '']
        .join(' ')
        .toLowerCase()
        .includes(kw),
    )
  }
  return list
})

const total = computed(() =>
  mockMode.value ? filteredMock.value.length : (store.total ?? 0),
)

const pageCount = computed(() =>
  Math.max(
    1,
    Math.ceil(total.value / (mockMode.value ? MOCK_PAGE_SIZE : store.pageSize)),
  ),
)

const items = computed<PromptTemplateListItem[]>(() => {
  if (mockMode.value) {
    const p = Math.min(currentPage.value, pageCount.value)
    return filteredMock.value.slice((p - 1) * MOCK_PAGE_SIZE, p * MOCK_PAGE_SIZE)
  }
  return store.visibleTemplates
})

const hasActiveFilters = computed(
  () =>
    searchQuery.value.trim() !== '' ||
    filterCategory.value !== '' ||
    filterStatus.value !== '',
)

// ---- 对话框状态 ----
const showCreateDialog = ref(false)
const creating = ref(false)
const createSubmitted = ref(false)
const editingItem = ref<PromptTemplateListItem | null>(null)
const updating = ref(false)
const editSubmitted = ref(false)
const previewItem = ref<PromptTemplateListItem | null>(null)
const deletingItem = ref<PromptTemplateListItem | null>(null)
const actingId = ref('')

/** 保存成功：按钮显示「✓ 已保存」短暂延迟后自动关闭弹窗 */
let savedTimer: number | undefined
function closeAfterSaved(isCreate: boolean) {
  if (savedTimer) window.clearTimeout(savedTimer)
  savedTimer = window.setTimeout(() => {
    savedTimer = undefined
    if (isCreate) {
      showCreateDialog.value = false
      createSubmitted.value = false
    } else {
      closeEditDialog()
      editSubmitted.value = false
    }
  }, 900)
}

const previewVars = computed<VariableDef[]>(() => {
  if (!previewItem.value) return []
  const names = new Set(previewItem.value.variables ?? [])
  return [...names].map((name) => ({
    name,
    description: '',
    required: false,
  }))
})

// ---- 轻提示 ----
const flash = ref('')
const flashType = ref<'success' | 'error'>('success')
let flashTimer: number | undefined

function showFlash(message: string, type: 'success' | 'error' = 'success') {
  flash.value = message
  flashType.value = type
  if (flashTimer) window.clearTimeout(flashTimer)
  flashTimer = window.setTimeout(() => {
    flash.value = ''
  }, 2600)
}
const flashIcon = computed(() => (flashType.value === 'error' ? '⚠' : '✓'))

// ---- 数据拉取 ----
async function fetchTemplates() {
  searchQuery.value = ''
  filterCategory.value = ''
  filterStatus.value = ''
  currentPage.value = 1
  try {
    await store.fetchTemplates()
    mockMode.value = false
    mockReady.value = true
  } catch (error) {
    // 后端未就绪 → 进入 Mock 模式（框架可用、数据为示例）
    mockMode.value = true
    mockReady.value = true
    console.warn('[PromptTemplatesView] Prompt API 尚未就绪，使用示例数据:', error)
  }
}

function handleSearchInput() {
  if (searchDebounce) window.clearTimeout(searchDebounce)
  searchDebounce = window.setTimeout(() => {
    currentPage.value = 1
    if (!mockMode.value) store.setSearchKeyword(searchQuery.value)
  }, 250)
}

function handleFilterChange() {
  currentPage.value = 1
  if (mockMode.value) return // mock 模式下 computed 自动生效
  store.setCategoryFilter(
    (filterCategory.value || undefined) as Parameters<typeof store.setCategoryFilter>[0],
  )
  store.setStatusFilter(
    (filterStatus.value || '') as Parameters<typeof store.setStatusFilter>[0],
  )
  if (searchQuery.value.trim()) store.setSearchKeyword(searchQuery.value)
}

function goPage(page: number) {
  if (page < 1 || page > pageCount.value) return
  currentPage.value = page
  if (mockMode.value) return
  store.setPage(page)
}

// ---- CRUD ----
function handleEdit(item: PromptTemplateListItem) {
  editingItem.value = item
  editSubmitted.value = false
}

function handlePreview(item: PromptTemplateListItem) {
  previewItem.value = item
}

function handleDeleteRequest(item: PromptTemplateListItem) {
  deletingItem.value = item
}

/**
 * 统一表单提交（新建 / 编辑共用）。
 * 新建 → POST /prompt-templates/（基线版本）；编辑 → PUT /prompt-templates/{id}（生成新版本）。
 * Mock 模式（后端未连接）下对本地 MOCK_TEMPLATES 直接增改，便于视觉验收。
 */
async function handleFormSubmit(data: PromptFormEditPayload) {
  // ---- 编辑模式 ----
  if (editingItem.value) {
    updating.value = true
    try {
      if (mockMode.value && editingItem.value.id.startsWith('local-')) {
        const it = MOCK_TEMPLATES.find((t) => t.id === editingItem.value!.id)
        if (it) {
          it.name = data.name
          it.description = data.description ?? undefined
          it.content = data.content
          it.template_type = data.template_type
          it.category = data.category ?? undefined
          it.variables = data.variables
          it.version += 1
          it.updated_at = new Date().toISOString()
        }
        showFlash(`模板「${data.name}」已保存（示例数据）`)
      } else {
        await store.updateTemplate(editingItem.value.id, {
          name: data.name,
          content: data.content,
          template_type: data.template_type,
          category: data.category,
          description: data.description,
          variables: data.variables,
          tags: data.tags,
          variable_defs: data.variable_defs,
        })
        showFlash(`模板「${data.name}」已保存（生成新版本）`)
      }
      editSubmitted.value = true
      closeAfterSaved(false)
    } catch (error) {
      console.error('更新模板失败:', error)
      showFlash('保存失败，请重试', 'error')
    } finally {
      updating.value = false
    }
    return
  }

  // ---- 新建模式 ----
  creating.value = true
  try {
    if (mockMode.value) {
      MOCK_TEMPLATES.unshift({
        id: `local-${Date.now()}`,
        name: data.name,
        description: data.description ?? undefined,
        content: data.content,
        template_type: data.template_type,
        category: data.category ?? undefined,
        variables: data.variables,
        version: 1,
        is_baseline: true,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      })
      currentPage.value = 1
      showFlash(`模板「${data.name}」已创建（示例数据）`)
    } else {
      await store.createTemplate({
        name: data.name,
        description: data.description ?? undefined,
        content: data.content,
        template_type: data.template_type,
        category: data.category ?? undefined,
        variables: data.variables,
        is_baseline: true,
      })
      showFlash(`模板「${data.name}」已创建`)
    }
    createSubmitted.value = true
    closeAfterSaved(true)
  } catch (error) {
    console.error('创建模板失败:', error)
    showFlash('创建模板失败，请重试', 'error')
  } finally {
    creating.value = false
  }
}

async function confirmDelete() {
  if (!deletingItem.value) return
  const target = deletingItem.value
  actingId.value = target.id
  try {
    if (mockMode.value) {
      const idx = MOCK_TEMPLATES.findIndex((t) => t.id === target.id)
      if (idx !== -1) MOCK_TEMPLATES.splice(idx, 1)
      // 当前页删除后若不足一页则回退一页
      if (items.value.length === 0 && currentPage.value > 1) {
        currentPage.value -= 1
      }
      showFlash(`模板「${target.name}」已删除（示例数据）`)
    } else {
      await store.deleteTemplate(target.id)
      showFlash(`模板「${target.name}」已删除`)
    }
    deletingItem.value = null
  } catch (error) {
    console.error('删除模板失败:', error)
    showFlash('删除失败，请重试', 'error')
  } finally {
    actingId.value = ''
  }
}

function closeCreateDialog() {
  showCreateDialog.value = false
  createSubmitted.value = false
}

function closeEditDialog() {
  editingItem.value = null
  editSubmitted.value = false
}

// 实时模式下，搜索输入直接驱动 store 的客户端过滤（保持 computed 视图同步）
watch(searchQuery, (v) => {
  if (!mockMode.value) store.setSearchKeyword(v)
})

onMounted(fetchTemplates)
onBeforeUnmount(() => {
  if (searchDebounce) window.clearTimeout(searchDebounce)
  if (flashTimer) window.clearTimeout(flashTimer)
  if (savedTimer) window.clearTimeout(savedTimer)
})
</script>

<style scoped>
/* ===== P1-002 列表页局部设计令牌（东方雅致） =====
   任务规范：#8D6E63 古铜棕主色 / #F9F7F2 宣纸白背景 /
   Noto Serif SC 标题 / Noto Sans SC 正文 /
   卡片阴影 0 4px 12px rgba(0,0,0,0.05) / 圆角 8px
   通过 .pt-page 作用域内的 --pt-* 变量实现，不污染全局 tokens.css */
.pt-page {
  --pt-primary: #8d6e63;
  --pt-primary-light: #f3ece8;
  --pt-bg: #f9f7f2;
  --pt-bg-card: #ffffff;
  --pt-bg-secondary: #faf8f4;
  --pt-bg-tertiary: #f7f4ef;
  --pt-text: #3a2f2a;
  --pt-text-secondary: #7a6f68;
  --pt-text-muted: #a89d95;
  --pt-border: #e8e2d6;
  --pt-radius: 8px;
  --pt-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);

  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--pt-bg);
  border-radius: var(--pt-radius);
  padding: 4px;
  font-family: 'Noto Sans SC', -apple-system, sans-serif;
}

/* 标题字体（PageHeader 为子组件，需 :deep 穿透 scoped 边界） */
.pt-page :deep(.page-header__title) {
  font-family: 'Noto Serif SC', 'Noto Sans SC', serif;
  color: var(--pt-text);
}

/* ---- 主按钮（新建模板） ---- */
.pt-btn {
  padding: 8px 18px;
  font-size: 14px;
  font-family: 'Noto Sans SC', sans-serif;
  border-radius: var(--pt-radius);
  cursor: pointer;
  transition: all 0.15s ease;
  border: 1px solid transparent;
}

.pt-btn--primary {
  background: var(--pt-primary);
  color: #fff;
  box-shadow: var(--pt-shadow);
}

.pt-btn--primary:hover:not(:disabled) {
  background: #7a5f54;
  transform: translateY(-1px);
}

.pt-btn--primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---- 筛选栏 ---- */
.pt-filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: var(--pt-bg-card);
  border: 1px solid var(--pt-border);
  border-radius: var(--pt-radius);
  box-shadow: var(--pt-shadow);
}

.pt-filters__left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.pt-filters__right {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--pt-text-secondary);
}

.pt-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  background: var(--pt-bg-secondary);
  border: 1px solid var(--pt-border);
  border-radius: var(--pt-radius);
  min-width: 260px;
}

.pt-search__icon {
  font-size: 13px;
  opacity: 0.7;
}

.pt-search__input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  font-family: 'Noto Sans SC', sans-serif;
  color: var(--pt-text);
  width: 100%;
}

.pt-select {
  padding: 7px 30px 7px 12px;
  font-size: 13px;
  font-family: 'Noto Sans SC', sans-serif;
  color: var(--pt-text);
  background: var(--pt-bg-secondary);
  border: 1px solid var(--pt-border);
  border-radius: var(--pt-radius);
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%238D6E63'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
}

.pt-select:focus {
  outline: none;
  border-color: var(--pt-primary);
}

/* ---- 轻提示 ---- */
.pt-flash {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--pt-radius);
  font-size: 13px;
}

.pt-flash--success {
  background: #e8f5e9;
  color: #15803d;
  border: 1px solid #c8e6c9;
}

.pt-flash--error {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.pt-flash__icon {
  font-weight: 700;
}

/* ---- Mock 横幅 ---- */
.pt-mock-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--pt-bg-tertiary);
  border: 1px dashed var(--pt-primary);
  border-radius: var(--pt-radius);
  font-size: 13px;
  color: var(--pt-text-secondary);
  line-height: 1.6;
}

.pt-mock-banner__icon {
  font-size: 18px;
  flex-shrink: 0;
}

.pt-mock-banner code {
  font-size: 12px;
  background: var(--pt-bg-card);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: 'Consolas', monospace;
}

.pt-mock-banner__btn {
  flex-shrink: 0;
  margin-left: auto;
  padding: 5px 14px;
  font-size: 13px;
  color: var(--pt-primary);
  background: var(--pt-bg-card);
  border: 1px solid var(--pt-primary);
  border-radius: var(--pt-radius);
  cursor: pointer;
  transition: all 0.15s ease;
}

.pt-mock-banner__btn:hover {
  background: var(--pt-primary);
  color: #fff;
}

/* ---- 卡片网格：响应式列数（≥1200px 三列 / 900-1199px 两列 / <900px 单列） ----
   注意：断点按「视口宽度」计算，AppLayout 内容区还有 sidebar(240px)+padding(48px)，
   因此阈值需加上该偏移，使实际观感与任务规范一致 */
.pt-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

@media (max-width: 1439px) {
  .pt-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 1139px) {
  .pt-grid {
    grid-template-columns: 1fr;
  }
}

/* ---- 分页：共 X 条，第 X/Y 页 ---- */
.pt-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 16px;
  background: var(--pt-bg-card);
  border: 1px solid var(--pt-border);
  border-radius: var(--pt-radius);
  box-shadow: var(--pt-shadow);
}

.pt-pagination__info {
  margin-right: auto;
  font-size: 13px;
  color: var(--pt-text-secondary);
}

.pt-page-btn {
  padding: 6px 14px;
  font-size: 13px;
  font-family: 'Noto Sans SC', sans-serif;
  color: var(--pt-text);
  background: var(--pt-bg-card);
  border: 1px solid var(--pt-border);
  border-radius: var(--pt-radius);
  cursor: pointer;
  transition: all 0.15s ease;
}

.pt-page-btn:hover:not(:disabled) {
  border-color: var(--pt-primary);
  color: var(--pt-primary);
}

.pt-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pt-page-btn__current {
  font-size: 13px;
  color: var(--pt-primary);
  font-weight: 600;
  padding: 4px 10px;
  background: var(--pt-primary-light);
  border-radius: var(--pt-radius);
}
</style>
