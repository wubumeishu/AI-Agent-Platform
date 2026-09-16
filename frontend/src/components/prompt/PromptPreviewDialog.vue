<template>
  <Modal
    v-if="open"
    :title="title || '预览 Prompt 渲染结果'"
    width="600px"
    @close="close()"
  >
    <!-- 1. 模板内容预览 -->
    <section class="preview-section">
      <div class="preview-section__label">模板内容预览：</div>
      <div class="content-preview">
        <template v-for="(token, i) in contentTokens" :key="i">
          <span v-if="token.type === 'var'" class="content-preview__var">
            {{ token.display }}
          </span>
          <span v-else class="content-preview__text">{{ token.display }}</span>
        </template>
      </div>
    </section>

    <!-- 2. 变量填写 -->
    <section class="preview-section">
      <div class="preview-section__label">变量填写：</div>

      <!-- 必填变量校验提示 -->
      <div v-if="missingRequired.length > 0" class="var-warning">
        <span class="var-warning__icon">⚠</span>
        请填写必填变量：
        <span v-for="(name, i) in missingRequired" :key="name">
          <span v-if="i > 0">、</span>
          <strong>{{ name }}</strong>
        </span>
      </div>

      <div class="var-form">
        <div
          v-for="def in variableDefs"
          :key="def.name"
          class="var-row"
          :class="{ 'var-row--error': isMissing(def.name) }"
        >
          <label class="var-row__label" :for="`var-${def.name}`">
            {{ def.name }}
            <span v-if="def.required" class="var-row__required">*</span>
          </label>
          <input
            :id="`var-${def.name}`"
            v-model="values[def.name]"
            class="var-row__input"
            :placeholder="inputPlaceholder(def)"
            @input="onValueInput(def.name)"
          />
          <span v-if="def.defaultValue" class="var-row__default">
            默认:{{ def.defaultValue }}
          </span>
        </div>

        <p v-if="variableDefs.length === 0" class="var-empty">
          该模板没有可替换的变量
        </p>
      </div>
    </section>

    <!-- 3. 渲染结果预览 -->
    <section class="preview-section">
      <div class="preview-section__label">渲染结果预览：</div>

      <div class="render-preview">
        <template v-if="renderedText !== null">
          <pre class="render-preview__text">{{ renderedText }}</pre>
          <p v-if="renderedUnfilled.length > 0" class="render-preview__note">
            （可选变量 {{ renderedUnfilled.join('、') }} 未填写，已保留原占位符）
          </p>
        </template>
        <div v-else class="render-preview__placeholder">
          请填写必填变量后查看渲染结果
        </div>
      </div>
    </section>

    <!-- 底部操作：[复制] [关闭] -->
    <template #footer>
      <div class="dialog-actions">
        <button
          class="btn btn--ghost"
          :disabled="copyDisabled || copied"
          :class="{ 'btn--success': copied }"
          @click="handleCopy()"
        >
          {{ copied ? '✓ 已复制' : '复制' }}
        </button>
        <button class="btn btn--ghost" @click="close()">关闭</button>
      </div>
    </template>
  </Modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import Modal from '../common/Modal.vue'
import type { VariableDef, PromptVariableValues } from '@/api/types'
import {
  collectVariableDefs,
  renderPromptTemplate,
  validateRequiredVariables,
} from '@/composables/usePromptRender'

const props = defineProps<{
  open: boolean
  /** 弹窗标题 */
  title?: string
  /** 模板内容（含 {{variable}} 占位符） */
  content: string
  /** 变量定义（必填 / 默认值 / 说明） */
  variables?: VariableDef[]
}>()

const emit = defineEmits<{
  (e: 'update:open', open: boolean): void
  (e: 'close'): void
  /** 复制成功后回调，携带当前变量值与渲染文本 */
  (e: 'copy', payload: { values: PromptVariableValues; text: string }): void
}>()

// ---------- 变量定义 ----------
const variableDefs = computed(() => collectVariableDefs(props.content, props.variables))

/** 打开弹窗（或模板变化）时，用默认值初始化输入 */
const values = reactive<PromptVariableValues>({})
const touched = reactive<Record<string, boolean>>({})

function initValues() {
  for (const def of variableDefs.value) {
    if (values[def.name] === undefined) {
      values[def.name] = def.defaultValue ?? ''
    }
  }
  // 清理已不存在的变量
  for (const key of Object.keys(values)) {
    if (!variableDefs.value.some((d) => d.name === key)) delete values[key]
  }
}

