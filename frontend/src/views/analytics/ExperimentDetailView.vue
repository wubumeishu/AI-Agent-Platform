<template>
  <div class="exp-detail">
    <PageHeader title="实验详情" show-back>
      <template #actions>
        <button
          class="btn btn--ghost"
          :disabled="store.loading"
          @click="reload()"
        >
          {{ store.loading ? '刷新中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <ErrorBanner
      v-if="store.error"
      :message="store.error"
      retryable
      @retry="reload()"
    />

    <LoadingState
      v-if="store.loading && !exp"
      full-screen
      text="正在加载实验…"
    />

    <template v-else-if="exp">
      <!-- 状态徽章 + 状态机操作 -->
      <div class="exp-detail__status">
        <span
          class="status-badge"
          :style="{ color: statusColor, borderColor: statusColor, background: statusBg }"
        >
          {{ statusLabel }}
        </span>
        <span v-if="exp.started_at" class="exp-detail__meta">
          开始 {{ fmtDateTime(exp.started_at) }}
        </span>
        <span v-if="exp.ended_at" class="exp-detail__meta">
          结束 {{ fmtDateTime(exp.ended_at) }}
        </span>

        <div class="exp-detail__transitions">
          <template v-for="t in transitions" :key="t">
            <button
              class="btn btn--ghost btn--sm"
              :class="{ 'btn--primary': t === 'running', 'btn--danger': t === 'terminated' }"
              :disabled="store.saving"
              @click="onTransition(t)"
            >
              → {{ experimentStatusLabel(t) }}
            </button>
          </template>
          <button
            v-if="!isTerminal"
            class="btn btn--danger btn--sm"
            :disabled="store.saving"
            @click="onDelete"
          >
            删除
          </button>
        </div>
      </div>

      <!-- 终止原因输入（仅当目标为 terminated 时显示） -->
      <div v-if="pendingTerminate" class="exp-detail__terminate">
        <label class="form-label">终止原因（必填）</label>
        <input
          v-model="terminateReason"
          class="form-input"
          placeholder="请填写终止原因"
        />
        <div class="exp-detail__terminate-actions">
          <button
            class="btn btn--danger btn--sm"
            :disabled="store.saving || !terminateReason.trim()"
            @click="confirmTerminate"
          >
            确认终止
          </button>
          <button class="btn btn--ghost btn--sm" @click="pendingTerminate = false">
            取消
          </button>
        </div>
      </div>

      <!-- 实验信息 -->
      <section class="exp-detail__section">
        <h3 class="exp-detail__title">实验信息</h3>
        <dl class="exp-info">
          <dt>编码</dt>
          <dd>{{ exp.code }}</dd>
          <dt>名称</dt>
          <dd>{{ exp.name }}</dd>
          <dt v-if="exp.description">描述</dt>
          <dd v-if="exp.description">{{ exp.description }}</dd>
          <dt v-if="exp.hypothesis">假设</dt>
          <dd v-if="exp.hypothesis">{{ exp.hypothesis }}</dd>
          <dt v-if="exp.primary_metric_code">主指标</dt>
          <dd v-if="exp.primary_metric_code">{{ exp.primary_metric_code }}</dd>
          <dt v-if="exp.secondary_metric_codes?.length">次指标</dt>
          <dd v-if="exp.secondary_metric_codes?.length">
            {{ exp.secondary_metric_codes.join(', ') }}
          </dd>
          <dt v-if="exp.owner">负责人</dt>
          <dd v-if="exp.owner">{{ exp.owner }}</dd>
        </dl>
      </section>

      <!-- 变组 -->
      <section class="exp-detail__section">
        <h3 class="exp-detail__title">变组（{{ exp.variants?.length ?? 0 }}）</h3>
        <div v-if="exp.variants?.length" class="variant-list">
          <div
            v-for="(v, i) in exp.variants"
            :key="i"
            class="variant-item"
          >
            <span class="variant-item__label">{{ v.label }}</span>
            <span
              v-if="typeof v.share === 'number'"
              class="variant-item__share"
              >份额 {{ (v.share * 100).toFixed(0) }}%</span
            >
            <span
              v-if="v.config && Object.keys(v.config).length"
              class="variant-item__config"
              >{{ JSON.stringify(v.config) }}</span
            >
          </div>
        </div>
        <EmptyState
          v-else
          icon="🧩"
          title="未配置变组"
          description="该实验还没有变组配置"
        />
      </section>

      <!-- P6AN-08 结果对比 -->
      <section class="exp-detail__section">
        <div class="exp-detail__section-header">
          <h3 class="exp-detail__title">结果对比（P6AN-08）</h3>
          <label class="exp-detail__threshold">
            显著性阈值
            <input
              v-model.number="thresholdInput"
              type="number"
              min="0"
              max="1"
              step="0.01"
              class="exp-detail__threshold-input"
              :disabled="store.summaryLoading"
              @change="onThresholdChange"
            />
          </label>
        </div>

        <ErrorBanner
          v-if="store.summaryError"
          :message="store.summaryError"
          retryable
          @retry="store.fetchSummary(id, thresholdInput)"
        />

        <template v-if="store.summary && store.summary.metrics.length">
          <ExperimentComparisonChart
            :summary="store.summary"
            height="300px"
          />
          <!-- 对比表（每指标 × 各变组） -->
          <div class="summary-table-wrap">
            <table class="summary-table">
              <thead>
                <tr>
                  <th>指标</th>
                  <th
                    v-for="v in variantLabelsOf(store.summary)"
                    :key="v"
                  >
                    {{ v }}<span v-if="isBaseline(v)" class="summary-table__base">（基线）</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in store.summary!.metrics" :key="m.metric_code">
                  <td class="summary-table__metric">
                    {{ m.metric_code }}<span v-if="m.is_primary"> · 主</span>
                  </td>
                  <td
                    v-for="v in variantLabelsOf(store.summary)"
                    :key="v"
                  >
                    <template
                      v-if="rowFor(store.summary, m.metric_code, v)"
                    >
                      {{ numText(rowFor(store.summary, m.metric_code, v)!.metric_value) }}
                      <div class="summary-table__lift">
                        <span v-if="rowFor(store.summary, m.metric_code, v)!.lift_vs_baseline_percent !== null">
                          {{
                            liftText(
                              rowFor(store.summary, m.metric_code, v)!.lift_vs_baseline_percent
                            )
                          }}
                        </span>
                        <span
                          v-else
                          class="summary-table__dim"
                          >无 lift</span
                        >
                      </div>
                    </template>
                    <span v-else class="summary-table__dim">无快照</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p
            v-if="store.summary.notes.length"
            class="exp-detail__note"
          >
            {{ store.summary.notes.join(' · ') }}
          </p>
        </template>
        <EmptyState
          v-else-if="!store.summaryLoading"
          icon="📈"
          title="暂无结果快照"
          description="该实验还没有记录任何结果快照，无法生成对比"
        />
      </section>

      <!-- 结果快照列表 + 记录 -->
      <section class="exp-detail__section">
        <div class="exp-detail__section-header">
          <h3 class="exp-detail__title">结果快照（{{ store.resultsTotal }}）</h3>
          <button
            class="btn btn--primary btn--sm"
            @click="showRecordForm = !showRecordForm"
          >
            + 记录快照
          </button>
        </div>

        <ErrorBanner
          v-if="store.resultsError"
          :message="store.resultsError"
          retryable
          @retry="store.fetchResults(id, store.resultsPage)"
        />

        <!-- 记录快照表单 -->
        <div v-if="showRecordForm" class="record-form">
          <div class="record-form__row">
            <input
              v-model="rec.variant_label"
              class="form-input"
              placeholder="变组 label"
              list="exp-variant-options"
            />
            <input
              v-model="rec.metric_code"
              class="form-input"
              placeholder="指标 code"
            />
          </div>
          <div class="record-form__row">
            <input
              v-model="rec.metric_value"
              class="form-input"
              type="number"
              step="any"
              placeholder="观测值 *"
            />
            <input
              v-model="rec.baseline_value"
              class="form-input"
              type="number"
              step="any"
              placeholder="基线值"
            />
            <input
              v-model="rec.lift_percent"
              class="form-input"
              type="number"
              step="any"
              placeholder="提升 %"
            />
            <input
              v-model="rec.p_value"
              class="form-input"
              type="number"
              min="0"
              max="1"
              step="any"
              placeholder="p 值（0-1）"
            />
          </div>
          <div class="record-form__row">
            <input
              v-model="rec.sample_size"
              class="form-input"
              type="number"
              min="0"
              placeholder="样本量"
            />
          </div>
          <datalist id="exp-variant-options">
            <option v-for="v in exp.variants" :key="v.label" :value="v.label" />
          </datalist>
          <div class="record-form__actions">
            <button
              class="btn btn--primary btn--sm"
              :disabled="rec.metric_value === '' || !rec.variant_label || !rec.metric_code"
              @click="submitRecord"
            >
              保存快照
            </button>
            <button class="btn btn--ghost btn--sm" @click="showRecordForm = false">
              取消
            </button>
          </div>
        </div>

        <table v-if="store.results.length" class="results-table">
          <thead>
            <tr>
              <th>变组</th>
              <th>指标</th>
              <th>观测值</th>
              <th>样本</th>
              <th>p 值</th>
              <th>显著</th>
              <th>记录于</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in store.results" :key="r.id">
              <td>{{ r.variant_label }}</td>
              <td>{{ r.metric_code }}</td>
              <td>{{ numText(r.metric_value) }}</td>
              <td>{{ r.sample_size }}</td>
              <td>{{ r.p_value ?? '—' }}</td>
              <td>
                <span v-if="r.is_significant === true" class="sig sig--yes">✓ 显著</span>
                <span v-else-if="r.is_significant === false" class="sig sig--no">不显著</span>
                <span v-else class="summary-table__dim">未评估</span>
              </td>
              <td class="summary-table__dim">{{ fmtDateTime(r.computed_at) }}</td>
            </tr>
          </tbody>
        </table>
        <EmptyState
          v-else-if="!store.resultsLoading"
          icon="🗂️"
          title="暂无快照"
          description="还没有任何结果快照记录"
        />
      </section>
    </template>

    <EmptyState
      v-else
      icon="🧪"
      title="实验不存在"
      description="该实验可能已被删除"
      :show-action="true"
      action-text="返回列表"
      @action="router.push('/analytics/experiments')"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'
import ExperimentComparisonChart from '@/components/analytics/ExperimentComparisonChart.vue'
import {
  useAnalyticsExperimentStore,
  allowedTransitions,
  experimentStatusLabel,
  experimentStatusColor,
} from '@/stores/analyticsExperiment'
import type {
  Experiment,
  ExperimentResultCreate,
  ExperimentResultSummaryResponse,
  ExperimentResultSummaryRow,
} from '@/api/analytics-types'

const route = useRoute()
const router = useRouter()
const store = useAnalyticsExperimentStore()

const id = computed(() => String(route.params.experimentId ?? ''))
const exp = computed<Experiment | null>(() => store.current)

// ---- 状态机 ----
const isTerminal = computed(() =>
  ['completed', 'terminated'].includes(exp.value?.status ?? '')
)
const transitions = computed<readonly string[]>(() =>
  allowedTransitions(exp.value?.status ?? '')
)
const statusLabel = computed(() =>
  exp.value ? experimentStatusLabel(exp.value.status) : ''
)
const statusColor = computed(() =>
  exp.value ? experimentStatusColor(exp.value.status) : ''
)
const statusBg = computed(() => {
  const c = statusColor.value
  return c ? `${c}1A` : 'transparent'
})

const pendingTerminate = ref(false)
const terminateReason = ref('')

function onTransition(t: string) {
  if (t === 'terminated') {
    pendingTerminate.value = true
    terminateReason.value = ''
  } else {
    void store.transitionStatus(id.value, t as 'running' | 'paused' | 'completed')
  }
}

async function confirmTerminate() {
  const ok = await store.transitionStatus(
    id.value,
    'terminated',
    terminateReason.value.trim()
  )
  if (ok) pendingTerminate.value = false
}

async function onDelete() {
  if (!exp.value) return
  const ok = confirm(`确定删除实验「${exp.value.name}」？（软删除，不可恢复）`)
  if (!ok) return
  if (await store.deleteExperiment(exp.value.id)) {
    router.push('/analytics/experiments')
  }
}

// ---- P6AN-08 摘要 ----
const thresholdInput = ref(0.05)
function onThresholdChange() {
  const v = thresholdInput.value
  if (Number.isNaN(v) || v < 0 || v > 1) {
    thresholdInput.value = 0.05
    return
  }
  void store.fetchSummary(id.value, thresholdInput.value)
}

function variantLabelsOf(
  s: ExperimentResultSummaryResponse
): string[] {
  const seen: string[] = []
  for (const m of s.metrics) {
    for (const r of m.variants) {
      if (!seen.includes(r.variant_label)) seen.push(r.variant_label)
    }
  }
  return seen
}

function isBaseline(label: string): boolean {
  return store.summary?.baseline_variant === label
}

function rowFor(
  s: ExperimentResultSummaryResponse,
  metricCode: string,
  variant: string
): ExperimentResultSummaryRow | null {
  const m = s.metrics.find((x) => x.metric_code === metricCode)
  return m?.variants.find((r) => r.variant_label === variant) ?? null
}

// ---- 结果快照记录 ----
const showRecordForm = ref(false)
const rec = reactive({
  variant_label: '',
  metric_code: '',
  metric_value: '',
  baseline_value: '',
  lift_percent: '',
  p_value: '',
  sample_size: '',
})

async function submitRecord() {
  const payload: ExperimentResultCreate = {
    variant_label: rec.variant_label.trim(),
    metric_code: rec.metric_code.trim(),
    metric_value: rec.metric_value,
    sample_size: rec.sample_size === '' ? 0 : Number(rec.sample_size),
  }
  if (rec.baseline_value !== '') payload.baseline_value = rec.baseline_value
  if (rec.lift_percent !== '') payload.lift_percent = rec.lift_percent
  if (rec.p_value !== '') payload.p_value = rec.p_value
  const ok = await store.createResult(id.value, payload)
  if (ok) {
    showRecordForm.value = false
    rec.metric_value = ''
    rec.baseline_value = ''
    rec.lift_percent = ''
    rec.p_value = ''
    rec.sample_size = ''
  }
}

// ---- 格式化 ----
function numText(v: string | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toLocaleString('en-US')
}

function liftText(pct: string | null | undefined): string {
  if (pct === null || pct === undefined) return '—'
  const n = Number(pct)
  if (Number.isNaN(n)) return String(pct)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'short',
  })
}

