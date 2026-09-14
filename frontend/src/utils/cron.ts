/**
 * Cron 表达式工具（5 段标准 cron: 分 时 日 月 周）。
 * 纯前端校验 + 预设 + 可读描述；不依赖第三方库。
 */

const MONTH_NAMES: Record<string, number> = {
  JAN: 1, FEB: 2, MAR: 3, APR: 4, MAY: 5, JUN: 6,
  JUL: 7, AUG: 8, SEP: 9, OCT: 10, NOV: 11, DEC: 12,
}
const DOW_NAMES: Record<string, number> = {
  SUN: 0, MON: 1, TUE: 2, WED: 3, THU: 4, FRI: 5, SAT: 6,
}

const MIN = { min: 0, max: 59 }
const HOUR = { min: 0, max: 23 }
const DOM = { min: 1, max: 31 }
const MONTH = { min: 1, max: 12 }
const DOW = { min: 0, max: 7 } // 0 和 7 都表示周日

const FIELDS = [
  { key: 'minute', label: '分', range: MIN },
  { key: 'hour', label: '时', range: HOUR },
  { key: 'dom', label: '日', range: DOM },
  { key: 'month', label: '月', range: MONTH },
  { key: 'dow', label: '周', range: DOW },
] as const

function resolveName(token: string, names: Record<string, number>): number | null {
  return names[token.toUpperCase()] ?? null
}

function checkValue(v: number, range: { min: number; max: number }): boolean {
  return v >= range.min && v <= range.max
}

/** 解析单个 cron 值项（数字或名称），返回 0..1000 合法数字或 null */
function parseValue(
  raw: string,
  range: { min: number; max: number },
  names?: Record<string, number>
): number | null {
  if (!/^\d+$/.test(raw)) {
    const named = names ? resolveName(raw, names) : null
    if (named === null) return null
    return checkValue(named, range) ? named : null
  }
  const num = Number(raw)
  return checkValue(num, range) ? num : null
}

/** 校验单段（支持星号、单值、区间、步进取值、逗号列表、名称） */
function validateField(
  field: string,
  range: { min: number; max: number },
  names?: Record<string, number>
): string | null {
  const trimmed = field.trim()
  if (trimmed === '') return '不能为空'

  // 逗号分隔的多个部分
  for (const part of trimmed.split(',')) {
    const p = part.trim()
    if (p === '*') continue
    if (p === '?') continue // 兼容日/周段的部分方言
    // 步进: */n 或 a-b/n
    let body = p
    let hasStep = false
    const stepIdx = p.lastIndexOf('/')
    if (stepIdx !== -1) {
      hasStep = true
      body = p.slice(0, stepIdx)
      const stepStr = p.slice(stepIdx + 1)
      if (!/^\d+$/.test(stepStr) || Number(stepStr) === 0) {
        return `步进值无效: "${p}"`
      }
    }
    if (body === '*') {
      if (hasStep && range.max - range.min < 1) return `该段不支持步进`
      continue
    }
    // 范围 a-b
    const rangeMatch = body.match(/^(.+)-(.+)$/)
    if (rangeMatch) {
      const startTok = rangeMatch[1]?.trim() ?? ''
      const endTok = rangeMatch[2]?.trim() ?? ''
      const start = parseValue(startTok, range, names)
      const end = parseValue(endTok, range, names)
      if (start === null || end === null) {
        return `取值超出范围 (${range.min}-${range.max}): "${p}"`
      }
      if (start > end) return `范围起止颠倒: "${p}"`
      continue
    }
    // 单值
    if (hasStep) {
      // 单值带步进（如 5/10）：部分方言允许，等价于 5-max/10
      if (parseValue(body, range, names) === null) {
        return `取值超出范围 (${range.min}-${range.max}): "${p}"`
      }
      continue
    }
    if (parseValue(body, range, names) === null) {
      return `取值超出范围 (${range.min}-${range.max}): "${p}"`
    }
  }
  return null
}

export interface CronValidationResult {
  valid: boolean
  error?: string
  /** 规范化为 5 段（若输入是 6 段含秒则取后 5 段并在 error 提示） */
  normalized?: string
}

/**
 * 校验 5 段标准 cron 表达式。
 * 宽容处理：自动 trim；6 段（含秒）视为无效并提示。
 */
