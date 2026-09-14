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
      <PlatformCard
        v-for="platform in platforms"
        :key="platform.id"
        :platform="platform"
        @test="testConnection(platform.id)"
        @delete="deletePlatform(platform.id)"
      />
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
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'
import PlatformCard from '@/components/platform/PlatformCard.vue'

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
    console.log('连接测试成功！')
  } catch (error) {
    console.error('Failed to test connection:', error)
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
</style>
