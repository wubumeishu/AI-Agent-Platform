<template>
  <form @submit.prevent="handleSubmit" class="trigger-form">
    <!-- 名称 -->
    <div class="form-group">
      <label class="form-label">触发器名称</label>
      <input
        v-model.trim="form.name"
        class="form-input"
        placeholder="例如：新消息自动跟进"
        :maxlength="200"
      />
    </div>

    <!-- 类型 -->
    <div class="form-group">
      <label class="form-label">触发类型 *</label>
      <div class="type-grid">
        <label
          v-for="opt in TRIGGER_TYPE_OPTIONS"
          :key="opt.value"
          class="type-card"
          :class="{ 'type-card--active': form.trigger_type === opt.value }"
        >
          <input
            type="radio"
            class="type-card__radio"
            :value="opt.value"
            v-model="form.trigger_type"
          />
          <div class="type-card__body">
            <div class="type-card__title">{{ opt.title }}</div>
            <div class="type-card__desc">{{ opt.desc }}</div>
          </div>
        </label>
      </div>
    </div>

    <!-- Cron 表达式（仅 cron 类型） -->
    <div v-if="form.trigger_type === 'cron'" class="form-group">
      <label class="form-label">Cron 表达式 *</label>
      <div class="cron-row">
        <input
          v-model.trim="cronExpr"
          class="form-input code-input"
          :class="{ 'input-invalid': cronError && cronTouched }"
          placeholder="* * * * *"
          @input="cronTouched = true"
        />
      </div>
      <div class="cron-presets">
        <button
          v-for="p in CRON_PRESETS"
          :key="p.expression"
          type="button"
          class="cron-preset"
          :class="{ 'cron-preset--active': cronExpr === p.expression }"
          @click="cronExpr = p.expression; cronTouched = false"
        >
          {{ p.label }}
        </button>
      </div>
      <div v-if="cronError && cronTouched" class="field-error">
        {{ cronError }}
      </div>
      <div v-else-if="cronDesc" class="field-hint">{{ cronDesc }}</div>
      <div v-if="!cronError" class="field-hint field-hint--muted">
        格式：分 时 日 月 周，例如 <code>0 9 * * 1</code> 表示每周一 09:00
      </div>
    </div>

    <!-- 单次定时（scheduled 类型） -->
    <div v-if="form.trigger_type === 'scheduled'" class="form-group">
      <label class="form-label">执行时间 *</label>
      <input
        v-model="runAt"
        type="datetime-local"
        class="form-input"
        :min="nowLocalInput"
      />
      <div class="field-hint">只执行一次的时间点（本地时间）</div>
    </div>

    <!-- 事件（event 类型） -->
    <div v-if="form.trigger_type === 'event'" class="form-group">
      <label class="form-label">事件名称 *</label>
      <input
        v-model.trim="eventName"
        class="form-input code-input"
        placeholder="message.created"
      />
      <div class="event-presets">
        <button
          v-for="ev in EVENT_PRESETS"
          :key="ev"
          type="button"
          class="cron-preset"
          :class="{ 'cron-preset--active': eventName === ev }"
          @click="eventName = ev"
        >
          {{ ev }}
        </button>
      </div>
      <div class="field-hint">匹配域事件时触发，例如新消息、新意图等</div>
    </div>

    <!-- 手动（manual 类型） -->
    <div v-if="form.trigger_type === 'manual'" class="form-group">
      <div class="manual-note">
        手动触发器不需要周期或事件配置，可通过
        <code>POST /workflows/{id}/triggers/fire</code>
        或动作面板手动触发。
      </div>
    </div>

    <!-- 启用开关 -->
    <div class="form-group">
      <label class="toggle-row">
        <input type="checkbox" v-model="form.enabled" class="toggle-row__box" />
        <span class="toggle-row__text">
          {{ form.enabled ? '创建后立即启用' : '创建后保持禁用' }}
        </span>
      </label>
    </div>

    <!-- 触发条件配置 -->
    <div class="form-group">
      <div class="cond-header">
        <label class="form-label form-label--inline">触发条件</label>
        <button
          type="button"
          class="btn btn--ghost btn--sm"
          @click="addConditionRow"
        >
          + 添加条件
        </button>
      </div>
      <p v-if="conditionRows.length === 0" class="field-hint">
        不添加条件时，触发即执行。添加条件后需满足表达式才继续。
      </p>
      <div
        v-for="(row, i) in conditionRows"
        :key="row.key"
        class="cond-row"
      >
        <div class="cond-row__line1">
          <input
            v-model.trim="row.name"
            class="form-input cond-row__name"
            placeholder="条件名称（可选）"
            :maxlength="200"
          />
          <select v-model="row.logic" class="form-select cond-row__logic">
            <option value="and">AND（与）</option>
            <option value="or">OR（或）</option>
          </select>
          <button
            type="button"
            class="cond-row__remove"
            title="删除条件"
            @click="removeConditionRow(i)"
          >
            ×
          </button>
        </div>
        <div class="cond-row__line2">
          <input
            v-model.trim="row.field"
            class="form-input cond-row__field code-input"
            placeholder="字段，如 customer.total_orders"
          />
          <select v-model="row.operator" class="form-select cond-row__op">
            <option v-for="op in CONDITION_OPERATORS" :key="op" :value="op">
              {{ operatorLabel(op) }}
            </option>
          </select>
          <input
            v-model.trim="row.value"
            class="form-input cond-row__value code-input"
            :placeholder="valuePlaceholder(row.operator)"
          />
        </div>
      </div>
    </div>

    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        @click="$emit('cancel')"
      >
        取消
      </button>
      <button
        type="submit"
        class="btn btn--primary"
        :disabled="submitting || !canSubmit"
      >
        {{ submitting ? (editing ? '保存中...' : '创建中...') : (editing ? '保存' : '创建') }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import ModalFooter from '../common/ModalFooter.vue'
import type {
  WorkflowTrigger,
  TriggerType,
  ConditionLogic,
  ConditionOperator,
  CreateConditionRequest,
} from '@/api/types'
import {
  validateCron,
  describeCron,
  CRON_PRESETS,
} from '@/utils/cron'

// ---- 常量 ----
const nowLocalInput = (() => {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
})()

const TRIGGER_TYPE_OPTIONS: Array<{
  value: TriggerType
  title: string
  desc: string
}> = [
  { value: 'cron', title: '周期 Cron', desc: '按 5 段 Cron 表达式周期执行' },
  { value: 'scheduled', title: '单次定时', desc: '在指定时间点执行一次' },
  { value: 'event', title: '事件触发', desc: '匹配域事件（消息/意图）' },
  { value: 'manual', title: '手动触发', desc: '按需手动 / 接口触发' },
]

const CONDITION_OPERATORS: ConditionOperator[] = [
  'eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'in', 'not_in', 'contains', 'regex',
]
const OPERATOR_LABELS: Record<ConditionOperator, string> = {
  eq: '=', neq: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤',
  in: '属于', not_in: '不属于', contains: '包含', regex: '正则匹配',
}
function operatorLabel(op: ConditionOperator) {
  return `${OPERATOR_LABELS[op]} (${op})`
}
function valuePlaceholder(op: ConditionOperator) {
  if (op === 'in' || op === 'not_in') return '值列表，如 1,2,3'
  if (op === 'regex') return '正则表达式'
  return '值'
}

const EVENT_PRESETS = [
  'message.created',
  'conversation.created',
  'intent.resolved',
  'agent.updated',
]

// ---- Props / Emits ----
const props = defineProps<{
  editing: WorkflowTrigger | null
  /** 编辑时回填的条件列表（来自 triggerStore.conditionsOf） */
  conditions?: Array<{
    id: string
    name?: string
    logic: ConditionLogic
    priority: number
    expression: Record<string, unknown>
  }>
  submitting?: boolean
}>()

const emit = defineEmits<{
  (
    e: 'submit',
    payload: {
      trigger: {
        name?: string
        trigger_type: TriggerType
        spec: Record<string, unknown>
        enabled?: boolean
      }
      conditions: CreateConditionRequest[]
    }
  ): void
  (e: 'cancel'): void
}>()

// ---- 表单状态 ----
const form = reactive<{
  name: string
  trigger_type: TriggerType
  enabled: boolean
}>({
  name: '',
  trigger_type: 'cron',
  enabled: true,
})

const cronExpr = ref('0 9 * * *')
const runAt = ref('')
const eventName = ref('message.created')
const cronTouched = ref(false)

interface ConditionRow {
  key: number
  name: string
  logic: ConditionLogic
  field: string
  operator: ConditionOperator
  value: string
}
const conditionRows = ref<ConditionRow[]>([])
let condKey = 0

function addConditionRow() {
  conditionRows.value.push({
    key: ++condKey,
    name: '',
    logic: conditionRows.value.length === 0 ? 'and' : 'and',
    field: '',
    operator: 'eq',
    value: '',
  })
}

function removeConditionRow(index: number) {
  conditionRows.value.splice(index, 1)
}

// ---- 编辑模式回填 ----
watch(
  () => props.editing,
  (t) => {
    if (!t) {
      form.name = ''
      form.trigger_type = 'cron'
      form.enabled = true
      cronExpr.value = '0 9 * * *'
      cronTouched.value = false
      runAt.value = ''
      eventName.value = 'message.created'
      conditionRows.value = []
      return
    }
    form.name = t.name ?? ''
    form.trigger_type = t.trigger_type
    form.enabled = t.enabled
    const spec = (t.spec ?? {}) as Record<string, unknown>
    if (t.trigger_type === 'cron') cronExpr.value = String(spec.cron ?? '0 9 * * *')
    if (t.trigger_type === 'scheduled' && spec.run_at) {
      runAt.value = toLocalInput(String(spec.run_at))
    }
    if (t.trigger_type === 'event') eventName.value = String(spec.event ?? '')
    backfillConditions()
  },
  { immediate: true }
)

// 条件列表变化时（编辑已打开的情况下刷新）也同步回填
watch(
  () => props.conditions,
  () => {
    if (props.editing) backfillConditions()
  }
)

function toLocalInput(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
    return d.toISOString().slice(0, 16)
  } catch {
    return ''
  }
}

