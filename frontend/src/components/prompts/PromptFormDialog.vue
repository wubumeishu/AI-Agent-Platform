<template>
  <Modal :title="title" width="720px" @close="emit('close')">
    <form class="pfe-form" @submit.prevent="handleSubmit">
      <!-- 表单主体：最大 600px 高、可滚动（设计规范） -->
      <div class="pfe-form__scroll">
        <!-- 模板名称 * -->
        <div class="pfe-form__group">
          <label class="pfe-form__label" for="pfe-name">
            模板名称 <span class="pfe-form__req">*</span>
          </label>
          <input
            id="pfe-name"
            v-model.trim="form.name"
            class="pfe-form__input"
            :class="{ 'pfe-form__input--error': touched.name && fieldErrors.name }"
            placeholder="例如：家族故事开场介绍"
            maxlength="200"
            @blur="touched.name = true"
          />
          <span v-if="touched.name && fieldErrors.name" class="pfe-form__field-error">
            {{ fieldErrors.name }}
          </span>
        </div>

        <!-- 类型 + 分类（双列） -->
        <div class="pfe-form__row">
          <div class="pfe-form__group">
            <label class="pfe-form__label" for="pfe-type">模板类型</label>
            <select id="pfe-type" v-model="form.template_type" class="pfe-form__select">
              <option v-for="t in PROMPT_TEMPLATE_TYPES" :key="t.value" :value="t.value">
                {{ t.label }}
              </option>
            </select>
          </div>
          <div class="pfe-form__group">
            <label class="pfe-form__label" for="pfe-category">
              分类 <span class="pfe-form__req">*</span>
            </label>
            <select
              id="pfe-category"
              v-model="form.category"
              class="pfe-form__select"
              :class="{ 'pfe-form__input--error': touched.category && fieldErrors.category }"
              @blur="touched.category = true"
            >
              <option value="">请选择分类</option>
              <option v-for="c in PROMPT_CATEGORIES" :key="c.value" :value="c.value">
                {{ c.label }}
              </option>
            </select>
            <span v-if="touched.category && fieldErrors.category" class="pfe-form__field-error">
              {{ fieldErrors.category }}
            </span>
          </div>
        </div>

        <!-- 标签（chip 编辑器） -->
        <div class="pfe-form__group">
          <label class="pfe-form__label">标签</label>
          <div class="pfe-form__tagbox">
            <span
              v-for="tag in form.tags"
              :key="tag"
              class="pfe-tag-chip"
            >
              {{ tag }}
              <button
                type="button"
                class="pfe-tag-chip__x"
                :aria-label="`删除标签 ${tag}`"
                @click="removeTag(tag)"
              >
                ×
              </button>
            </span>
            <input
              v-model="tagDraft"
              class="pfe-form__tagbox-input"
              placeholder="输入后回车添加"
              @keydown.enter.prevent="addTagFromDraft"
            />
            <button
              type="button"
              class="pfe-form__tagbox-plus"
              :disabled="!tagDraft.trim()"
              @click="addTagFromDraft"
            >
              +
            </button>
          </div>
          <span class="pfe-form__hint-text">用于检索与筛选，可添加多个标签</span>
        </div>

        <!-- 描述 -->
        <div class="pfe-form__group">
          <label class="pfe-form__label" for="pfe-desc">描述</label>
          <input
            id="pfe-desc"
            v-model.trim="form.description"
            class="pfe-form__input"
            placeholder="一句话说明该模板的用途（可选）"
            maxlength="200"
          />
        </div>

        <!-- 模板内容 + 变量自动识别 -->
        <div class="pfe-form__group">
          <label class="pfe-form__label" for="pfe-content">
            模板内容 <span class="pfe-form__req">*</span>
          </label>
          <textarea
            id="pfe-content"
            v-model="form.content"
            class="pfe-form__textarea"
            :class="{ 'pfe-form__input--error': touched.content && fieldErrors.content }"
            placeholder="请为{{user_name}}介绍{{surname}}姓氏的起源..."
            rows="7"
            @blur="touched.content = true"
          ></textarea>
          <span v-if="touched.content && fieldErrors.content" class="pfe-form__field-error">
            {{ fieldErrors.content }}
          </span>

          <!-- 变量实时预览：随内容输入即时解析 {{variable}} -->
          <div class="pfe-form__vars">
            <span class="pfe-form__vars-label">识别到的变量：</span>
            <template v-if="detectedVars.length > 0">
              <span
                v-for="v in detectedVars"
                :key="v"
                class="pfe-form__var-chip"
              >{{ v }}</span>
            </template>
            <span v-else class="pfe-form__vars-empty">（暂未识别到变量）</span>
          </div>

          <!-- 变量定义表 -->
          <div class="pfe-form__vars-table-wrap">
            <table class="pfe-form__vars-table">
              <thead>
                <tr>
                  <th>变量名</th>
                  <th>说明</th>
                  <th>默认值</th>
                  <th class="pfe-form__col-req">必填</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="activeVarDefs.length === 0">
                  <td colspan="4" class="pfe-form__vars-empty">
                    内容中输入 {{ '{variable}' }} 后自动生成变量定义
                  </td>
                </tr>
                <tr v-for="def in activeVarDefs" :key="def.name">
                  <td>
                    <code class="pfe-form__var-name">{{ def.name }}</code>
                  </td>
                  <td>
                    <input
                      v-model.trim="def.description"
                      class="pfe-form__cell-input"
                      placeholder="变量说明"
                    />
                  </td>
                  <td>
                    <input
                      v-model="def.defaultValue"
                      class="pfe-form__cell-input"
                      placeholder="默认值（可选）"
                    />
                  </td>
                  <td class="pfe-form__col-req">
                    <input
                      v-model="def.required"
                      type="checkbox"
                      class="pfe-form__checkbox"
                      :aria-label="`${def.name} 是否必填`"
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 提交级错误（必填项校验不通过时） -->
      <div v-if="submitError" class="pfe-form__error">
        <span class="pfe-form__error-icon">⚠</span> {{ submitError }}
      </div>

      <!-- 底部：取消 / 保存（保存按钮 56px 高、古铜棕背景） -->
      <div class="pfe-form__footer">
        <button type="button" class="btn btn--ghost" @click="emit('close')">取消</button>
        <button
          type="submit"
          class="pfe-form__save"
          :disabled="updating || submitted"
        >
          {{ updating ? '保存中…' : submitted ? '✓ 已保存' : submitLabel }}
        </button>
      </div>
    </form>
  </Modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import Modal from '@/components/common/Modal.vue'
