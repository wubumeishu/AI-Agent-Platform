<template>
  <div class="analytics-metrics">
    <PageHeader title="数据洞察 · 指标">
      <template #actions>
        <button
          class="btn btn--ghost"
          @click="onRefresh"
          :disabled="metricsStore.metricsLoading || metricsStore.metricDefinitionsLoading"
        >
          刷新
        </button>
      </template>
    </PageHeader>

    <FilterBar @apply="onRefresh" />

    <ErrorBanner
      v-if="metricsStore.metricsError || metricsStore.metricDefinitionsError"
      :message="metricsStore.metricsError ?? metricsStore.metricDefinitionsError ?? ''"
      retryable
      @retry="onRefresh"
    />

    <LoadingState
      v-if="metricsStore.metricsLoading && !metricsStore.metricsHasLoaded"
      full-screen
      text="正在加载指标…"
    />

    <template v-else>
      <!-- P6AN-04 会话质量与效率 headline 指标 -->
      <section class="metrics-section">
        <h2 class="metrics-section__title">会话质量与效率（P6AN-04）</h2>
        <EmptyState
          v-if="metricsStore.conversationMetricsEmpty"
          icon="💬"
          title="暂无会话数据"
          description="当前过滤范围内没有 AI 会话。产生一些会话后再来看质量指标。"
        />
        <div v-else class="kpi-grid">
          <KpiCard
            icon="⏱️"
            label="平均响应时长"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtSeconds(m.avg_response_time_seconds)"
            hint="用户消息 → 下一条 AI 消息"
          />
          <KpiCard
            icon="🔁"
            label="平均会话轮次"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtFixed(m.avg_conversation_rounds)"
            hint="用户消息 / 会话数"
          />
          <KpiCard
            icon="🎯"
            label="意图准确率（代理）"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtPercent(m.intent_accuracy)"
            :hint="intentAccuracyHint"
          />
          <KpiCard
            icon="🙋"
            label="人工接管率"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtPercent(m.human_handoff_rate)"
            hint="含升级型意图的会话占比"
          />
          <KpiCard
            icon="😊"
            label="满意度（代理）"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtPercent(m.satisfaction_rate)"
            hint="正向情绪会话 / 带情绪标签会话"
          />
          <KpiCard
            icon="🧮"
            label="样本量"
            :loading="metricsStore.metricsLoading"
            :value-text="fmtNum(m.sample_size)"
            hint="窗口内会话数"
          />
        </div>
      </section>

      <!-- 指标定义注册表 -->
      <section class="metrics-section">
        <h2 class="metrics-section__title">指标定义</h2>
        <LoadingState
          v-if="metricsStore.metricDefinitionsLoading && metricsStore.metricDefinitions.length === 0"
          text="加载指标定义…"
        />
        <EmptyState
          v-else-if="metricsStore.metricDefinitions.length === 0 && !metricsStore.metricDefinitionsLoading"
          icon="📐"
          title="暂无指标定义"
          description="还没有注册指标定义（/analytics/metrics）"
        />
        <div v-else class="table-card">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>代码</th>
                <th>分类</th>
                <th>单位</th>
                <th>窗口</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in metricsStore.metricDefinitions" :key="m.id">
                <td class="cell-name">{{ m.name }}</td>
                <td class="cell-code">{{ m.code }}</td>
                <td>{{ m.category }}</td>
                <td>{{ m.unit || '—' }}</td>
                <td>{{ m.window_days }}d</td>
                <td>
                  <StatusBadge
                    :status="m.enabled ? 'success' : 'info'"
                    :label="m.enabled ? '启用' : '停用'"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useAnalyticsMetricsStore } from '@/stores/analyticsMetrics'
import { useAnalyticsOptionsStore } from '@/stores/analyticsOptions'
import KpiCard from '@/components/analytics/KpiCard.vue'
import FilterBar from '@/components/analytics/FilterBar.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'

const metricsStore = useAnalyticsMetricsStore()
const options = useAnalyticsOptionsStore()

// 无数据时的安全兜底（全部 0 / has_data=false），避免渲染 undefined
const m = computed(() =>
  metricsStore.conversationMetrics ?? {
    sample_size: 0,
    has_data: false,
    avg_response_time_seconds: 0,
    avg_conversation_rounds: 0,
    intent_accuracy: 0,
    human_handoff_rate: 0,
    satisfaction_rate: 0,
    accuracy_threshold: 0.7,
  }
)

const fmtNum = (n: number) => n.toLocaleString('en-US')
const fmtFixed = (n: number) => (Number.isFinite(n) ? n.toFixed(1) : '—')
const fmtPercent = (n: number) => `${(n * 100).toFixed(1)}%`
const fmtSeconds = (n: number) =>
  n >= 60 ? `${Math.floor(n / 60)}m ${Math.round(n % 60)}s` : `${n.toFixed(1)}s`

const intentAccuracyHint = computed(
  () => `置信度 ≥ ${m.value.accuracy_threshold} 且匹配到动作`
)

onMounted(() => {
  void options.loadAgents()
  void onRefresh()
})

async function onRefresh() {
  await Promise.all([
    metricsStore.fetchConversationMetrics({ range: '30d' }),
    metricsStore.fetchMetricDefinitions({ page: 1, page_size: 100 }),
  ])
}
</script>

<style scoped>
.analytics-metrics {
  max-width: 1200px;
  margin: 0 auto;
}

.metrics-section {
  margin-bottom: var(--spacing-6);
}

.metrics-section__title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-4);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--spacing-4);
}

.table-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.table-card table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.table-card th {
  text-align: left;
  padding: var(--spacing-3) var(--spacing-4);
  background: var(--color-bg-tertiary);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.table-card td {
  padding: var(--spacing-3) var(--spacing-4);
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}

.cell-name {
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
}

.cell-code {
  font-family: monospace;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