function backfillConditions() {
  const list = props.conditions ?? []
  conditionRows.value = list.map((c) => {
    const expr = c.expression ?? {}
    const rawOp = expr.operator as ConditionOperator | undefined
    let val: unknown = expr.value
    if (Array.isArray(val)) val = val.join(',')
    return {
      key: ++condKey,
      name: c.name ?? '',
      logic: c.logic === 'or' ? ('or' as ConditionLogic) : ('and' as ConditionLogic),
      field: expr.field != null ? String(expr.field) : '',
      operator:
        rawOp != null && (CONDITION_OPERATORS as string[]).includes(rawOp)
          ? rawOp
          : ('eq' as ConditionOperator),
      value: val === undefined || val === null ? '' : String(val),
    }
  })
}

// ---- 校验 ----
const cronError = computed(() => {
  if (form.trigger_type !== 'cron') return ''
  const res = validateCron(cronExpr.value)
  return res.valid ? '' : res.error ?? '无效表达式'
})

const cronDesc = computed(() => {
  if (form.trigger_type !== 'cron' || !cronExpr.value.trim()) return ''
  return describeCron(cronExpr.value)
})

const canSubmit = computed(() => {
  switch (form.trigger_type) {
    case 'cron':
      return !cronError.value
    case 'scheduled':
      return runAt.value !== ''
    case 'event':
      return eventName.value.trim() !== ''
    case 'manual':
    default:
      return true
  }
})

