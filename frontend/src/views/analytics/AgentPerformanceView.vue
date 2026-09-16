<template>
  <div class="agent-perf">
    <PageHeader title="数据洞察 · Agent 效能">
      <template #actions>
        <button
          class="btn btn--ghost"
          :disabled="store.leaderboardLoading"
          @click="store.refresh()"
        >
          {{ store.leaderboardLoading ? '刷新中…' : '刷新' }}
        </button>
      </template>
    </PageHeader>

    <!-- 筛选条：时间范围（P6AN-07 range 预设）+ 状态 + 名称搜索 -->
    <div class="agent-perf__filters">
      <div class="filter-group">
        <label class="filter-group__label">时间范围</label>
        <select
          class="filter-group__select"
          :value="store.range"
          @change="onRangeChange"
        >
          <option
            v-for="r in AGENT_RANGE_OPTIONS"
            :key="r.value"
            :value="r.value"
          >
            {{ r.label }}
          </option>
        </select>
      </div>

      <div class="filter-group">
        <label class="filter-group__label">状态</label>
        <select
          class="filter-group__select"
          :value="store.status ?? ''"
          @change="onStatusChange"
        >
          <option value="">全部状态</option>
          <option value="active">active</option>
          <option value="inactive">inactive</option>
          <option value="paused">paused</option>
        </select>
      </div>

      <div class="filter-group">
        <label class="filter-group__label">名称</label>
        <input
          class="filter-group__input"
          placeholder="按名称模糊搜索"
          :value="store.keyword ?? ''"
          @change="onKeywordChange"
        />
      </div>
    </div>

    <!-- 错误条（保留旧数据降级展示 + 重试） -->
    <ErrorBanner
      v-if="store.leaderboardError"
      :message="store.leaderboardError"
      retryable
      @retry="store.refresh()"
    />

    <!-- 首次加载中：整页骨架 -->
    <LoadingState
      v-if="store.leaderboardLoading && !store.leaderboardHasLoaded"
      full-screen
      text="正在加载 Agent 排行榜…"
    />

    <template v-else>
      <EmptyState
        v-if="store.leaderboard === null"
        icon="🤖"
        title="暂无 Agent"
        description="还没有可用的 Agent 效能数据"
      />

      <div v-else class="leaderboard-card">
        <div class="leaderboard-card__meta">
          <span>共 {{ store.leaderboard.total_agents }} 个 Agent</span>
          <span>
            当前排序：{{ currentSortLabel }}（{{
              store.sortOrder === 'desc' ? '降序' : '升序'
            }}）
          </span>
        </div>

        <table class="leaderboard-table">
          <thead>
            <tr>
              <th class="leaderboard-table__rank">#</th>
              <th
                v-for="col in AGENT_SORT_COLUMNS"
                :key="col.key"
                class="leaderboard-table__sortable"
                :class="{ 'is-active': store.sortKey === col.key }"
                @click="store.toggleSort(col.key)"
              >
                {{ col.label }}
                <span v-if="store.sortKey === col.key" class="leaderboard-table__arrow">
                  {{ store.sortOrder === 'desc' ? '↓' : '↑' }}
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in store.leaderboard!.items"
              :key="row.agent_id"
              class="leaderboard-table__row"
              @click="openAgent(row.agent_id)"
            >
              <td class="leaderboard-table__rank">{{ rowRank(i) }}</td>
              <td>
                <div class="leaderboard-table__agent">
                  <span>{{ row.agent_name || shortId(row.agent_id) }}</span>
                  <span
                    v-if="row.status"
                    class="agent-status-chip"
                    :class="`agent-status-chip--${row.status}`"
                    >{{ row.status }}</span
                  >
                </div>
              </td>
              <td>{{ fmtNum(row.conversation_count) }}</td>
              <td>{{ fmtNum(row.message_count) }}</td>
              <td>{{ fmtNum(row.conversation_count + row.message_count) }}</td>
              <td>{{ rateText(row.conversion_rate, row.lead_count) }}</td>
              <td>{{ satisfactionText(row) }}</td>
              <td>
                {{ fmtNum(row.active_customers) }}
                <span class="leaderboard-table__dim">
                  / {{ fmtNum(row.total_customers) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>

        <p
          v-if="store.leaderboardIsEmpty(store.leaderboard)"
          class="leaderboard-card__hint"
        >
          窗口内所有 Agent 暂无活动数据（点击表头可切换排序指标）
        </p>

        <!-- 分页 -->
        <div class="pagination" v-if="store.leaderboard!.total_agents > store.pageSize">
          <button
            class="btn btn--ghost"
            :disabled="store.page <= 1"
            @click="store.setPage(store.page - 1)"
          >
            上一页
          </button>
          <span class="pagination-info">
            第 {{ store.page }} / {{ totalPages }} 页，共
            {{ store.leaderboard!.total_agents }} 条
          </span>
          <button
            class="btn btn--ghost"
            :disabled="store.page >= totalPages"
            @click="store.setPage(store.page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'
import {
  useAnalyticsAgentPerformanceStore,
  AGENT_SORT_COLUMNS,
  AGENT_RANGE_OPTIONS,
  formatAgentRate,
} from '@/stores/analyticsAgentPerformance'
import type {
  AgentPerformanceMetrics,
  AgentPerformanceRange,
} from '@/api/analytics-types'

const router = useRouter()
const store = useAnalyticsAgentPerformanceStore()

onMounted(() => {
  void store.fetchLeaderboard()
})

const totalPages = computed(() =>
  Math.max(
    1,
    Math.ceil((store.leaderboard?.total_agents ?? 0) / store.pageSize)
  )
)

const currentSortLabel = computed(() => {
  return (
    AGENT_SORT_COLUMNS.find((c) => c.key === store.sortKey)?.label ??
    store.sortKey
  )
})

/** 排名 = (当前页码 - 1) × 页大小 + 页内序号 */
function rowRank(indexInPage: number): number {
  return (store.page - 1) * store.pageSize + indexInPage + 1
}

// ---- 筛选条 ----
function onRangeChange(e: Event) {
  store.setRange((e.target as HTMLSelectElement).value as AgentPerformanceRange)
}

function onStatusChange(e: Event) {
  store.setStatusFilter((e.target as HTMLSelectElement).value || null)
}

function onKeywordChange(e: Event) {
  store.setKeyword((e.target as HTMLInputElement).value.trim() || null)
}

// ---- 格式化 ----
const fmtNum = (n: number) => n.toLocaleString('en-US')

function rateText(rate: number | null, leadCount: number): string {
  if (rate === null) return leadCount === 0 ? '无线索' : '—'
  return formatAgentRate(rate)
}

function satisfactionText(row: AgentPerformanceMetrics): string {
  if (row.satisfaction_proxy === null) {
    return row.satisfaction_sample > 0 ? '—' : '无情绪数据'
  }
  return `${(row.satisfaction_proxy * 100).toFixed(0)}%（n=${row.satisfaction_sample}）`
}

const shortId = (id: string) => id.slice(0, 8)

function openAgent(agentId: string) {
  void router.push(`/analytics/agents/${agentId}`)
}
</script>

<style scoped>
.agent-perf {
  max-width: 1200px;
  margin: 0 auto;
}

.agent-perf__filters {
  display: flex;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin-bottom: var(--spacing-5);
}

.filter-group {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.filter-group__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
}

.filter-group__select,
.filter-group__input {
  min-width: 140px;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
}

.filter-group__select {
  cursor: pointer;
}

.filter-group__select:focus,
.filter-group__input:focus {
  outline: none;
  border-color: var(--color-primary);
}

.leaderboard-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
}

.leaderboard-card__meta {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--spacing-3);
}

.leaderboard-card__hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-3);
}

.leaderboard-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}

.leaderboard-table th {
  text-align: left;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  padding: var(--spacing-2);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.leaderboard-table__sortable {
  cursor: pointer;
  user-select: none;
}

.leaderboard-table__sortable:hover {
  color: var(--color-text-primary);
}

.leaderboard-table__sortable.is-active {
  color: var(--color-primary);
}

.leaderboard-table__arrow {
  margin-left: 2px;
}

.leaderboard-table td {
  padding: var(--spacing-2);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.leaderboard-table__row {
  cursor: pointer;
}

.leaderboard-table__row:hover td {
  background: var(--color-bg-secondary);
}

.leaderboard-table__row:last-child td {
  border-bottom: none;
}

.leaderboard-table__rank {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-muted);
  width: 32px;
}

.leaderboard-table__agent {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.leaderboard-table__dim {
  color: var(--color-text-muted);
}

.agent-status-chip {
  font-size: var(--font-size-xs);
  padding: 1px var(--spacing-2);
  border-radius: var(--radius-full, 999px);
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

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-3);
  margin-top: var(--spacing-4);
}

.pagination-info {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}
</style>
