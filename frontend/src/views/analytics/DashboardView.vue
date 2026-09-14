<template>
  <div class="analytics-dashboard">
    <PageHeader title="数据洞察 · 概览">
      <template #actions>
        <button class="btn btn--ghost" @click="dashboardStore.refresh()" :disabled="dashboardStore.loading">
          {{ dashboardStore.loading ? '刷新中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <!-- 共享过滤器（时间窗口 / Agent / 渠道，读 analyticsOptions store） -->
    <FilterBar @apply="onApplyFilters" />

    <!-- 错误条（保留旧数据降级展示 + 重试） -->
    <ErrorBanner
      v-if="dashboardStore.error"
      :message="dashboardStore.error"
      retryable
      @retry="dashboardStore.refresh()"
    />

    <!-- 首次加载中：整页骨架 -->
    <LoadingState v-if="dashboardStore.loading && !dashboardStore.hasLoaded" full-screen text="正在加载数据洞察…" />

    <!-- 已加载：概览内容 -->
    <template v-else>
      <!-- 空态：全部指标为 0 / 无 Agent -->
      <EmptyState
        v-if="isEmptyState"
        icon="📊"
        title="暂无数据"
        description="当前时间窗口内还没有 Agent / 会话 / 消息 / 线索数据。先创建 Agent 并产生一些交互，再回来看概览。"
      />

      <template v-else>
        <!-- KPI 指标卡 -->
        <section class="kpi-grid">
          <KpiCard
            icon="🤖"
            label="Agent"
            :loading="dashboardStore.loading"
            :value-text="fmt(store?.agents.total ?? 0)"
            :sub-value="`活跃 ${fmt(store?.agents.active ?? 0)}`"
            hint="未删除 Agent 总数"
          />
          <KpiCard
            icon="📨"
            label="新增会话"
            :loading="dashboardStore.loading"
            :value-text="fmt(store?.conversations.new ?? 0)"
            :sub-value="`在途 ${fmt(store?.conversations.active ?? 0)}`"
            :hint="avgMessagesHint"
          />
          <KpiCard
            icon="💬"
            label="消息（窗口内）"
            :loading="dashboardStore.loading"
            :value-text="fmt(store?.messages.total ?? 0)"
            :no-data="(store?.messages.delivered ?? 0) + (store?.messages.failed ?? 0) === 0"
            :sub-value="successRateText"
            hint="送达率 = 已送达 /（已送达 + 失败）"
          />
          <KpiCard
            icon="🎯"
            label="线索转化"
            :loading="dashboardStore.loading"
            :value-text="conversionRateText"
            :no-data="(store?.conversion.conversion_rate ?? null) === null"
            :sub-value="`新增 ${fmt(store?.conversion.new_leads ?? 0)}`"
            hint="已转化 / 全部线索（全量口径）"
          />
        </section>

        <!-- 图表区 -->
        <section class="chart-grid">
          <div class="chart-card">
            <h3 class="chart-card__title">Agent 活跃度 Top 10</h3>
            <AgentActivityChart v-if="agentStats.length > 0" :data="agentStats" height="280px" />
            <EmptyState
              v-else
              icon="🤖"
              title="暂无 Agent 消息"
              description="窗口内没有 Agent 产生渠道消息"
            />
          </div>

          <div class="chart-card">
            <h3 class="chart-card__title">消息发送状态</h3>
            <MessageStatusChart v-if="messages" :data="messages" height="280px" />
            <EmptyState
              v-else
              icon="💬"
              title="暂无消息"
              description="窗口内没有渠道消息记录"
            />
          </div>

          <div class="chart-card">
            <h3 class="chart-card__title">线索转化漏斗</h3>
            <ConversionFunnelChart v-if="conversion" :data="conversion" height="280px" />
            <EmptyState
              v-else
              icon="🎯"
              title="暂无线索"
              description="还没有线索数据"
            />
          </div>

          <div class="chart-card">
            <h3 class="chart-card__title">Agent 明细</h3>
            <div v-if="agentStats.length > 0" class="agent-table">
              <table>
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>会话</th>
                    <th>消息</th>
                    <th>成功率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in agentStats" :key="row.agent_id">
                    <td>{{ row.agent_name || shortId(row.agent_id) }}</td>
                    <td>{{ fmt(row.conversations) }}</td>
                    <td>{{ fmt(row.messages) }}</td>
                    <td>{{ percentOrDash(row.message_success_rate) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <EmptyState v-else icon="🤖" title="暂无 Agent 数据" description="窗口内没有 Agent 活动" />
          </div>
        </section>

        <!-- 元信息 -->
        <footer class="dashboard-meta">
          <span v-if="store">
            窗口：{{ store.range.start }} → {{ store.range.end }}
            <template v-if="options.filterActive">（已过滤：{{ activeFilterSummary }}）</template>
          </span>
          <span>
            更新于 {{ formatUpdatedAt(dashboardStore.lastUpdated) }}
            <template v-if="store?.cached"> · 缓存命中（TTL {{ store.cache_ttl_seconds }}s）</template>
          </span>
        </footer>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAnalyticsDashboardStore } from '@/stores/analyticsDashboard'
import { useAnalyticsOptionsStore } from '@/stores/analyticsOptions'
import { useAgentStore } from '@/stores/agent'
import type {
  AgentStat,
  ConversionOverview,
  MessagesOverview,
} from '@/api/analytics-types'
import KpiCard from '@/components/analytics/KpiCard.vue'
import FilterBar from '@/components/analytics/FilterBar.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'
import AgentActivityChart from '@/components/analytics/AgentActivityChart.vue'
import MessageStatusChart from '@/components/analytics/MessageStatusChart.vue'
import ConversionFunnelChart from '@/components/analytics/ConversionFunnelChart.vue'

const dashboardStore = useAnalyticsDashboardStore()
const options = useAnalyticsOptionsStore()
const agentStore = useAgentStore()

const store = computed(() => dashboardStore.overview)
const agentStats = computed<AgentStat[]>(() => store.value?.by_agent ?? [])
const messages = computed<MessagesOverview | null>(() => store.value?.messages ?? null)
const conversion = computed<ConversionOverview | null>(() => store.value?.conversion ?? null)

// ---- KPI 文本格式化 ----
const fmt = (n: number) => n.toLocaleString('en-US')

const avgMessagesHint = computed(() => {
  const avg = store.value?.conversations.avg_messages_per_new_conversation
  return avg === null || avg === undefined
    ? '暂无会话'
    : `每条新会话平均 ${avg.toFixed(1)} 条消息`
})

const successRateText = computed(() => {
  const rate = store.value?.messages.success_rate
  if (rate === null || rate === undefined) return '无已完成消息'
  return `成功率 ${(rate * 100).toFixed(1)}%`
})

const conversionRateText = computed(() => {
  const rate = store.value?.conversion.conversion_rate
  if (rate === null || rate === undefined) return ''
  return `${(rate * 100).toFixed(1)}%`
})

const percentOrDash = (v: number | null) =>
  v === null ? '—' : `${(v * 100).toFixed(1)}%`

// ---- 空态判定：无 Agent、无消息、无线索、无会话 → 视为空数据 ----
const isEmptyState = computed(() => {
  if (!store.value) return false
  const s = store.value
  return (
    s.agents.total === 0 &&
    s.messages.total === 0 &&
    s.conversations.new === 0 &&
    s.conversion.total_leads === 0
  )
})

const activeFilterSummary = computed(() => {
  const parts: string[] = []
  if (options.agentId) {
    const a = agentStore.agents.find((x) => x.id === options.agentId)
    parts.push(a?.name ?? `Agent ${shortId(options.agentId)}`)
  }
  if (options.channel) parts.push(`渠道 ${options.channel}`)
  return parts.join(' / ') || `近 ${options.days} 天`
})

const shortId = (id: string) => id.slice(0, 8)

function formatUpdatedAt(d: Date | null) {
  return d ? d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '—'
}

// ---- 数据流：视图 → store.fetchOverview()（读 options 过滤条件） ----
onMounted(() => {
  void options.loadAgents()
  void dashboardStore.fetchOverview()
})

function onApplyFilters() {
  // 过滤变化 → 强制刷新（options store 已被 FilterBar 直接修改）
  void dashboardStore.refresh()
}

// 窗口/过滤自动失效：options 变化时若已加载过则刷新
watch(
  () => [options.days, options.agentId, options.channel],
  () => {
    if (dashboardStore.hasLoaded) void dashboardStore.refresh()
  }
)
</script>

<style scoped>
.analytics-dashboard {
  max-width: 1200px;
  margin: 0 auto;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-5);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
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

.agent-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.agent-table th {
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  padding: var(--spacing-2);
  border-bottom: 1px solid var(--color-border);
}

.agent-table td {
  padding: var(--spacing-2);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
}

.agent-table tr:last-child td {
  border-bottom: none;
}

.dashboard-meta {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  padding: var(--spacing-3);
}

@media (max-width: 768px) {
  .kpi-grid,
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
