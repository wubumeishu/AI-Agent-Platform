<template>
  <Modal :title="`版本历史${templateName ? ' · ' + templateName : ''}`" @close="emit('close')">
    <!-- 加载态 -->
    <div v-if="loading" class="pv-loading">
      <LoadingState text="加载版本历史..." />
    </div>

    <!-- 错误态 / 后端未就绪 -->
    <div v-else-if="error" class="pv-note">
      <div class="pv-note__icon">🚧</div>
      <h3>版本历史服务即将上线</h3>
      <p>版本管理 API 尚未就绪（等待后端 P1-002-D 版本 API）。服务上线后此面板将自动可用。</p>
      <p v-if="errorText" class="pv-note__error">{{ errorText }}</p>
      <button class="btn btn--ghost" @click="loadVersions()">重新加载</button>
    </div>

    <!-- 空态 -->
    <div v-else-if="!versions.length" class="pv-empty">
      <EmptyState icon="📭" title="暂无版本记录" description="保存模板内容时会自动生成版本。" />
    </div>

    <template v-else>
      <!-- 版本列表（时间倒序，行高 48px） -->
      <div class="pv-section">
        <h4 class="pv-section__title">版本列表</h4>
        <div class="pv-list">
          <div
            v-for="v in versions"
            :key="v.version"
            class="pv-item"
            :class="{ 'pv-item--active': selectedVersion === v.version }"
            @click="selectVersion(v)"
          >
            <div class="pv-item__head">
              <span class="pv-item__ver">v{{ v.version }}</span>
              <span class="pv-item__time">{{ formatTime(v.changed_at) }}</span>
              <span class="pv-item__by">{{ v.changed_by }}</span>
              <span v-if="v.change_note" class="pv-item__note" :title="v.change_note">{{ v.change_note }}</span>
              <button
                v-if="v.version !== latestVersion"
                class="pv-item__rollback"
                :disabled="rollingBack"
                @click.stop="askRollback(v)"
              >
                回滚
              </button>
            </div>
            <!-- 点击行展开的详情 -->
            <div v-if="expandedVersion === v.version" class="pv-item__detail">
              <div class="pv-item__detail-label">内容快照</div>
              <pre class="pv-item__detail-content">{{ v.content }}</pre>
              <div v-if="v.variables.length" class="pv-item__detail-label">变量（{{ v.variables.length }}）</div>
              <ul v-if="v.variables.length" class="pv-item__detail-vars">
                <li v-for="varDef in v.variables" :key="varDef.name">
                  <code>{{ varDef.name }}</code>
                  <span v-if="varDef.required" class="pv-var-required">必填</span>
                  <span v-if="varDef.defaultValue !== undefined" class="pv-var-default">默认: {{ varDef.defaultValue }}</span>
                  <span v-if="varDef.description" class="pv-var-desc">{{ varDef.description }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      <!-- 版本对比 -->
      <div class="pv-section">
        <h4 class="pv-section__title">版本对比</h4>
        <div class="pv-compare-bar">
          <label class="pv-compare-field">
            <span class="pv-compare-label">从</span>
            <select v-model.number="fromVersion" class="pv-compare-select">
              <option v-for="v in versions" :key="v.version" :value="v.version">
                v{{ v.version }} · {{ formatTime(v.changed_at) }}
              </option>
            </select>
          </label>
          <label class="pv-compare-field">
            <span class="pv-compare-label">到</span>
            <select v-model.number="toVersion" class="pv-compare-select">
              <option v-for="v in versions" :key="v.version" :value="v.version">
                v{{ v.version }} · {{ formatTime(v.changed_at) }}
              </option>
            </select>
          </label>
          <button
            class="btn btn--primary btn--sm"
            :disabled="!canCompare || comparing"
            @click="runCompare()"
          >
            {{ comparing ? '对比中...' : '对比' }}
          </button>
        </div>

        <div v-if="compareError" class="pv-compare-error">{{ compareError }}</div>

        <PromptDiffViewer v-if="diffLines !== null" :lines="diffLines" />
      </div>
    </template>

    <template #footer>
      <button
        v-if="selectedVersion !== null && selectedVersion !== latestVersion"
        class="btn btn--primary"
        :disabled="rollingBack"
        @click="askRollback(versions.find((v) => v.version === selectedVersion))"
      >
        {{ rollingBack ? '回滚中...' : `回滚到 v${selectedVersion}` }}
      </button>
      <button class="btn btn--ghost" @click="emit('close')">关闭</button>
    </template>

    <!-- 回滚确认弹层 -->
    <div v-if="rollbackTarget !== null" class="pv-confirm-overlay" @click.self="rollbackTarget = null">
      <div class="pv-confirm">
        <h4 class="pv-confirm__title">确认回滚</h4>
        <p class="pv-confirm__body">
          回滚到 <strong>v{{ rollbackTarget }}</strong> 将以该版本内容创建新版本
          <strong>v{{ latestVersion + 1 }}</strong>，当前内容不会被删除。
        </p>
        <div class="pv-confirm__actions">
          <button class="btn btn--ghost" @click="rollbackTarget = null">取消</button>
          <button class="btn btn--danger" :disabled="rollingBack" @click="confirmRollback()">
            {{ rollingBack ? '回滚中...' : '确认回滚' }}
          </button>
        </div>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Modal from '../common/Modal.vue'
import LoadingState from '../common/LoadingState.vue'
import EmptyState from '../common/EmptyState.vue'
import PromptDiffViewer from './PromptDiffViewer.vue'
import { promptApi as apiImpl } from '@/api/prompt'
import { diffLines as computeDiff } from '@/utils/diff'
import type { PromptTemplateVersion, DiffLine } from '@/api/types'

const props = defineProps<{
  templateId: string
  templateName?: string
  /** 可注入 API 客户端（默认生产 promptApi；demo/验收场景可注入 mock） */
  apiClient?: {
    versions: (id: string) => Promise<PromptTemplateVersion[]>
    rollback: (id: string, version: number) => Promise<unknown>
  }
}>()

const PromptApiClientType = {
  versions: (_id: string) => Promise.resolve([] as PromptTemplateVersion[]),
  rollback: (_id: string, _version: number) => Promise.resolve(null as unknown),
}
const promptApi =
  props.apiClient ?? (apiImpl as unknown as typeof PromptApiClientType)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'rolled-back'): void
}>()

