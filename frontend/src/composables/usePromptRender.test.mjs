// P1-002-H runtime smoke test — plain-JS mirror of usePromptRender.ts logic
// (kept dependency-free so QA can run:  node frontend/src/composables/usePromptRender.test.mjs)
import assert from 'node:assert/strict'

// ---- mirror of extractTemplateVariables ----
function extractTemplateVariables(content) {
  if (!content) return []
  const seen = new Set()
  const names = []
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  let match
  while ((match = re.exec(content)) !== null) {
    const name = match[1]
    if (!name || seen.has(name)) continue
    seen.add(name)
    names.push(name)
  }
  return names
}

// ---- mirror of collectVariableDefs ----
function collectVariableDefs(content, declared = []) {
  const found = extractTemplateVariables(content)
  const map = new Map()
  for (const def of declared) map.set(def.name, def)
  for (const name of found) map.set(name, map.get(name) ?? { name, description: '', required: false })
  const order = [...found, ...[...map.keys()].filter((n) => !found.includes(n))]
  return order.map((n) => map.get(n))
}

// ---- mirror of renderPromptTemplate ----
function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderPromptTemplate(content, defs, values) {
  const missingRequired = []
  const usedDefaults = []
  for (const def of defs) {
    const provided = values[def.name]
    if (provided !== undefined && provided !== '') continue
    if (def.defaultValue !== undefined && def.defaultValue !== '') {
      if (values[def.name] !== def.defaultValue) usedDefaults.push(def.name)
      continue
    }
    if (def.required) missingRequired.push(def.name)
  }
  if (missingRequired.length > 0) {
    return { rendered: null, missingRequired, usedDefaults, unfilledOptional: [] }
  }
  let rendered = content
  const re = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g
  rendered = rendered.replace(re, (original, name) => {
    const value = values[name]
    if (value !== undefined && value !== '') return escapeHtml(value)
    const def = defs.find((d) => d.name === name)
    if (def && def.defaultValue !== undefined && def.defaultValue !== '') return escapeHtml(def.defaultValue)
    return original
  })
  const unfilledOptional = extractTemplateVariables(rendered).filter((n) => {
    const def = defs.find((d) => d.name === n)
    return def && !def.required && !(def.defaultValue && def.defaultValue !== '')
  })
  return { rendered, missingRequired: [], usedDefaults, unfilledOptional }
}

// ---- mirror of validateRequiredVariables ----
function validateRequiredVariables(defs, values) {
  const missing = []
  for (const def of defs) {
    if (!def.required) continue
    const value = values[def.name]
    const hasValue = value !== undefined && value !== ''
    const hasDefault = def.defaultValue !== undefined && def.defaultValue !== ''
    if (!hasValue && !hasDefault) missing.push(def.name)
  }
  return missing
}

// ===== assertions =====
let passed = 0
function ok(name, fn) {
  try {
    fn()
    passed++
    console.log('  PASS  ' + name)
  } catch (e) {
    console.log('  FAIL  ' + name + '\n        ' + e.message)
    process.exitCode = 1
  }
}

const content = `你是一位家谱专家。请为{{user_name}}介绍{{surname}}姓氏的起源。

背景信息：
- 姓氏：{{surname}}
- 用户姓名：{{user_name}}
- 兴趣点：{{interest}}（可选）

请生成一段通俗易懂的介绍，字数在{{word_count}}字以内。`
const vars = [
  { name: 'user_name', description: '用户姓名', required: true },
  { name: 'surname', description: '姓氏', required: true },
  { name: 'interest', description: '兴趣点', required: false, defaultValue: '姓氏起源' },
  { name: 'word_count', description: '字数上限', required: false, defaultValue: '500' },
]

console.log('--- extractTemplateVariables ---')
ok('extracts 4 vars in order', () =>
  assert.deepEqual(extractTemplateVariables(content), ['user_name', 'surname', 'interest', 'word_count']))
ok('dedupes repeats', () => assert.deepEqual(extractTemplateVariables('{{a}}x{{a}}'), ['a']))
ok('empty -> []', () => assert.deepEqual(extractTemplateVariables(''), []))
ok('spaces in braces', () => assert.deepEqual(extractTemplateVariables('{{ user_name }}'), ['user_name']))

console.log('--- collectVariableDefs ---')
ok('merges 4 declared defs', () => assert.equal(collectVariableDefs(content, vars).length, 4))
ok('undeclared placeholder becomes optional', () => {
  const merged = collectVariableDefs('hello {{ghost}}', vars)
  assert.ok(merged.some((d) => d.name === 'ghost' && d.required === false))
})

console.log('--- renderPromptTemplate: success ---')
const okr = renderPromptTemplate(content, vars, { user_name: '张三', surname: '李', word_count: '800' })
ok('rendered not null', () => assert.notEqual(okr.rendered, null))
ok('user_name replaced', () => assert.ok(okr.rendered.includes('为张三介绍')))
ok('surname substituted twice', () => assert.equal(okr.rendered.split('李').length - 1, 2))
ok('default interest applied', () => assert.ok(okr.rendered.includes('兴趣点：姓氏起源（可选）')))
ok('explicit word_count overrides default', () => assert.ok(okr.rendered.includes('字数在800字以内')))
ok('no placeholders remain', () => assert.ok(!/\{\{/.test(okr.rendered)))
ok('usedDefaults flags interest (blank->default) but not word_count (explicit 800)', () => {
  assert.ok(okr.usedDefaults.includes('interest'), 'interest used its default')
  assert.ok(!okr.usedDefaults.includes('word_count'), 'word_count was explicitly set to 800')
})

console.log('--- renderPromptTemplate: required missing ---')
const bad = renderPromptTemplate(content, vars, { surname: '李' })
ok('rendered is null', () => assert.equal(bad.rendered, null))
ok('missingRequired=[user_name]', () => assert.deepEqual(bad.missingRequired, ['user_name']))

console.log('--- optional unfilled keeps placeholder ---')
const opt = renderPromptTemplate(
  'Hi {{user_name}}! {{topic}}',
  [
    { name: 'user_name', description: '', required: true },
    { name: 'topic', description: '', required: false },
  ],
  { user_name: '张三' }
)
ok('placeholder retained', () => assert.equal(opt.rendered, 'Hi 张三! {{topic}}'))
ok('unfilledOptional=[topic]', () => assert.deepEqual(opt.unfilledOptional, ['topic']))

console.log('--- XSS escaping (AC-06) ---')
const xss = renderPromptTemplate('Say {{msg}}', [{ name: 'msg', description: '', required: false }], {
  msg: '<script>alert("x")</script>',
})
ok('html special chars escaped', () =>
  assert.equal(xss.rendered, 'Say &lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;'))

console.log('--- validateRequiredVariables ---')
ok('flags both missing required', () =>
  assert.deepEqual(validateRequiredVariables(vars, {}), ['user_name', 'surname']))
ok('default satisfies required', () =>
  assert.deepEqual(validateRequiredVariables([{ name: 'a', description: '', required: true, defaultValue: 'x' }], {}), []))
ok('all filled -> []', () =>
  assert.deepEqual(validateRequiredVariables(vars, { user_name: '张', surname: '李' }), []))

console.log('\nRESULT: ' + passed + ' assertions passed' + (process.exitCode ? ' (WITH FAILURES)' : ' — ALL OK'))
