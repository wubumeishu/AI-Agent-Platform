<template>
  <div class="experiments-view">
    <PageHeader title="数据洞察 · 实验">
      <template #actions>
        <button
          class="btn btn--primary"
          @click="openCreate()"
        >
          + 新建实验
        </button>
      </template>
    </PageHeader>

    <!-- 状态过滤 -->
    <div class="exp-filter">
      <label class="exp-filter__label">状态</label>
      <select
        class="exp-filter__select"
        :value="store.statusFilter ?? ''"
        @change="onFilterChange"
      >
        <option value="">全部状态</option>
        <option
          v-for="s in EXPERIMENT_STATUSES"
          :key="s"
          :value="s"
        >
          {{ experimentStatusLabel(s) }}
        </option>
      </select>
    </div>

    <!-- 错误条（保留旧数据降级展示 + 重试） -->
    <ErrorBanner
      v-if="store.error"
      :message="store.error"
      retryable
      @retry="store.refresh()"
    />

    <LoadingState
      v-if="store.loading && !store.hasLoaded"
      full-screen
      text="正在加载实验…"
    />

    <template v-else>
      <EmptyState
        v-if="store.experiments.length === 0"
        icon="🧪"
        title="暂无实验"
        description="还没有 A/B 实验。新建一个实验开始对比变组效果。"
        :show-action="true"
        action-text="新建实验"
        @action="openCreate()"
      />

      <!-- 实验列表 -->
      <div v-else class="exp-list">
        <div
          v-for="exp in store.experiments"
          :key="exp.id"
          class="exp-card"
          @click="openDetail(exp.id)"
        >
          <div class="exp-card__top">
            <span class="exp-card__code">{{ exp.code }}</span>
            <span
              class="exp-card__status"
              :style="{ color: experimentStatusColor(exp.status), borderColor: experimentStatusColor(exp.status) }"
            >
              {{ experimentStatusLabel(exp.status) }}
            </span>
            <button
              class="btn btn--ghost btn--sm exp-card__edit"
              @click.stop="openEdit(exp)"
            >
              编辑
            </button>
          </div>
          <h3 class="exp-card__name">{{ exp.name }}</h3>
          <p v-if="exp.description" class="exp-card__desc">
            {{ exp.description }}
          </p>
          <div class="exp-card__meta">
            <span>
              变组 × {{ exp.variants?.length ?? 0 }}
              <template
                v-if="
                  exp.variants?.some(
                    (v) => typeof v.share === 'number'
                  )
                "
              >
                · 有份额
              </template>
            </span>
            <span v-if="exp.owner">负责人：{{ exp.owner }}</span>
            <span>创建：{{ fmtDate(exp.created_at) }}</span>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="store.totalPages > 1" class="pagination">
          <button
            class="btn btn--ghost"
            :disabled="store.page <= 1"
            @click="store.setPage(store.page - 1)"
          >
            上一页
          </button>
          <span class="pagination-info">
            第 {{ store.page }} / {{ store.totalPages }} 页，共
            {{ store.total }} 条
          </span>
          <button
            class="btn btn--ghost"
            :disabled="store.page >= store.totalPages"
            @click="store.setPage(store.page + 1)"
          >
            下一页
          </button>
        </div>
      </div>
    </template>

    <!-- 创建 / 编辑弹窗 -->
    <Modal
      v-if="modalOpen"
      :title="editing ? '编辑实验' : '新建实验'"
      :width="'680px'"
      @close="closeModal"
    >
      <ExperimentForm
        :experiment="editing ?? undefined"
        :saving="store.saving"
        :form-error="formError"
        @cancel="closeModal"
        @submit="onSubmit"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import ErrorBanner from '@/components/analytics/ErrorBanner.vue'
import ExperimentForm from '@/components/analytics/ExperimentForm.vue'
import {
  useAnalyticsExperimentStore,
  EXPERIMENT_STATUSES,
  experimentStatusLabel,
  experimentStatusColor,
} from '@/stores/analyticsExperiment'
import type {
  Experiment,
  ExperimentCreate,
  ExperimentUpdate,
} from '@/api/analytics-types'

const router = useRouter()
const store = useAnalyticsExperimentStore()

// ---- 弹窗状态 ----
const modalOpen = ref(false)
const editing = ref<Experiment | null>(null)
const formError = ref<string | null>(null)

function openCreate() {
  editing.value = null
  formError.value = null
  modalOpen.value = true
}

function openEdit(exp: Experiment) {
  editing.value = exp
  formError.value = null
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false
  editing.value = null
  formError.value = null
}

async function onSubmit(payload: ExperimentCreate | ExperimentUpdate) {
  let ok = false
  if (editing.value) {
    const res = await store.updateExperiment(
      editing.value.id,
      payload as ExperimentUpdate
    )
    ok = res !== null
    formError.value = store.error
  } else {
    const res = await store.createExperiment(
      payload as ExperimentCreate
    )
    ok = res !== null
    formError.value = store.error
  }
  if (ok) {
    closeModal()
  }
}

function openDetail(id: string) {
  void router.push(`/analytics/experiments/${id}`)
}

function onFilterChange(e: Event) {
  store.setStatusFilter((e.target as HTMLSelectElement).value || null)
}

function fmtDate(iso: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('zh-CN')
}

onMounted(() => {
  void store.fetchList()
})
</script>

<style scoped>
.experiments-view {
  max-width: 1100px;
  margin: 0 auto;
}

.exp-filter {
  display: flex;
  align-items: flex-end;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  margin-bottom: var(--spacing-5);
}

.exp-filter__label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
}

.exp-filter__select {
  min-width: 140px;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.exp-filter__select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.exp-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
}

.exp-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4) var(--spacing-5);
  cursor: pointer;
  transition: border-color var(--transition-fast);
}

.exp-card:hover {
  border-color: var(--color-primary);
}

.exp-card__top {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.exp-card__code {
  font-size: var(--font-size-xs);
  font-family: monospace;
  color: var(--color-text-muted);
  background: var(--color-bg-secondary);
  padding: 1px var(--spacing-2);
  border-radius: var(--radius-md);
}

.exp-card__status {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  padding: 1px var(--spacing-2);
  border: 1px solid;
  border-radius: 999px;
}

.exp-card__edit {
  margin-left: auto;
}

.exp-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: var(--spacing-2) 0 0;
}

.exp-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: var(--spacing-2) 0 0;
}

.exp-card__meta {
  display: flex;
  gap: var(--spacing-4);
  flex-wrap: wrap;
  margin-top: var(--spacing-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
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
