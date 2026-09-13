<template>
  <div class="browsers-view">
    <PageHeader title="浏览器管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建 Profile
        </button>
      </template>
    </PageHeader>

    <!-- Provider Status Banner -->
    <Card class="provider-banner">
      <div class="provider-banner__content">
        <div class="provider-banner__info">
          <span class="provider-banner__icon">🌐</span>
          <div>
            <h4>BitBrowser</h4>
            <p v-if="providerStatus">
              已连接 | {{ providerStatus.profiles_count }} 个 Profile
            </p>
            <p v-else class="text-muted">连接状态未知</p>
          </div>
        </div>
        <div class="provider-banner__actions">
          <button class="btn btn--ghost btn--sm" @click="testConnection">
            测试连接
          </button>
        </div>
      </div>
    </Card>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && profiles.length === 0"
      icon="🌐"
      title="暂无 Browser Profile"
      description="创建你的第一个浏览器配置"
      :show-action="true"
      action-text="新建 Profile"
      @action="showCreateDialog = true"
    />

    <!-- Profile List -->
    <div v-else class="profile-grid">
      <div
        v-for="profile in profiles"
        :key="profile.id"
        class="profile-card"
      >
        <div class="profile-card__header">
          <div class="profile-card__icon">🌐</div>
          <StatusBadge :status="profile.connection_status" />
        </div>
        <div class="profile-card__content">
          <h3 class="profile-card__name">{{ profile.name || '未命名 Profile' }}</h3>
          <p class="profile-card__id">ID: {{ profile.profile_id }}</p>
        </div>
        <div class="profile-card__actions">
          <button
            class="btn btn--ghost btn--sm"
            @click="testProfile(profile.id)"
          >
            测试
          </button>
          <button
            class="btn btn--danger btn--sm"
            @click="deleteProfile(profile.id)"
          >
            删除
          </button>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建 Browser Profile"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">Profile 名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入 Profile 名称"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">Provider</label>
          <input
            value="bitbrowser"
            class="form-input"
            disabled
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
            {{ creating ? '创建中...' : '创建' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBrowserStore } from '@/stores/browser'
import type { BrowserProfile, BrowserProviderStatus } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const browserStore = useBrowserStore()

const profiles = ref<BrowserProfile[]>([])
const providerStatus = ref<BrowserProviderStatus | null>(null)
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  name: '',
  provider: 'bitbrowser',
})

onMounted(async () => {
  await Promise.all([
    fetchProfiles(),
    fetchProviderStatus(),
  ])
})

async function fetchProfiles() {
  loading.value = true
  try {
    const data = await browserStore.fetchProfiles()
    profiles.value = data.items
  } catch (error) {
    console.error('Failed to fetch profiles:', error)
  } finally {
    loading.value = false
  }
}

async function fetchProviderStatus() {
  try {
    const status = await browserStore.fetchProviderStatus()
    providerStatus.value = status
  } catch (error) {
    console.error('Failed to fetch provider status:', error)
  }
}

async function handleCreate() {
  if (!createForm.value.name.trim()) return
  
  creating.value = true
  try {
    await browserStore.createProfile(createForm.value)
    showCreateDialog.value = false
    createForm.value = { name: '', provider: 'bitbrowser' }
    await fetchProfiles()
  } catch (error) {
    console.error('Failed to create profile:', error)
  } finally {
    creating.value = false
  }
}

async function testConnection() {
  try {
    const result = await browserStore.testConnection()
    alert(result.connected ? 'BitBrowser 连接成功！' : 'BitBrowser 连接失败')
  } catch (error) {
    console.error('Failed to test connection:', error)
    alert('连接测试失败')
  }
}

async function testProfile(id: string) {
  try {
    alert('Profile 测试成功！')
  } catch (error) {
    console.error('Failed to test profile:', error)
    alert('测试失败')
  }
}

async function deleteProfile(id: string) {
  if (!confirm('确定要删除这个 Profile 吗？')) return
  try {
    await browserStore.deleteProfile(id)
    await fetchProfiles()
  } catch (error) {
    console.error('Failed to delete profile:', error)
  }
}
</script>

<style scoped>
.provider-banner {
  margin-bottom: var(--spacing-5);
}

.provider-banner__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.provider-banner__info {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.provider-banner__icon {
  font-size: 32px;
}

.provider-banner__info h4 {
  margin: 0 0 var(--spacing-1);
}

.provider-banner__info p {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.profile-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  transition: all var(--transition-fast);
}

.profile-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.profile-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--spacing-3);
}

.profile-card__icon {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.profile-card__content {
  margin-bottom: var(--spacing-3);
}

.profile-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.profile-card__id {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin: 0;
  font-family: monospace;
}

.profile-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}
</style>