import type {
  PromptTemplateListItem,
  PromptTemplateType,
  VariableDef,
  PromptFormEditPayload,
} from '@/api/types'
import {
  PROMPT_TEMPLATE_TYPES,
  PROMPT_CATEGORIES,
} from '@/stores/promptTemplate'
import { extractTemplateVariables } from '@/composables/usePromptRender'

const props = withDefaults(
  defineProps<{
    /** 弹窗标题：新建 / 编辑（模板名） */
    title: string
    /** 编辑模式下传入模板数据；不传则为新建模式 */
    item?: PromptTemplateListItem
    updating?: boolean
    /** 保存成功后父级可传入 true 让按钮显示「已保存」态 */
    submitted?: boolean
  }>(),
  { item: undefined, updating: false, submitted: false },
)

const emit = defineEmits<{
  (e: 'close'): void
  /** 提交表单（校验通过）；新建/编辑共用，父级根据 item 决定调 create 还是 update */
  (e: 'submit', data: PromptFormEditPayload): void
}>()

// ---- 表单状态（新建 / 编辑共用，打开时由父级 key 重建） ----
const form = reactive({
  name: props.item?.name ?? '',
  description: props.item?.description ?? '',
  template_type: (props.item?.template_type ?? 'custom') as PromptTemplateType,
  category: (props.item?.category ?? '') as string,
  tags: (props.item as PromptTemplateListItem & { tags?: string[] } | undefined)?.tags ?? [],
  content: props.item?.content ?? '',
})

const fieldErrors = reactive({
  name: '',
  category: '',
  content: '',
})
const touched = reactive({
  name: false,
  category: false,
  content: false,
})
const submitError = ref('')

const submitLabel = computed(() =>
  props.item ? '保存' : '保存模板',
)

// ---- 标签编辑器 ----
const tagDraft = ref('')

function addTagFromDraft() {
  const value = tagDraft.value.trim()
  if (!value) return
  if (!form.tags.includes(value)) {
    form.tags.push(value)
  }
  tagDraft.value = ''
}