watch(
  () => [props.open, props.content, props.variables] as const,
  ([open]) => {
    if (open) initValues()
  },
  { immediate: true }
)

function onValueInput(name: string) {
  touched[name] = true
}

// ---------- 实时渲染 ----------
const renderResult = computed(() =>
  renderPromptTemplate(props.content, variableDefs.value, { ...values })
)

const renderedText = computed(() => renderResult.value.rendered)
const renderedUnfilled = computed(() => renderResult.value.unfilledOptional)

// ---------- 必填校验 ----------
const missingRequired = computed(() =>
  validateRequiredVariables(variableDefs.value, { ...values })
)

function isMissing(name: string): boolean {
  const def = variableDefs.value.find((d) => d.name === name)
  if (!def) return false
  const value = values[name]
  const hasValue = value !== undefined && value.trim() !== ''
  const hasDefault = def.defaultValue !== undefined && def.defaultValue !== ''
  return def.required && !hasValue && !hasDefault
}

// ---------- 模板内容 token 化（高亮变量） ----------
const contentTokens = computed(() => {
  const tokens: Array<{ type: 'text' | 'var'; display: string }> = []
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  let last = 0
  let m: RegExpExecArray | null
  const source = props.content ?? ''
  while ((m = re.exec(source)) !== null) {
    if (m.index > last) tokens.push({ type: 'text', display: source.slice(last, m.index) })
    // 变量占位符：完整显示为 {{name}}
    tokens.push({ type: 'var', display: `{{${m[1]}}}` })
    last = m.index + m[0].length
  }
  if (last < source.length) tokens.push({ type: 'text', display: source.slice(last) })
  return tokens
})

// ---------- 复制 ----------
const copied = ref(false)
const copyDisabled = computed(() => missingRequired.value.length > 0)

let copyTimer: ReturnType<typeof setTimeout> | null = null

async function handleCopy() {
  if (copyDisabled.value) return
  const text = renderedText.value
  if (text === null) return

  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 剪贴板 API 不可用时的降级方案（兼容 Tauri 桌面环境）
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }

  copied.value = true
  emit('copy', { values: { ...values }, text })
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copied.value = false
  }, 2000)
}

defineExpose({ copied })

// ---------- 关闭 ----------
function close() {
  emit('update:open', false)
  emit('close')
}

// ---------- 输入提示 ----------
function inputPlaceholder(def: VariableDef): string {
  if (def.defaultValue) return `请输入（默认：${def.defaultValue}）`
  return def.description || '请输入'
}
</script>

<style scoped>
.preview-section {
  margin-bottom: 20px;
}

.preview-section__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-bottom: 8px;
}

/* 模板内容预览 */
.content-preview {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 160px;
  overflow-y: auto;
}

.content-preview__var {
  color: var(--color-primary);
  background: var(--color-primary-light);
  border-radius: var(--radius-sm);
  padding: 0 4px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
}

/* 变量填写 */
.var-form {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.var-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.var-row__label {
  flex: 0 0 96px;
  font-size: 13px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: var(--color-text-primary);
}

.var-row__required {
  color: var(--color-error);
  margin-left: 2px;
}

.var-row__input {
  flex: 1;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 14px;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  transition: border-color 150ms ease;
}

.var-row__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.var-row--error .var-row__input {
  border-color: var(--color-error);
  background: var(--color-error-light);
}

.var-row__default {
  flex: 0 0 72px;
  text-align: right;
  font-size: 12px;
  color: var(--color-text-muted);
}

.var-warning {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  background: var(--color-warning-light);
  color: #92400e;
  border: 1px solid #fde68a;
  border-radius: var(--radius-md);
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 10px;
}

[data-theme='dark'] .var-warning {
  color: #fbbf24;
}

.var-warning__icon {
  margin-right: 4px;
}

.var-empty {
  font-size: 13px;
  color: var(--color-text-muted);
  margin: 0;
}

/* 渲染结果预览 */
.render-preview {
  min-height: 200px;
  max-height: 320px;
  overflow-y: auto;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
}

.render-preview__text {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
}

.render-preview__note {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.render-preview__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 188px;
  font-size: 13px;
  color: var(--color-text-muted);
}

/* 底部操作：复制在左、关闭在右 */
.dialog-actions {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.btn--success {
  background: var(--color-success-light);
  color: var(--color-success);
  border-color: var(--color-success);
}
</style>
