<template>
  <form class="exp-form" @submit.prevent="onSubmit">
    <div class="exp-form__grid">
      <!-- 编码（创建时必填，编辑时只读） -->
      <div class="form-group">
        <label class="form-label">实验编码 code *</label>
        <input
          v-model="form.code"
          class="form-input"
          :disabled="isEdit"
          placeholder="a-z / 0-9 / _ / -（如 new-greeting-ab）"
          pattern="^[a-z0-9_-]{1,100}$"
          :required="!isEdit"
        />
        <p v-if="errors.code" class="form-error">{{ errors.code }}</p>
        <p v-else-if="isEdit" class="form-hint">编码创建后不可修改</p>
      </div>

      <!-- 名称 -->
      <div class="form-group">
        <label class="form-label">实验名称 name *</label>
        <input
          v-model="form.name"
          class="form-input"
          placeholder="如：新欢迎语 A/B 测试"
        />
        <p v-if="errors.name" class="form-error">{{ errors.name }}</p>
      </div>

      <!-- 描述 -->
      <div class="form-group form-group--full">
        <label class="form-label">描述 description</label>
        <textarea
          v-model="form.description"
          class="form-input"
          rows="2"
          placeholder="（可选）实验背景 / 目标"
        ></textarea>
      </div>

      <!-- 假设 -->
      <div class="form-group form-group--full">
        <label class="form-label">假设 hypothesis</label>
        <textarea
          v-model="form.hypothesis"
          class="form-input"
          rows="2"
          placeholder="（可选）若 X 则 Y 的预期因果假设"
        ></textarea>
      </div>

      <!-- 主指标 -->
      <div class="form-group">
        <label class="form-label">主指标 code</label>
        <input
          v-model="form.primary_metric_code"
          class="form-input"
          placeholder="（可选）注册指标 code，如 conversion_rate"
        />
      </div>

      <!-- 次指标（逗号分隔） -->
      <div class="form-group">
        <label class="form-label">次指标 codes</label>
        <input
          v-model="form.secondaryMetricInput"
          class="form-input"
          placeholder="（可选）逗号分隔，如 cr,satisfaction"
        />
        <p class="form-hint">用英文逗号分隔多个指标 code</p>
      </div>

      <!-- 负责人 -->
      <div class="form-group form-group--full">
        <label class="form-label">负责人 owner</label>
        <input
          v-model="form.owner"
          class="form-input"
          placeholder="（可选）"
        />
      </div>
    </div>

    <!-- 变组编辑器 -->
    <fieldset class="exp-form__variants">
      <legend>变组 variants（含流量份额 share，可选）</legend>
      <p class="form-hint exp-form__variants-hint">
        每个变组至少一个 label；若任一变组填了份额，则所有变组份额之和必须
        = 1.0（±1e-6），否则保存会被后端拒绝（409）。
      </p>

      <div
        v-for="(v, i) in form.variants"
        :key="i"
        class="variant-row"
      >
        <input
          v-model="v.label"
          class="variant-row__input"
          placeholder="label（如 control / variant_a）"
        />
        <input
          v-model.number="v.share"
          class="variant-row__input variant-row__input--num"
          type="number"
          min="0"
          max="1"
          step="0.01"
          placeholder="份额 0-1"
        />
        <input
          v-model="v.configText"
          class="variant-row__input variant-row__input--wide"
          placeholder='config（JSON，可选，如 {"tone":"warm"}）'
        />
        <span
          v-if="shareError && i === form.variants.length - 1"
          class="form-error variant-row__share-error"
        >
          {{ shareError }}
        </span>
        <button
          type="button"
          class="btn btn--ghost btn--sm variant-row__remove"
          :disabled="form.variants.length <= 1"
          title="移除该变组"
          @click="removeVariant(i)"
        >
          ×
        </button>
      </div>

      <button type="button" class="btn btn--ghost btn--sm" @click="addVariant">
        + 添加变组
      </button>

      <p v-if="errors.variants" class="form-error exp-form__variants-error">
        {{ errors.variants }}
      </p>

      <p v-if="shareSum" class="exp-form__share-sum">
        当前份额合计：{{ shareSum }}
        <span :class="shareOk ? 'exp-form__share-ok' : 'exp-form__share-bad'">
          （{{ shareOk ? '校验通过' : '须为 1.0' }}）
        </span>
      </p>
    </fieldset>

    <!-- 表单级错误（后端 409 / 网络） -->
    <div v-if="formError" class="exp-form__error" role="alert">
      ⚠️ {{ formError }}
    </div>

    <ModalFooter>
      <button type="button" class="btn btn--ghost" @click="$emit('cancel')">
        取消
      </button>
      <button type="submit" class="btn btn--primary" :disabled="saving">
        {{ saving ? '保存中…' : isEdit ? '保存修改' : '创建实验' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
/**
 * 实验创建 / 编辑表单（Phase 6 / P6AN-12，对接 P6AN-08 API）。
 *
 * - 前端校验镜像后端规则：code 正则、name 必填、variants 份额 all-or-nothing；
 *   后端 409（份额违例 / 状态机）会被捕获并就地展示。
 * - 变组 config 在 UI 里是 JSON 文本框，提交前 parse；非法 JSON 直接报校验错。
 */
import { computed, reactive, ref } from 'vue'
import ModalFooter from '@/components/common/ModalFooter.vue'
import type {
  Experiment,
  ExperimentCreate,
  ExperimentUpdate,
  ExperimentVariant,
} from '@/api/analytics-types'

/** 行内变组草稿：share / configText 为输入态，提交时归一 */
interface VariantDraft {
  label: string
  share: number | null
  configText: string
}

const props = defineProps<{
  /** 传入则为编辑态（code 只读、走 update），否则为创建态 */
  experiment?: Experiment
  saving?: boolean
  /** 后端返回的表单级错误（409 / 网络） */
  formError?: string | null
}>()

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'submit', payload: ExperimentCreate | ExperimentUpdate): void
}>()

