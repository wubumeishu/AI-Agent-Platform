/**
 * Prompt 变量渲染逻辑 (P1-002-H)
 *
 * 从模板内容中提取 {{variable}} 变量占位符，
 * 并根据变量定义（必填校验 / 默认值）渲染最终文本。
 *
 * 设计约定：
 * - 变量名大小写敏感
 * - 嵌套变量暂不支持（V2 规划）
 * - 必填变量缺失时不渲染结果，返回缺失名单供 UI 提示
 */
import type { VariableDef, PromptVariableValues } from '@/api/types'

/** 提取模板内容中出现的 {{variable}} 占位符名称（去重、保持出现顺序） */
export function extractTemplateVariables(content: string): string[] {
  if (!content) return []
  const seen = new Set<string>()
  const names: string[] = []
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  let match: RegExpExecArray | null
  while ((match = re.exec(content)) !== null) {
    const name = match[1]
    if (!name || seen.has(name)) continue
    seen.add(name)
    names.push(name)
  }
  return names
}

/** 合并变量定义：模板声明的 variables + 内容中实际出现的占位符（内容优先） */
export function collectVariableDefs(
  content: string,
  declared: VariableDef[] = []
): VariableDef[] {
  const found = extractTemplateVariables(content)
  const map = new Map<string, VariableDef>()
  // 先放声明定义
  for (const def of declared) {
    map.set(def.name, def)
  }
  // 内容中出现的变量：未声明的默认非必填
  for (const name of found) {
    const existing = map.get(name)
    map.set(name, existing ?? { name, description: '', required: false })
  }
  // 按内容出现顺序排列（内容中未出现的声明变量放后面）
  const order = [...found, ...[...map.keys()].filter((n) => !found.includes(n))]
  return order.map((n) => map.get(n)!)
}

export interface RenderResult {
  /** 渲染后的完整文本（校验失败时为 null） */
  rendered: string | null
  /** 未填的必填变量名 */
  missingRequired: string[]
  /** 使用了默认值的变量名 */
  usedDefaults: string[]
  /** 模板中未被提供值也非必填的变量（保留原占位符） */
  unfilledOptional: string[]
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * 渲染模板：用变量值替换 {{name}} 占位符。
 *
 * - 必填变量缺失 → rendered 为 null，missingRequired 列出缺失项
 * - 可选变量未填且无默认值 → 保留原始 {{name}} 占位符，并记入 unfilledOptional
 * - 变量值在渲染前做 HTML 转义（AC-06 防 XSS）
 * - 未知占位符（不在收集定义中）保留原样
 */
export function renderPromptTemplate(
  content: string,
  defs: VariableDef[],
  values: PromptVariableValues
): RenderResult {
  const missingRequired: string[] = []
  const usedDefaults: string[] = []

  for (const def of defs) {
    const provided = values[def.name]
    if (provided !== undefined && provided !== '') {
      continue
    }
    if (def.defaultValue !== undefined && def.defaultValue !== '') {
      if (values[def.name] !== def.defaultValue) usedDefaults.push(def.name)
      continue
    }
    if (def.required) {
      missingRequired.push(def.name)
    }
  }

  if (missingRequired.length > 0) {
    return { rendered: null, missingRequired, usedDefaults, unfilledOptional: [] }
  }

  let rendered = content
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  rendered = rendered.replace(re, (original, name: string) => {
    const value = values[name]
    if (value !== undefined && value !== '') {
      return escapeHtml(value)
    }
    const def = defs.find((d) => d.name === name)
    if (def?.defaultValue !== undefined && def.defaultValue !== '') {
      return escapeHtml(def.defaultValue)
    }
    // 未填的非必填变量：保留占位符
    return original
  })

  // 找出模板中保留下来的占位符（非必填且无默认值且未填写）
  const unfilledOptional = extractTemplateVariables(rendered).filter((n) => {
    const def = defs.find((d) => d.name === n)
    return def !== undefined && !def.required && !(def.defaultValue && def.defaultValue !== '')
  })

  return { rendered, missingRequired: [], usedDefaults, unfilledOptional }
}

/** 校验必填变量是否齐全，返回缺失名单（UI 提示用） */
export function validateRequiredVariables(
  defs: VariableDef[],
  values: PromptVariableValues
): string[] {
  const missing: string[] = []
  for (const def of defs) {
    if (!def.required) continue
    const value = values[def.name]
    const hasValue = value !== undefined && value !== ''
    const hasDefault = def.defaultValue !== undefined && def.defaultValue !== ''
    if (!hasValue && !hasDefault) {
      missing.push(def.name)
    }
  }
  return missing
}