// ---- 生命周期 ----
function reload() {
  if (!id.value) return
  void store.fetchDetail(id.value)
  void store.fetchResults(id.value)
  void store.fetchSummary(id.value)
}

onMounted(() => {
  reload()
})
</script>

<style scoped>
.exp-detail {
  max-width: 1100px;
  margin: 0 auto;
}

.exp-detail__status {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  flex-wrap: wrap;
  margin-bottom: var(--spacing-5);
}

.exp-detail__meta {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.exp-detail__transitions {
  display: flex;
  gap: var(--spacing-2);
  margin-left: auto;
  flex-wrap: wrap;
}

.status-badge {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  padding: var(--spacing-1) var(--spacing-3);
  border: 1px solid;
  border-radius: 999px;
}

.exp-detail__terminate {
  background: var(--color-error-light);
  border: 1px solid var(--color-error);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin-bottom: var(--spacing-4);
}

.exp-detail__terminate-actions {
  display: flex;
  gap: var(--spacing-2);
  margin-top: var(--spacing-3);
}

.exp-detail__section {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  margin-bottom: var(--spacing-5);
}

.exp-detail__section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-3);
  flex-wrap: wrap;
}

.exp-detail__title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-3);
}

.exp-detail__threshold {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.exp-detail__threshold-input {
  width: 64px;
  padding: var(--spacing-1) var(--spacing-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-size: var(--font-size-xs);
}

.exp-detail__note {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-3);
}

.exp-info {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: var(--spacing-2) var(--spacing-4);
  font-size: var(--font-size-sm);
  margin: 0;
}

.exp-info dt {
  color: var(--color-text-muted);
}

.exp-info dd {
  margin: 0;
  color: var(--color-text-secondary);
}

.variant-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-2);
}