// ===== 版本列表 =====
const versions = ref<PromptTemplateVersion[]>([])
const loading = ref(false)
const error = ref(false)
const errorText = ref('')
const rollingBack = ref(false)

// 时间倒序
const sortedVersions = computed(() =>
  [...versions.value].sort((a, b) => b.version - a.version),
)

const latestVersion = computed(() =>
  Math.max(0, ...versions.value.map((v) => v.version)),
)

async function loadVersions() {
  loading.value = true
  error.value = false
  errorText.value = ''
  try {
    const list = await promptApi.versions(props.templateId)
    versions.value = [...list].sort((a, b) => b.version - a.version)
  } catch (err) {
    error.value = true
    errorText.value = err instanceof Error ? err.message : '加载失败'
    versions.value = []
  } finally {
    loading.value = false
  }
}

// ===== 点击行查看详情 =====
const selectedVersion = ref<number | null>(null)
const expandedVersion = ref<number | null>(null)

function selectVersion(v: PromptTemplateVersion) {
  selectedVersion.value = v.version
  expandedVersion.value = expandedVersion.value === v.version ? null : v.version
}

// ===== 版本对比 =====
const fromVersion = ref(0)
const toVersion = ref(0)
const comparing = ref(false)
const compareError = ref('')
const diffLinesResult = ref<DiffLine[] | null>(null)

const diffLines = computed(() => diffLinesResult.value)

const canCompare = computed(() => {
  if (versions.value.length < 2) return false
  if (!fromVersion.value || !toVersion.value) return false
  if (fromVersion.value === toVersion.value) return false
  return true
})

watch(versions, (list) => {
  if (list.length) {
    const desc = [...list].sort((a, b) => b.version - a.version)
    const oldest = desc[desc.length - 1]
    const newest = desc[0]
    if (oldest) fromVersion.value = oldest.version // 最早
    if (newest) toVersion.value = newest.version // 最新
  }
}, { immediate: true })

function runCompare() {
  compareError.value = ''
  const from = versions.value.find((v) => v.version === fromVersion.value)
  const to = versions.value.find((v) => v.version === toVersion.value)
  if (!from || !to) {
    compareError.value = '请选择两个版本进行对比'
    return
  }
  comparing.value = true
  // 本地计算 diff（内容已在版本列表中）；方向固定为 旧→新
  const [older, newer] = from.version <= to.version ? [from, to] : [to, from]
  diffLinesResult.value = computeDiff(older.content, newer.content)
  comparing.value = false
}

