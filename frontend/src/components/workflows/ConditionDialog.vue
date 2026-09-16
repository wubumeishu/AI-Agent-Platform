<template>
  <div class="cond-dlg">
    <p v-if="conditions.length === 0" class="cond-dlg__empty">
      当前触发器还没有任何条件。
    </p>

    <!-- 已有条件列表 -->
    <div v-if="conditions.length > 0" class="cond-list">
      <div
        v-for="cond in conditions"
        :key="cond.id"
        class="cond-item"
      >
        <div class="cond-item__top">
          <span class="cond-item__logic">{{ cond.logic === 'or' ? 'OR' : 'AND' }}</span>
          <code class="cond-item__expr">{{ condExpressionText(cond) }}</code>
          <button
            class="btn btn--ghost btn--sm"
            @click="openEdit(cond)"
          >
            编辑
          </button>
          <button
            class="btn btn--danger btn--sm"
            :disabled="busy"
            @click="emit('delete-condition', cond)"
          >
            删除
          </button>
        </div>
        <div v-if="cond.name" class="cond-item__name">{{ cond.name }}</div>
      </div>
    </div>

    <div class="cond-dlg__divider"></div>

    <!-- 新建 / 编辑条件表单 -->
    <div class="cond-form">
      <h4 class="cond-form__title">{{ editingCond ? '编辑条件' : '新建条件' }}</h4>

      <div class="form-group">
        <label class="form-label">条件名称（可选）</label>
        <input
          v-model.trim="draft.name"
          class="form-input"
          :maxlength="200"
          placeholder="例如：高价值客户"
        />
      </div>

      <div class="form-group">
        <label class="form-label">逻辑关系</label>
        <select v-model="draft.logic" class="form-select">
          <option value="and">AND（与）</option>
          <option value="or">OR（或）</option>
        </select>
      </div>

      <div class="form-group">
        <div class="cond-fields">
          <input
            v-model.trim="draft.field"
            class="form-input cond-field code-input"
            placeholder="字段，如 customer.total_orders"
          />
          <select v-model="draft.operator" class="form-select cond-op">
            <option v-for="op in CONDITION_OPERATORS" :key="op" :value="op">
              {{ operatorLabel(op) }}
            </option>
          </select>
          <input
            v-model.trim="draft.value"
            class="form-input cond-value code-input"
            :placeholder="valuePlaceholder(draft.operator)"
          />
        </div>
        <div class="field-hint">
          表达式形如 <code>{{ draft.field || 'field' }} {{ draft.operator }} {{ draft.value || 'value' }}</code>
        </div>
      </div>

      <ModalFooter>
        <button
          v-if="editingCond"
          type="button"
          class="btn btn--ghost"
          @click="resetDraft()"
        >
          取消编辑
        </button>
        <button
          type="button"
          class="btn btn--primary"
          :disabled="busy || !canSave"
          @click="saveDraft"
        >
          {{ editingCond ? '保存条件' : '添加条件' }}
        </button>
      </ModalFooter>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import ModalFooter from '../common/ModalFooter.vue'
import type {
  WorkflowCondition,
  ConditionLogic,
  ConditionOperator,
  CreateConditionRequest,
  UpdateConditionRequest,
} from '@/api/types'

const props = defineProps<{
  conditions: WorkflowCondition[]
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'create-condition', data: CreateConditionRequest): void
  (e: 'update-condition', conditionId: string, data: UpdateConditionRequest): void
  (e: 'delete-condition', condition: WorkflowCondition): void
}>()

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

function isKnownOperator(op: ConditionOperator | undefined): op is ConditionOperator {
  return op != null && (CONDITION_OPERATORS as string[]).includes(op)
}

const editingCond = ref<WorkflowCondition | null>(null)

const draft = reactive({
  name: '',
  logic: 'and' as ConditionLogic,
  field: '',
  operator: 'eq' as ConditionOperator,
  value: '',
})