// ---- 提交：构造 spec + 条件请求体 ----
function buildSpec(): Record<string, unknown> {
  switch (form.trigger_type) {
    case 'cron':
      return { cron: cronExpr.value.trim() }
    case 'scheduled':
      return { run_at: new Date(runAt.value).toISOString() }
    case 'event':
      return { event: eventName.value.trim() }
    case 'manual':
    default:
      return {}
  }
}

function buildConditions(): CreateConditionRequest[] {
  return conditionRows.value
    .filter((r) => r.field.trim() !== '' || r.name.trim() !== '')
    .map((r, i) => {
      const expression: Record<string, unknown> = {}
      if (r.field.trim()) expression.field = r.field.trim()
      if (r.operator !== 'eq' || r.value.trim() !== '') {
        expression.operator = r.operator
        // 数值自动转 number
        const raw = r.value.trim()
        if (
          (r.operator === 'in' || r.operator === 'not_in') &&
          raw.includes(',')
        ) {
          expression.value = raw
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        } else if (
          raw !== '' &&
          (r.operator === 'gt' ||
            r.operator === 'gte' ||
            r.operator === 'lt' ||
            r.operator === 'lte')
        ) {
          const num = Number(raw)
          expression.value = Number.isNaN(num) ? raw : num
        } else if (raw !== '') {
          expression.value = raw
        }
      }
      return {
        name: r.name.trim() || undefined,
        logic: r.logic,
        priority: i,
        expression,
      }
    })
}

