<template>
  <div class="trigger-list">
    <div
      v-for="trigger in triggers"
      :key="trigger.id"
      class="trigger-card"
      :class="{ 'trigger-card--disabled': !trigger.enabled }"
    >
      <!-- 卡片头：名称 + 启用开关 + 操作 -->
      <div class="trigger-card__head">
        <div class="trigger-card__title">
          <span class="trigger-card__name">{{ trigger.name || triggerSummaryLabel(trigger) }}</span>
          <span class="trigger-type-tag">{{ getTriggerTypeLabel(trigger.trigger_type) }}</span>
        </div>
        <div class="trigger-card__tools">
          <label class="switch" :class="{ 'switch--on': trigger.enabled }">
            <input
              type="checkbox"
              role="switch"
              :checked="trigger.enabled"
              :disabled="busyIds.includes(trigger.id)"
              @change="emit('toggle-enabled', trigger)"
            />
            <span class="switch__track"></span>
          </label>
          <button
            class="btn btn--ghost btn--sm"
            :disabled="busyIds.includes(trigger.id)"
            @click="emit('edit', trigger)"
          >
            编辑
          </button>
          <button
            class="btn btn--danger btn--sm"
            :disabled="busyIds.includes(trigger.id)"
            @click="emit('delete', trigger)"
          >
            删除
          </button>
        </div>
      </div>

      <!-- 规格摘要 -->
      <div class="trigger-card__spec">
        {{ triggerSpecSummary(trigger) }}
      </div>

      <!-- 条件 -->
      <div class="trigger-card__conds">
        <div class="trigger-card__conds-head">
          <span>触发条件</span>
          <button
            class="btn btn--ghost btn--sm"
            @click="emit('add-condition', trigger)"
          >
            + 添加条件
          </button>
        </div>
        <template v-if="conditionsOf(trigger.id).length > 0">
          <div
            v-for="cond in conditionsOf(trigger.id)"
            :key="cond.id"
            class="cond-line"
          >
            <span class="cond-line__logic">{{ cond.logic === 'or' ? 'OR' : 'AND' }}</span>
            <span v-if="cond.name" class="cond-line__name">{{ cond.name }}</span>
            <code class="cond-line__expr">{{ condExpressionText(cond) }}</code>
            <!-- 该条件下的动作 -->
            <div v-if="cond.actions && cond.actions.length > 0" class="cond-line__actions">
              <span
                v-for="a in cond.actions"
                :key="a.id"
                class="action-chip"
              >
                {{ getActionTypeLabel(a.action_type) }}{{ a.name ? ' · ' + a.name : '' }}
              </span>
            </div>
            <div v-else class="cond-line__no-actions">
              （尚未配置动作）
            </div>
          </div>
        </template>
        <p v-else class="field-hint">
          无条件 = 触发即执行。点击「添加条件」配置过滤表达式。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type {
  WorkflowTrigger,
  WorkflowCondition,
  TriggerType,
  ActionType,
  ConditionOperator,
} from '@/api/types'
import { describeCron } from '@/utils/cron'

const props = defineProps<{
  triggers: WorkflowTrigger[]
  conditionsOf: (triggerId: string) => WorkflowCondition[]
  busyIds?: string[]
}>()

const emit = defineEmits<{
  (e: 'toggle-enabled', trigger: WorkflowTrigger): void
  (e: 'edit', trigger: WorkflowTrigger): void
  (e: 'delete', trigger: WorkflowTrigger): void
  (e: 'add-condition', trigger: WorkflowTrigger): void
}>()

const busyIds = props.busyIds ?? []

const TRIGGER_TYPE_LABELS: Record<TriggerType, string> = {
  cron: '周期 Cron',
  scheduled: '单次定时',
  event: '事件触发',
  manual: '手动触发',
}

function getTriggerTypeLabel(type: TriggerType) {
  return TRIGGER_TYPE_LABELS[type] ?? type
}

const ACTION_TYPE_LABELS: Record<ActionType, string> = {
  conversation: '对话回复',
  message: '发送消息',
  tag: '打标签',
  status_change: '状态变更',
  notification: '通知',
  custom: '自定义',
}