const isEdit = computed(() => !!props.experiment)

function toDrafts(variants: ExperimentVariant[] | undefined): VariantDraft[] {
  if (!variants || variants.length === 0) {
    return [{ label: '', share: null, configText: '' }]
  }
  return variants.map((v) => ({
    label: v.label,
    share:
      typeof v.share === 'number' ? v.share : null,
    configText:
      v.config && Object.keys(v.config).length > 0
        ? JSON.stringify(v.config)
        : '',
  }))
}

const form = reactive({
  code: props.experiment?.code ?? '',
  name: props.experiment?.name ?? '',
  description: props.experiment?.description ?? '',
  hypothesis: props.experiment?.hypothesis ?? '',
  primary_metric_code: props.experiment?.primary_metric_code ?? '',
  secondaryMetricInput: (props.experiment?.secondary_metric_codes ?? []).join(','),
  owner: props.experiment?.owner ?? '',
  variants: toDrafts(props.experiment?.variants) as VariantDraft[],
})

const errors = reactive<Record<string, string>>({})

// ---- 份额校验（all-or-nothing，镜像后端） ----
const hasAnyShare = computed(() =>
  form.variants.some((v) => v.share !== null && !Number.isNaN(v.share as number))
)
const shareSum = computed(() => {
  if (!hasAnyShare.value) return null
  return Math.round(
    form.variants.reduce(
      (acc, v) => acc + (v.share !== null && !Number.isNaN(v.share as number) ? (v.share as number) : 0),
      0
    ) * 1e6
  ) / 1e6
})
const shareOk = computed(() => {
  if (!hasAnyShare.value) return true
  return Math.abs((shareSum.value ?? 0) - 1.0) <= 1e-6
})
const shareError = computed(() => {
  if (hasAnyShare.value && !shareOk.value) {
    return `份额之和必须 = 1.0，当前 ${shareSum.value}`
  }
  return ''
})

// ---- 配置 JSON 校验 ----
const configError = computed(() => {
  for (let i = 0; i < form.variants.length; i++) {
    const v = form.variants[i]
    if (!v) continue
    const t = v.configText.trim()
    if (t === '') continue
    try {
      const parsed = JSON.parse(t)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return `变组 ${i + 1} 的 config 必须是 JSON 对象`
      }
    } catch {
      return `变组 ${i + 1} 的 config 不是合法 JSON`
    }
  }
  return ''
})