function removeTag(tag: string) {
  form.tags = form.tags.filter((t) => t !== tag)
}

// ---- 变量自动提取：输入内容时实时解析 ----
const detectedVars = computed(() => extractTemplateVariables(form.content))

/** 变量定义行：保留用户已填写的说明/默认值/必填状态（跨内容编辑） */
const varDefs = reactive<VariableDef[]>([])

watch(
  detectedVars,
  (names) => {
    // 保留已存在的定义；为内容中新增的变量追加一行（默认必填，符合 PRD 必填项校验）
    for (const name of names) {
      if (!varDefs.some((d) => d.name === name)) {
        varDefs.push({ name, description: '', required: true })
      }
    }
    // 内容中不再出现的变量：保留定义（用户可能恢复），但只展示当前出现的
  },
  { immediate: true },
)

/** 仅展示当前内容中出现的变量定义（与内容保持同步） */
const activeVarDefs = computed(() => {
  const present = new Set(detectedVars.value)
  return varDefs.filter((d) => present.has(d.name))
})

// ---- 校验：必填项（名称、分类、内容） ----
function validate(): boolean {
  fieldErrors.name = ''
  fieldErrors.category = ''
  fieldErrors.content = ''
  let ok = true

  if (!form.name.trim()) {
    fieldErrors.name = '请填写模板名称'
    ok = false
  }
  if (!form.category) {
    fieldErrors.category = '请选择分类'
    ok = false
  }
  if (!form.content.trim()) {
    fieldErrors.content = '请填写模板内容'
    ok = false
  }
  submitError.value = ok ? '' : '请完善必填项后再保存'
  return ok
}

function handleSubmit() {
  touched.name = true
  touched.category = true
  touched.content = true
  if (!validate()) return

  emit('submit', {
    name: form.name.trim(),
    content: form.content,
    template_type: form.template_type,
    category: form.category || null,
    description: form.description.trim() || null,
    variables: [...detectedVars.value],
    variable_defs: activeVarDefs.value.map((d) => ({ ...d })),
    tags: [...form.tags],
  })
}
</script>

<style scoped>
/* ===== P1-002 G 编辑表单：东方雅致（与列表页 --pt-* 令牌一致） =====
   设计规范：表单最高 600px 可滚动 / 保存按钮 56px 古铜棕 /
   输入框 40px 高、4px 圆角 / 变量随输入实时解析 */
.pfe-form {
  --pfe-copper: #8d6e63;
  --pfe-copper-hover: #7a5f54;
  --pfe-copper-light: #f3ece8;
  --pfe-text: #3a2f2a;
  --pfe-text-secondary: #7a6f68;
  --pfe-text-muted: #a89d95;
  --pfe-border: #e8e2d6;
  --pfe-bg-card: #ffffff;
  --pfe-bg-tertiary: #f7f4ef;
  --pfe-radius: 4px;

  display: flex;
  flex-direction: column;
  gap: 14px;
  font-family: 'Noto Sans SC', -apple-system, sans-serif;
}

/* 表单主体：最大 600px 高、内部滚动（设计规范） */
.pfe-form__scroll {
  max-height: 600px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 4px;
}

.pfe-form__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pfe-form__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 560px) {
  .pfe-form__row {
    grid-template-columns: 1fr;
  }
}

.pfe-form__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--pfe-text);
}

.pfe-form__req {
  color: #dc2626;
}

/* 输入框：40px 高、4px 圆角（设计规范） */
.pfe-form__input,
.pfe-form__select,
.pfe-form__textarea {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  font-size: 14px;
  color: var(--pfe-text);
  background: var(--pfe-bg-card);
  border: 1px solid var(--pfe-border);
  border-radius: var(--pfe-radius);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.pfe-form__textarea {
  height: auto;
  min-height: 120px;
  padding: 10px 12px;
  resize: vertical;
  line-height: 1.6;
  font-family: 'Consolas', 'Monaco', 'Noto Sans SC', monospace;
  font-size: 13px;
}

.pfe-form__select {
  appearance: none;
  cursor: pointer;
}

.pfe-form__input:focus,
.pfe-form__select:focus,
.pfe-form__textarea:focus {
  outline: none;
  border-color: var(--pfe-copper);
  box-shadow: 0 0 0 3px var(--pfe-copper-light);
}

.pfe-form__input--error {
  border-color: #dc2626;
}

.pfe-form__field-error {
  font-size: 12px;
  color: #dc2626;
}

/* ---- 标签 chip 编辑器 ---- */
.pfe-form__tagbox {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 40px;
  padding: 4px 8px;
  background: var(--pfe-bg-card);
  border: 1px solid var(--pfe-border);
  border-radius: var(--pfe-radius);
}

.pfe-form__tagbox:focus-within {
  border-color: var(--pfe-copper);
  box-shadow: 0 0 0 3px var(--pfe-copper-light);
}

.pfe-form__tagbox-input {
  flex: 1;
  min-width: 120px;
  height: 30px;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--pfe-text);
}