function getActionTypeLabel(type: ActionType) {
  return ACTION_TYPE_LABELS[type] ?? type
}

function triggerSummaryLabel(trigger: WorkflowTrigger): string {
  return `触发器 #${trigger.id.slice(0, 8)}`
}

function triggerSpecSummary(trigger: WorkflowTrigger): string {
  const spec = (trigger.spec ?? {}) as Record<string, unknown>
  switch (trigger.trigger_type) {
    case 'cron': {
      const cron = String(spec.cron ?? '')
      const desc = cron ? ` · ${describeCron(cron)}` : ''
      return `Cron：${cron || '未配置'}${desc}`
    }
    case 'scheduled':
      return `执行时间：${spec.run_at ? formatTime(String(spec.run_at)) : '未配置'}`
    case 'event':
      return `事件：${String(spec.event ?? '未配置')}`
    case 'manual':
      return '手动 / 接口触发，无需周期配置'
    default:
      return JSON.stringify(spec)
  }
}

function condExpressionText(cond: WorkflowCondition): string {
  const expr = cond.expression ?? {}
  const parts: string[] = []
  if (expr.field != null) parts.push(String(expr.field))
  const op = expr.operator as ConditionOperator | undefined
  if (op) parts.push(`${op} ${formatCondValue(expr.value)}`.trim())
  if (expr.operator == null && expr.field == null) {
    return JSON.stringify(expr)
  }
  return parts.join(' ')
}

function formatCondValue(v: unknown): string {
  if (Array.isArray(v)) return `[${v.join(', ')}]`
  if (v == null) return ''
  return String(v)
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

void props
</script>

<style scoped>
.trigger-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.trigger-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
  background: var(--color-bg-secondary);
  padding: var(--spacing-3);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: opacity 120ms ease;
}

.trigger-card--disabled {
  opacity: 0.65;
}

.trigger-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.trigger-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.trigger-card__name {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trigger-type-tag {
  font-size: 11px;
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full, 999px);
  padding: 2px 8px;
  flex-shrink: 0;
}

.trigger-card__tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.trigger-card__tools .btn {
  margin-left: 0;
}

/* ---- 启用/禁用开关 ---- */
.switch {
  position: relative;
  display: inline-block;
  width: 34px;
  height: 18px;
  flex-shrink: 0;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.switch__track {
  position: absolute;
  inset: 0;
  background: var(--color-border);
  border-radius: var(--radius-full, 999px);
  transition: background 150ms ease;
  cursor: pointer;
}

.switch__track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  transition: transform 150ms ease;
}

.switch--on .switch__track {
  background: var(--color-success);
}

.switch--on .switch__track::after {
  transform: translateX(16px);
}

.switch input:disabled + .switch__track {
  opacity: 0.5;
  cursor: not-allowed;
}

.trigger-card__spec {
  font-size: 13px;
  color: var(--color-text-secondary);
}

/* ---- 条件 ---- */
.trigger-card__conds {
  border-top: 1px dashed var(--color-border);
  padding-top: 8px;
}

.trigger-card__conds-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.cond-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 0;
}

.cond-line__logic {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  color: var(--color-primary);
  background: var(--color-primary-light);
  border-radius: 4px;
  padding: 1px 6px;
}

.cond-line__name {
  flex-shrink: 0;
  color: var(--color-text-secondary);
}

.cond-line__expr {
  font-family: 'SF Mono', Consolas, monospace;
  font-size: 11px;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.cond-line__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  width: 100%;
  margin-top: 2px;
  padding-left: 2px;
}

.action-chip {
  font-size: 11px;
  color: var(--color-text-secondary);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full, 999px);
  padding: 1px 8px;
}

.cond-line__no-actions {
  width: 100%;
  font-size: 11px;
  color: var(--color-text-muted);
  padding-left: 2px;
}

.field-hint {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

@media (max-width: 640px) {
  .trigger-card__head {
    flex-direction: column;
    align-items: flex-start;
  }

  .trigger-card__tools {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