const variantLabelError = computed(() =>
  form.variants.some((v) => !v.label.trim()) ? '每个变组都必须填写 label' : ''
)

function validate(): boolean {
  const e: Record<string, string> = {}
  if (!isEdit.value) {
    if (!form.code.trim()) e.code = '编码必填'
    else if (!/^[a-z0-9_-]{1,100}$/.test(form.code.trim()))
      e.code = '编码只能含小写字母 / 数字 / _ / -（1-100 字符）'
  }
  if (!form.name.trim()) e.name = '名称必填'
  else if (form.name.trim().length > 200) e.name = '名称过长（>200）'

  // 清除旧错误后重算
  errors.code = ''
  errors.name = ''
  errors.variants = ''
  if (e.code) errors.code = e.code
  if (e.name) errors.name = e.name
  if (variantLabelError.value || configError.value || shareError.value) {
    errors.variants = variantLabelError.value || configError.value || shareError.value
  }
  return !errors.code && !errors.name && !errors.variants
}

function addVariant() {
  form.variants.push({ label: '', share: null, configText: '' })
}

function removeVariant(i: number) {
  if (form.variants.length <= 1) return
  form.variants.splice(i, 1)
}

function onSubmit() {
  if (!validate()) return

  const secondary = form.secondaryMetricInput
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

  const variants: ExperimentVariant[] = form.variants.map((v) => {
    const out: ExperimentVariant = { label: v.label.trim() }
    if (v.share !== null && !Number.isNaN(v.share as number)) {
      out.share = v.share as number
    }
    const ct = v.configText.trim()
    if (ct !== '') {
      out.config = JSON.parse(ct)
    }
    return out
  })

  const payload: ExperimentCreate = {
    code: form.code.trim(),
    name: form.name.trim(),
    description: form.description?.trim() || undefined,
    hypothesis: form.hypothesis?.trim() || undefined,
    primary_metric_code: form.primary_metric_code?.trim() || null,
    secondary_metric_codes: secondary,
    variants,
    owner: form.owner?.trim() || undefined,
  }

  if (isEdit.value) {
    // 编辑态：code 不可改，剥离后走 update 契约
    const { code: _omit, ...updatePayload } = payload
    emit('submit', updatePayload as unknown as ExperimentUpdate)
  } else {
    emit('submit', payload)
  }
}
</script>

<style scoped>
.exp-form__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-3) var(--spacing-4);
  margin-bottom: var(--spacing-4);
}

.exp-form__grid .form-group--full {
  grid-column: 1 / -1;
}

.exp-form .form-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-1);
}

.exp-form .form-error {
  font-size: var(--font-size-xs);
  color: var(--color-error);
  margin-top: var(--spacing-1);
}

.exp-form__variants {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin: 0 0 var(--spacing-4);
}

.exp-form__variants legend {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  padding: 0 var(--spacing-2);
}

.exp-form__variants-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--spacing-3);
}

.variant-row {
  display: grid;
  grid-template-columns: 1fr 90px 1.4fr auto;
  gap: var(--spacing-2);
  align-items: start;
  margin-bottom: var(--spacing-2);
}

.variant-row__input {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
}

.variant-row__input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.variant-row__remove {
  align-self: center;
}

.variant-row__share-error {
  grid-column: 1 / -1;
}

.exp-form__share-sum {
  margin-top: var(--spacing-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.exp-form__share-ok {
  color: var(--color-success);
}

.exp-form__share-bad {
  color: var(--color-error);
}

.exp-form__error {
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-md);
  color: var(--color-error);
  font-size: var(--font-size-sm);
  padding: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

@media (max-width: 720px) {
  .exp-form__grid {
    grid-template-columns: 1fr;
  }
  .variant-row {
    grid-template-columns: 1fr 80px;
  }
  .variant-row__input--wide {
    grid-column: 1 / -1;
  }
}
</style>