.pfe-form__tagbox-plus {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: 1px solid var(--pfe-copper);
  border-radius: var(--pfe-radius);
  background: transparent;
  color: var(--pfe-copper);
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.15s ease;
}

.pfe-form__tagbox-plus:hover:not(:disabled) {
  background: var(--pfe-copper);
  color: #fff;
}

.pfe-form__tagbox-plus:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.pfe-form__hint-text {
  font-size: 12px;
  color: var(--pfe-text-muted);
}

/* ---- 变量识别 / 变量定义表 ---- */
.pfe-form__vars {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.pfe-form__vars-label {
  font-size: 12px;
  color: var(--pfe-text-secondary);
}

.pfe-form__var-chip {
  font-size: 12px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: var(--pfe-copper);
  background: var(--pfe-copper-light);
  border-radius: 4px;
  padding: 2px 8px;
}

.pfe-form__vars-empty {
  font-size: 12px;
  color: var(--pfe-text-muted);
}

.pfe-form__vars-table-wrap {
  margin-top: 10px;
  border: 1px solid var(--pfe-border);
  border-radius: var(--pfe-radius);
  overflow-x: auto;
}

.pfe-form__vars-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pfe-form__vars-table th {
  padding: 8px 10px;
  text-align: left;
  font-weight: 500;
  font-size: 12px;
  color: var(--pfe-text-secondary);
  background: var(--pfe-bg-tertiary);
  border-bottom: 1px solid var(--pfe-border);
  white-space: nowrap;
}

.pfe-form__vars-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--pfe-bg-tertiary);
  vertical-align: middle;
}

.pfe-form__vars-table tbody tr:last-child td {
  border-bottom: none;
}

.pfe-form__col-req {
  width: 52px;
  text-align: center;
}

.pfe-form__vars-table .pfe-form__col-req th {
  text-align: center;
}

.pfe-form__var-name {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: var(--pfe-copper);
  background: var(--pfe-copper-light);
  padding: 1px 5px;
  border-radius: 4px;
}

.pfe-form__cell-input {
  width: 100%;
  min-width: 90px;
  height: 32px;
  padding: 0 8px;
  font-size: 13px;
  color: var(--pfe-text);
  background: var(--pfe-bg-card);
  border: 1px solid var(--pfe-border);
  border-radius: var(--pfe-radius);
}

.pfe-form__cell-input:focus {
  outline: none;
  border-color: var(--pfe-copper);
  box-shadow: 0 0 0 3px var(--pfe-copper-light);
}

.pfe-form__checkbox {
  width: 16px;
  height: 16px;
  accent-color: var(--pfe-copper);
  cursor: pointer;
  display: block;
  margin: 0 auto;
}

/* ---- 提交级错误 ---- */
.pfe-form__error {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #b91c1c;
  background: #fee2e2;
  border: 1px solid #fecaca;
  border-radius: var(--pfe-radius);
  padding: 8px 12px;
}

.pfe-form__error-icon {
  font-weight: 700;
}

/* ---- 底部：保存按钮 56px 高、古铜棕背景（设计规范） ---- */
.pfe-form__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--pfe-border);
}

.pfe-form__save {
  width: 160px;
  height: 56px;
  padding: 0 24px;
  font-size: 15px;
  font-weight: 600;
  font-family: 'Noto Sans SC', sans-serif;
  color: #fff;
  background: var(--pfe-copper);
  border: none;
  border-radius: var(--pfe-radius);
  cursor: pointer;
  transition: all 0.15s ease;
}

.pfe-form__save:hover:not(:disabled) {
  background: var(--pfe-copper-hover);
  transform: translateY(-1px);
}

.pfe-form__save:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}
</style>