function resetDraft() {
  editingCond.value = null
  draft.name = ''
  draft.logic = 'and'
  draft.field = ''
  draft.operator = 'eq'
  draft.value = ''
}

function openEdit(cond: WorkflowCondition) {
  editingCond.value = cond
  draft.name = cond.name ?? ''
  draft.logic = cond.logic === 'or' ? 'or' : 'and'
  const expr = cond.expression ?? {}
  draft.field = expr.field != null ? String(expr.field) : ''
  const op = expr.operator as ConditionOperator | undefined
  draft.operator = op && isKnownOperator(op) ? op : 'eq'
  let val: unknown = expr.value
  if (Array.isArray(val)) val = val.join(',')
  draft.value = val == null ? '' : String(val)
}

const canSave = computed(
  () => draft.field.trim() !== '' && (draft.operator !== 'eq' || draft.value.trim() !== '')
)

function buildExpression(): Record<string, unknown> {
  const expression: Record<string, unknown> = {}
  if (draft.field.trim()) expression.field = draft.field.trim()
  if (draft.operator !== 'eq' || draft.value.trim() !== '') {
    expression.operator = draft.operator
    const raw = draft.value.trim()
    if ((draft.operator === 'in' || draft.operator === 'not_in') && raw.includes(',')) {
      expression.value = raw.split(',').map((s) => s.trim()).filter(Boolean)
    } else if (
      raw !== '' &&
      ['gt', 'gte', 'lt', 'lte'].includes(draft.operator)
    ) {
      const num = Number(raw)
      expression.value = Number.isNaN(num) ? raw : num
    } else if (raw !== '') {
      expression.value = raw
    }
  }
  return expression
}

function saveDraft() {
  if (!canSave.value) return
  const body = {
    name: draft.name.trim() || undefined,
    logic: draft.logic,
    expression: buildExpression(),
  }
  if (editingCond.value) {
    const patch: UpdateConditionRequest = {
      name: body.name,
      logic: body.logic,
      expression: body.expression,
    }
    emit('update-condition', editingCond.value.id, patch)
  } else {
    emit('create-condition', body as CreateConditionRequest)
  }
  resetDraft()
}

function condExpressionText(cond: WorkflowCondition): string {
  const expr = cond.expression ?? {}
  const parts: string[] = []
  if (expr.field != null) parts.push(String(expr.field))
  if (expr.operator != null) {
    parts.push(`${expr.operator} ${formatValue(expr.value)}`.trim())
  }
  if (parts.length === 0) return JSON.stringify(expr)
  return parts.join(' ')
}

function formatValue(v: unknown): string {
  if (Array.isArray(v)) return `[${v.join(', ')}]`
  if (v == null) return ''
  return String(v)
}

void props
</script>

<style scoped>
.cond-dlg {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cond-dlg__empty {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.cond-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cond-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
  background: var(--color-bg-secondary);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cond-item__top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.cond-item__logic {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  color: var(--color-primary);
  background: var(--color-primary-light);
  border-radius: 4px;
  padding: 1px 6px;
}

.cond-item__expr {
  flex: 1;
  min-width: 0;
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 12px;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cond-item__name {
  font-size: 11px;
  color: var(--color-text-muted);
}

.cond-item__top .btn {
  margin-left: 0;
  flex-shrink: 0;
}

.cond-dlg__divider {
  height: 1px;
  background: var(--color-border);
}

/* ---- 表单 ---- */
.cond-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cond-form__title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
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

.code-input {
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 13px;
}

.cond-fields {
  display: flex;
  gap: 8px;
  align-items: center;
}

.cond-field {
  flex: 1.4;
}

.cond-op {
  flex: 0 0 150px;
}

.cond-value {
  flex: 1;
}

.field-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.field-hint code {
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 11px;
  background: var(--color-bg-primary);
  padding: 1px 4px;
  border-radius: 4px;
}

@media (max-width: 640px) {
  .cond-fields {
    flex-direction: column;
  }

  .cond-field,
  .cond-op,
  .cond-value {
    flex: 1 1 100%;
  }
}
</style>