.variant-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  font-size: var(--font-size-sm);
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.variant-item__label {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.variant-item__share {
  color: var(--color-primary);
}

.variant-item__config {
  color: var(--color-text-muted);
  font-family: monospace;
  font-size: var(--font-size-xs);
}

.summary-table-wrap {
  overflow-x: auto;
  margin-top: var(--spacing-4);
}

.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.summary-table th {
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  padding: var(--spacing-2);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.summary-table td {
  padding: var(--spacing-2);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.summary-table__metric {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.summary-table__base {
  color: var(--color-primary);
  font-size: var(--font-size-xs);
}

.summary-table__lift {
  font-size: var(--font-size-xs);
  color: var(--color-primary);
}

.summary-table__dim {
  color: var(--color-text-muted);
}

.results-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.results-table th {
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  padding: var(--spacing-2);
  border-bottom: 1px solid var(--color-border);
}

.results-table td {
  padding: var(--spacing-2);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}

.record-form {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin-bottom: var(--spacing-4);
}

.record-form__row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--spacing-2);
  margin-bottom: var(--spacing-2);
}

.record-form__actions {
  display: flex;
  gap: var(--spacing-2);
}

.sig {
  font-size: var(--font-size-xs);
  padding: 1px var(--spacing-2);
  border-radius: 999px;
}

.sig--yes {
  color: var(--color-success);
  background: rgba(16, 185, 129, 0.12);
}

.sig--no {
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary, var(--color-bg-secondary));
}
</style>
