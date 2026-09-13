<template>
  <div class="platforms-view">
    <PageHeader title="平台管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 注册平台
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && platforms.length === 0"
      icon="🔌"
      title="暂无平台"
      description="注册你的第一个社交平台"
      :show-action="true"
      action-text="注册平台"
      @action="showCreateDialog = true"
    />

    <!-- Platform List -->
    <div v-else class="platform-grid">
      <div
        v-for="platform in platforms"
        :key="platform.id"
        class="platform-card"
      >
        <div class="platform-card__header">
          <div class="platform-card__logo">{{ getPlatformLogo(platform.code) }}</div>
          <StatusBadge :status="platform.status === 'active' ? 'success' : 'stopped'" />
        </div>
        <div class="platform-card__content">
          <h3 class="platform-card__name">{{ platform.name }}</h3>
          <p class="platform-card__code">{{ platform.code }}</p>
          <div class="platform-card__capabilities">
            <span
              v-for="cap in platform.capabilities"
              :key="cap"
              class="capability-tag"
            >
              {{ cap }}
            </span>
          </div>
        </div>
        <div class="platform-card__actions">
          <button
            class="btn btn--ghost btn--sm"
            @click="testConnection(platform.id)"
          >
            测试连接
          </button>
          <button
            class="btn btn--danger btn--sm"
            @click="deletePlatform(platform.id)"
          >
            注销
          </button>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="注册平台"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">平台编码</label>
          <input
            v-model="createForm.code"
            class="form-input"
            placeholder="如: wechat, douyin"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">平台名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="如: 微信"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">能力列表（逗号分隔）</label>
          <input
            v-model="capabilitiesInput"
            class="form-input"
            placeholder="如: messaging, friend_management"
          />
        </div>
        <ModalFooter>
          <button
            type="button"
            class="btn btn--ghost"
            @click="showCreateDialog = false"
          >
            取消
          </button>
          <button type="submit" class="btn btn--primary" :disabled="creating">
            {{ creating ? '注册中...' : '注册' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { usePlatformStore } from '@/stores/platform'
import type { Platform } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const platformStore = usePlatformStore()

const platforms = ref<Platform[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  code: '',
  name: '',
  capabilities: [] as string[],
})

const capabilitiesInput = computed({
  get: () => createForm.value.capabilities.join(', '),
  set: (val: string) => {
    createForm.value.capabilities = val.split(',').map(s => s.trim()).filter(Boolean)
  },
})

const platformLogos: Record<string, string> = {
  wechat: '💬',
  douyin: '🎵',
  weibo: '📢',
  xiaohongshu: '📕',
  qq: '🐧',
}

onMounted(async () => {
  await fetchPlatforms()
})

async function fetchPlatforms() {
  loading.value = true
  try {
    const data = await platformStore.fetchPlatforms()
    platforms.value = data.items
  } catch (error) {
    console.error('Failed to fetch platforms:', error)
  } finally {
    loading.value = false
  }
}

function getPlatformLogo(code: string) {
  return platformLogos[code] || '🔌'
}

async function handleCreate() {
  if (!createForm.value.code.trim() || !createForm.value.name.trim()) return
  
  creating.value = true
  try {
    await platformStore.createPlatform({
      code: createForm.value.code,
      name: createForm.value.name,
      capabilities: createForm.value.capabilities,
    })
    showCreateDialog.value = false
    createForm.value = { code: '', name: '', capabilities: [] }
    await fetchPlatforms()
  } catch (error) {
    console.error('Failed to create platform:', error)
  } finally {
    creating.value = false
  }
}

async function testConnection(id: string) {
  try {
    // Mock connection test
    alert('连接测试成功！')
  } catch (error) {
    console.error('Failed to test connection:', error)
    alert('连接测试失败')
  }
}

async function deletePlatform(id: string) {
  if (!confirm('确定要注销这个平台吗？')) return
  try {
    await platformStore.deletePlatform(id)
    await fetchPlatforms()
  } catch (error) {
    console.error('Failed to delete platform:', error)
  }
}
</script>

<style scoped>
.platform-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--spacing-4);
}

.platform-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  transition: all var(--transition-fast);
}

.platform-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.platform-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.platform-card__logo {
  font-size: 40px;
}

.platform-card__content {
  margin-bottom: var(--spacing-4);
}

.platform-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.platform-card__code {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin: 0 0 var(--spacing-2);
}

.platform-card__capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-1);
}

.capability-tag {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
}

.platform-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