// ===== 回滚 =====
const rollbackTarget = ref<number | null>(null)

function askRollback(v: PromptTemplateVersion | undefined) {
  if (!v) return
  rollbackTarget.value = v.version
}

async function confirmRollback() {
  if (rollbackTarget.value === null) return
  rollingBack.value = true
  try {
    await promptApi.rollback(props.templateId, rollbackTarget.value)
    rollbackTarget.value = null
    emit('rolled-back')
    await loadVersions()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : '回滚失败'
  } finally {
    rollingBack.value = false
  }
}

// ===== 工具 =====
function formatTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

watch(() => props.templateId, loadVersions, { immediate: true })

// 暴露给父级
defineExpose({ loadVersions })
</script>

<style scoped>
.pv-loading {
  padding: var(--spacing-8) 0;
}

/* 后端未就绪 / 错误占位 */
.pv-note {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-6) var(--spacing-4);
  text-align: center;
  color: var(--color-text-secondary);
}

.pv-note__icon {
  font-size: 32px;
}

.pv-note h3 {
  margin: 0;
  font-size: var(--font-size-lg);
  color: var(--color-text-primary);
}

.pv-note p {
  margin: 0;
  font-size: var(--font-size-sm);
  max-width: 360px;
}

.pv-note__error {
  color: var(--color-error);
  font-size: var(--font-size-xs);
}

.pv-empty {
  padding: var(--spacing-4) 0;
}

.pv-section {
  margin-bottom: var(--spacing-5);
}

.pv-section__title {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* 版本列表：行高 48px */
.pv-list {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.pv-item {
  min-height: 48px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: var(--spacing-1) var(--spacing-3);
  cursor: pointer;
  border-bottom: 1px solid var(--color-border);
  transition: background var(--transition-fast);
  background: var(--color-bg-primary);
}

.pv-item:last-child {
  border-bottom: none;
}

.pv-item:hover {
  background: var(--color-bg-tertiary);
}

.pv-item--active {
  background: var(--color-primary-light);
}

.pv-item__head {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  min-height: 48px;
}

.pv-item__ver {
  flex: 0 0 36px;
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}

.pv-item__time {
  flex: 0 0 130px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
}

.pv-item__by {
  flex: 0 0 60px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.pv-item__note {
  flex: 1;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pv-item__rollback {
  flex: 0 0 auto;
  padding: 2px 8px;
  font-size: var(--font-size-xs);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.pv-item__rollback:hover:not(:disabled) {
  border-color: var(--color-error);
  color: var(--color-error);
  background: var(--color-error-light);
}

.pv-item__rollback:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 行详情展开区 */
.pv-item__detail {
  padding: var(--spacing-2) 0 var(--spacing-3) 36px;
}

.pv-item__detail-label {
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
  margin: var(--spacing-1) 0;
}

.pv-item__detail-content {
  margin: 0;
  padding: var(--spacing-2) var(--spacing-3);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

.pv-item__detail-vars {
  margin: 0;
  padding-left: 16px;
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pv-item__detail-vars code {
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

.pv-var-required {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: 11px;
}

.pv-var-default {
  margin-left: 6px;
  opacity: 0.8;
}

.pv-var-desc {
  margin-left: 6px;
  opacity: 0.7;
}

/* 对比工具条 */
.pv-compare-bar {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  flex-wrap: wrap;
  margin-bottom: var(--spacing-2);
}

.pv-compare-field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pv-compare-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
}

.pv-compare-select {
  min-width: 190px;
  padding: var(--spacing-1) var(--spacing-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-xs);
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
}

.pv-compare-select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.pv-compare-error {
  padding: var(--spacing-2) var(--spacing-3);
  border-radius: var(--radius-md);
  background: var(--color-error-light);
  color: var(--color-error);
  font-size: var(--font-size-xs);
  margin-bottom: var(--spacing-2);
}

/* 回滚确认弹层 */
.pv-confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
  padding: var(--spacing-4);
}

.pv-confirm {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  width: 100%;
  max-width: 420px;
  padding: var(--spacing-5);
}

.pv-confirm__title {
  margin: 0 0 var(--spacing-2);
  font-size: var(--font-size-lg);
}

.pv-confirm__body {
  margin: 0 0 var(--spacing-4);
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.pv-confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-2);
}
</style>