function handleSubmit() {
  if (!canSubmit.value) return
  emit('submit', {
    trigger: {
      name: form.name.trim() || undefined,
      trigger_type: form.trigger_type,
      spec: buildSpec(),
      enabled: form.enabled,
    },
    conditions: buildConditions(),
  })
}
</script>

<style scoped>
.trigger-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-group {
  margin-bottom: 4px;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.form-label--inline {
  margin-bottom: 0;
}

.form-input,
.form-select {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  transition: border-color 150ms ease;
}

.form-input:focus,
.form-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.input-invalid {
  border-color: var(--color-error);
}

.code-input {
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 13px;
}

/* ---- 类型选择卡片 ---- */
.type-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.type-card {
  position: relative;
  display: block;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
  padding: 10px 12px;
  cursor: pointer;
  transition:
    border-color 120ms ease,
    background 120ms ease;
}

.type-card__radio {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.type-card:hover {
  border-color: var(--color-primary);
}

.type-card--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.type-card__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.type-card__desc {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

/* ---- 预设 / 提示 ---- */
.cron-presets,
.event-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.cron-preset {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full, 999px);
  background: var(--color-bg-primary);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    border-color 120ms ease,
    color 120ms ease,
    background 120ms ease;
}

.cron-preset:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.cron-preset--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.field-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.field-hint--muted {
  color: var(--color-text-muted);
}

.field-error {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-error);
}

.manual-note {
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md, 8px);
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.manual-note code {
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 11px;
  background: var(--color-bg-primary);
  padding: 1px 4px;
  border-radius: 4px;
}

/* ---- 启用开关 ---- */
.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.toggle-row__box {
  width: 16px;
  height: 16px;
  accent-color: var(--color-primary);
}

.toggle-row__text {
  font-size: 13px;
  color: var(--color-text-primary);
}

/* ---- 条件行 ---- */
.cond-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.cond-row {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
  background: var(--color-bg-secondary);
}

.cond-row__line1 {
  display: flex;
  gap: 8px;
  align-items: center;
}

.cond-row__line2 {
  display: flex;
  gap: 8px;
  align-items: center;
}

.cond-row__name {
  flex: 2;
}

.cond-row__logic {
  flex: 0 0 130px;
}

.cond-row__remove {
  flex: 0 0 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-size: 16px;
  cursor: pointer;
  border-radius: 4px;
}

.cond-row__remove:hover {
  background: var(--color-error-light);
  color: var(--color-error);
}

.cond-row__field {
  flex: 1.4;
}

.cond-row__op {
  flex: 0 0 150px;
}

.cond-row__value {
  flex: 1;
}

@media (max-width: 640px) {
  .type-grid {
    grid-template-columns: 1fr;
  }

  .cond-row__line1,
  .cond-row__line2 {
    flex-direction: column;
    align-items: stretch;
  }

  .cond-row__name,
  .cond-row__logic,
  .cond-row__field,
  .cond-row__op,
  .cond-row__value {
    flex: 1 1 100%;
  }

  .cond-row__remove {
    align-self: flex-end;
  }
}
</style>
