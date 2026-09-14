<template>
  <div class="agent-perf-detail">
    <PageHeader title="Agent 效能详情" show-back>
      <template #actions>
        <button
          class="btn btn--ghost"
          :disabled="store.singleLoading"
          @click="reload()"
        >
          {{ store.singleLoading ? '刷新中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <ErrorBanner
      v-if="store.singleError"
      :message="store.singleError"
      retryable
      @retry="reload()"
    />

    <LoadingState
      v-if="store.singleLoading && !store.singleHasLoaded"
      full-screen
      text="正在加载效能指标…"
    />

    <template v-else-if="m">
      <div class="perf-detail__meta">
        <h2 class="perf-detail__name">{{ m.agent_name || shortId(agentId) }}</h2>
        <span
          v-if="m.status"
          class="agent-status-chip"
          :class="`agent-status-chip--${m.status}`"
          >{{ m.status }}</span
        >
        <span class="perf-detail__dim">
          窗口：{{ windowLabel }} · 点击「← 返回」回到排行榜
        </span>
      </div>

      <!-- KPI 指标卡 -->
      <section class="kpi-grid">
        <KpiCard
          icon="📨"
          label="会话数（窗口内）"
          :loading="store.singleLoading"
          :value-text="fmtNum(m.conversation_count)"
          hint="该 Agent 客户的窗口内会话"
        />
        <KpiCard
          icon="💬"
          label="消息数（窗口内）"
          :loading="store.singleLoading"
          :value-text="fmtNum(m.message_count)"
          :sub-value="peakHourLabel"
          hint="窗口内消息量 + 峰值小时（UTC）"
        />
        <KpiCard
          icon="🎯"
          label="线索转化"
          :loading="store.singleLoading"
          :value-text="rateText(m.conversion_rate, m.lead_count)"
          :no-data="m.conversion_rate === null && m.lead_count === 0"
          :sub-value="`${fmtNum(m.converted_lead_count)} / ${fmtNum(m.lead_count)} 线索`"
          hint="窗口内成交线索 / 新建线索"
        />
        <KpiCard
          icon="😊"
          label="满意度（代理）"
          :loading="store.singleLoading"
          :value-text="satisfactionText"
          :no-data="m.satisfaction_proxy === null"
          :sub-value="sentimentText"
          hint="窗口内带情绪会话的情绪均分（positive=1 / neutral=0.5 / negative=0）"
        />
        <KpiCard
          icon="👥"
          label="客户"
          :loading="store.singleLoading"
          :value-text="`${fmtNum(m.active_customers)} / ${fmtNum(m.total_customers)}`"
          sub-value="活跃 / 全部"
          hint="全部为绑定客户（全量口径）"
        />
      </section>

      <!-- 活跃小时直方图 -->
      <section class="chart-card">
        <h3 class="chart-card__title">活跃时段（24 小时 UTC 消息量直方图）</h3>
        <AgentActiveHoursChart
          v-if="hasHours"
          :data="m.active_hours"
          :peak-hour="m.peak_hour"
          height="240px"
        />
        <EmptyState
          v-else
          icon="⏰"
          title="暂无消息活动"
          description="窗口内该 Agent 没有消息量数据"
        />
      </section>
    </template>

    <EmptyState
      v-else
      icon="🤖"
      title="Agent 不存在或暂无效能数据"
      description="请返回排行榜选择其他 Agent"
      :show-action="true"
      action-text="返回排行榜"
      @action="router.push('/analytics/agents/performance')"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import KpiCard from '@/components/analytics/KpiCard.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'
import AgentActiveHoursChart from '@/components/analytics/AgentActiveHoursChart.vue'
import {
  useAnalyticsAgentPerformanceStore,
  AGENT_RANGE_OPTIONS,
  formatAgentRate,
} from '@/stores/analyticsAgentPerformance'

const route = useRoute()
const router = useRouter()
const store = useAnalyticsAgentPerformanceStore()

const agentId = computed(() => String(route.params.agentId ?? ''))
const m = computed(() => store.single?.metrics)

onMounted(() => {
  if (agentId.value) void store.fetchSingle(agentId.value)
})

function reload() {
  if (agentId.value) void store.fetchSingle(agentId.value)
}

// ---- 格式化 ----
const fmtNum = (n: number) => n.toLocaleString('en-US')

function rateText(rate: number | null, leadCount: number): string {
  if (rate === null) return leadCount === 0 ? '无线索' : '—'
  return formatAgentRate(rate)
}

const satisfactionText = computed(() => {
  if (!m.value || m.value.satisfaction_proxy === null) return '无数据'
  return `${(m.value.satisfaction_proxy * 100).toFixed(0)}%`
})

const sentimentText = computed(() => {
  if (!m.value) return ''
  const b = m.value.sentiment_breakdown ?? {}
  const total = (b.positive ?? 0) + (b.neutral ?? 0) + (b.negative ?? 0)
  if (total === 0) return '无情绪样本'
  return `正 ${b.positive ?? 0} / 中 ${b.neutral ?? 0} / 负 ${b.negative ?? 0}`
})

const peakHourLabel = computed(() => {
  if (!m.value || m.value.peak_hour === null) return '无峰值'
  const h = m.value.peak_hour
  return `峰值 ${String(h).padStart(2, '0')}:00 UTC`
})

const windowLabel = computed(() => {
  const w = store.single?.window
  if (!w) return '—'
  const preset = Object.entries(w).find(
    ([k, v]) => k === 'range' && v !== null
  )
  if (preset) {
    const found = AGENT_RANGE_OPTIONS.find((o) => o.value === preset[1])
    return found ? found.label : String(preset[1])
  }
  const since = w.since
  const until = w.until
  if (since && until) return `${since.slice(0, 10)} → ${until.slice(0, 10)}`
  return '全部'
})

const hasHours = computed(
  () =>
    m.value !== undefined &&
    m.value.active_hours.some((v) => v > 0)
)

const shortId = (id: string) => id.slice(0, 8)
</script>

<style scoped>
.agent-perf-detail {
  max-width: 1000px;
  margin: 0 auto;
}

.perf-detail__meta {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  flex-wrap: wrap;
  margin-bottom: var(--spacing-4);
}

.perf-detail__name {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  margin: 0;
  color: var(--color-text-primary);
}

.perf-detail__dim {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-left: auto;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-5);
}

.chart-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4) var(--spacing-5);
}

.chart-card__title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-3);
}

.agent-status-chip {
  font-size: var(--font-size-xs);
  padding: 1px var(--spacing-2);
  border-radius: 999px;
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
}

.agent-status-chip--active {
  color: #2f9e6b;
  border-color: rgba(47, 158, 107, 0.4);
}

.agent-status-chip--paused {
  color: #d98a2b;
  border-color: rgba(217, 138, 43, 0.4);
}
</style>