export function validateCron(expression: string): CronValidationResult {
  const raw = expression.trim()
  if (raw === '') {
    return { valid: false, error: 'Cron 表达式不能为空' }
  }
  const parts = raw.split(/\s+/)
  if (parts.length === 6) {
    // 允许 "秒 分 时 日 月 周" 方言：取后 5 段
    const five = parts.slice(1).join(' ')
    const check = validateCronParts(five.split(' '))
    if (!check.valid) return check
    return { valid: true, normalized: five, error: undefined }
  }
  if (parts.length < 5) {
    return {
      valid: false,
      error: `需要 5 段（分 时 日 月 周），当前 ${parts.length} 段`,
    }
  }
  if (parts.length > 5) {
    return { valid: false, error: `段数过多（${parts.length}），标准 cron 为 5 段` }
  }
  return checkFiveParts(parts)
}

function validateCronParts(parts: string[]): CronValidationResult {
  const namesPerField: Array<Record<string, number> | undefined> = [
    undefined,
    undefined,
    undefined,
    MONTH_NAMES,
    DOW_NAMES,
  ]
  for (let i = 0; i < 5; i++) {
    const part = parts[i]
    const field = FIELDS[i]
    if (!part || !field) {
      return { valid: false, error: `缺少第 ${i + 1} 段` }
    }
    const err = validateField(part, field.range, namesPerField[i])
    if (err) {
      return { valid: false, error: `${field.label}段无效: ${err}` }
    }
  }
  // 日/周 互斥约束：标准 cron 中若两者都非 * 则语义模糊，允许但提示
  return { valid: true, normalized: parts.join(' ') }
}

function checkFiveParts(parts: string[]): CronValidationResult {
  return validateCronParts(parts)
}

const DOW_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/** 生成人类可读描述（尽力而为，复杂表达式回退到原文） */
export function describeCron(expression: string): string {
  const res = validateCron(expression)
  if (!res.valid) return '无效表达式'
  const parts = (res.normalized ?? expression).trim().split(/\s+/)
  const minF = parts[0] ?? '*'
  const hourF = parts[1] ?? '*'
  const domF = parts[2] ?? '*'
  const monF = parts[3] ?? '*'
  const dowF = parts[4] ?? '*'

  const isAll = (v: string) => v === '*'
  const pad = (v: string) => (v.length === 1 ? `0${v}` : v)

  // ---- 纯时间周期（日/月/周 全为 *） ----
  if (isAll(domF) && isAll(monF) && isAll(dowF)) {
    if (isAll(minF) && isAll(hourF)) return '每分钟执行'
    if (minF.startsWith('*/') && isAll(hourF)) return `每 ${minF.slice(2)} 分钟执行`
    if (isAll(minF)) return '每小时执行'
    if (isAll(hourF)) return `每天 ${pad(minF)} 分执行`
    return `每天 ${pad(hourF)}:${pad(minF)} 执行`
  }

  // ---- 周期性（含 周 或 日/月 限定，且分钟/小时为固定值） ----
  const simple = (v: string) => /^\d+$/.test(v)
  const atTime =
    simple(hourF) || isAll(hourF)
      ? `${pad(isAll(hourF) ? '0' : hourF)}:${pad(minF)}`
      : ''
  const dowPart = !isAll(dowF) && isAll(domF)
    ? (() => {
        const m = dowF.match(/^(\d+)$/i)
        if (m) return DOW_LABELS[Number(m[1]) % 7] ?? dowF
        return dowF // 如 MON-FRI
      })()
    : ''
  const domPart = !isAll(domF) && isAll(dowF) ? `${domF} 日` : ''
  const monPart = isAll(monF) ? '' : `${monF} 月`

  const prefix: string[] = []
  if (monPart) prefix.push(monPart)
  if (domPart) prefix.push(domPart)
  if (dowPart) prefix.push(`每${dowPart}`)

  const head = prefix.length > 0 ? prefix.join(' ') + ' ' : '每'
  return `${head}${atTime ? `${atTime} ` : ''}执行`
}

export interface CronPreset {
  label: string
  expression: string
}

export const CRON_PRESETS: CronPreset[] = [
  { label: '每分钟', expression: '* * * * *' },
  { label: '每 5 分钟', expression: '*/5 * * * *' },
  { label: '每小时', expression: '0 * * * *' },
  { label: '每天 09:00', expression: '0 9 * * *' },
  { label: '每天 09:30', expression: '30 9 * * *' },
  { label: '每周一 09:00', expression: '0 9 * * 1' },
  { label: '每月 1 日 00:00', expression: '0 0 1 * *' },
]

/** 预设匹配检查：用于在输入框旁高亮匹配的预设 */
export function matchPreset(expression: string): CronPreset | undefined {
  const trimmed = expression.trim()
  return CRON_PRESETS.find((p) => p.expression === trimmed)
}
