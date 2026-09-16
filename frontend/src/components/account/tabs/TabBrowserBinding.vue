<template>
  <Card>
    <template #header>
      <div class="tab-header">
        <h3>绑定 Browser Profile</h3>
        <button class="btn btn--primary btn--sm" @click="showBindDialog = true">
          + 绑定 Profile
        </button>
      </div>
    </template>
    
    <!-- Provider Status -->
    <div v-if="providerStatus" class="provider-status">
      <span class="provider-status__icon">🌐</span>
      <span>BitBrowser: {{ providerStatus.profiles_count }} 个 Profile</span>
    </div>
    
    <div v-if="bindings.length === 0" class="empty-binding">
      <p class="text-muted">暂无绑定的 Browser Profile</p>
    </div>
    
    <div v-else class="binding-list">
      <div
        v-for="binding in bindings"
        :key="binding.profile_id"
        class="binding-item"
      >
        <div class="binding-item__info">
          <span class="binding-item__icon">🌐</span>
          <div>
            <p class="binding-item__name">{{ binding.profile_name }}</p>
            <p class="binding-item__id">ID: {{ binding.profile_id }}</p>
          </div>
        </div>
        <button class="btn btn--ghost btn--sm" @click="removeBinding(binding.profile_id)">
          解除绑定
        </button>
      </div>
    </div>

    <!-- Bind Dialog -->
    <Modal
      v-if="showBindDialog"
      title="绑定 Browser Profile"
      @close="showBindDialog = false"
    >
      <div class="form-group">
        <label class="form-label">选择 Profile</label>
        <select v-model="selectedProfileId" class="form-select" required>
          <option value="" disabled>请选择 Profile</option>
          <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
            {{ profile.name || '未命名 Profile' }}
          </option>
        </select>
      </div>
      <ModalFooter>
        <button class="btn btn--ghost" @click="showBindDialog = false">取消</button>
        <button class="btn btn--primary" :disabled="!selectedProfileId" @click="bindProfile">
          确认绑定
        </button>
      </ModalFooter>
    </Modal>
  </Card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useBrowserStore } from '@/stores/browser'
import type { BrowserProfile, BrowserProviderStatus } from '@/api/types'
import Card from '@/components/common/Card.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

defineProps<{
  accountId: string
}>()

const browserStore = useBrowserStore()
const profiles = ref<BrowserProfile[]>([])
const providerStatus = ref<BrowserProviderStatus | null>(null)
const bindings = ref<any[]>([])
const showBindDialog = ref(false)
const selectedProfileId = ref('')

onMounted(async () => {
  await Promise.all([
    fetchProfiles(),
    fetchProviderStatus(),
  ])
})

async function fetchProfiles() {
  try {
    const data = await browserStore.fetchProfiles()
    profiles.value = data.items
  } catch (error) {
    console.error('Failed to fetch profiles:', error)
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

async function bindProfile() {
  if (!selectedProfileId.value) return
  
  const profile = profiles.value.find(p => p.id === selectedProfileId.value)
  if (profile) {
    bindings.value.push({
      profile_id: profile.id,
      profile_name: profile.name || '未命名 Profile',
    })
    showBindDialog.value = false
    selectedProfileId.value = ''
  }
}

async function removeBinding(profileId: string) {
  bindings.value = bindings.value.filter(b => b.profile_id !== profileId)
}
</script>

<style scoped>
.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.provider-status {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3);
  background: var(--color-success-light);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-4);
  font-size: var(--font-size-sm);
}

.provider-status__icon {
  font-size: 20px;
}

.empty-binding {
  padding: var(--spacing-8) 0;
  text-align: center;
}

.binding-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.binding-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3);
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.binding-item__info {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
}

.binding-item__icon {
  font-size: 24px;
}

.binding-item__name {
  margin: 0 0 var(--spacing-1);
  font-weight: var(--font-weight-medium);
}

.binding-item__id {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-family: monospace;
}

.text-muted {
  color: var(--color-text-muted);
}
</style>
