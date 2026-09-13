<template>
  <div class="proxy-view">
    <PageHeader title="代理管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建代理
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && proxies.length === 0"
      icon="🔀"
      title="暂无代理"
      description="添加你的网络代理配置"
      :show-action="true"
      action-text="新建代理"
      @action="showCreateDialog = true"
    />

    <!-- Proxy List -->
    <div v-else class="proxy-list">
      <div
        v-for="proxy in proxies"
        :key="proxy.id"
        class="proxy-card"
      >
        <div class="proxy-card__left">
          <div class="proxy-card__type">
            <StatusBadge
              :status="(proxy.type === 'http' || proxy.type === 'https' ? 'info' : 'warning') as any"
              :label="proxy.type.toUpperCase()"
            />
          </div>
          <div class="proxy-card__address">
            <span class="proxy-card__host">{{ proxy.host }}</span>
            <span class="proxy-card__port">:{{ proxy.port }}</span>
          </div>
          <div class="proxy-card__name">{{ proxy.name }}</div>
        </div>
        <div class="proxy-card__right">
          <StatusBadge :status="(proxy.status === 'active' ? 'success' : proxy.status === 'failed' ? 'error' : 'stopped') as any" />
          <div class="proxy-card__actions">
            <button
              class="btn btn--ghost btn--sm"
              @click="testConnection(proxy.id)"
            >
              测试
            </button>
            <button
              class="btn btn--danger btn--sm"
              @click="deleteProxy(proxy.id)"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建代理"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">代理名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入代理名称"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">代理类型</label>
          <select v-model="createForm.type" class="form-select" required>
            <option value="http">HTTP</option>
            <option value="https">HTTPS</option>
            <option value="socks5">SOCKS5</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">主机地址</label>
          <input
            v-model="createForm.host"
            class="form-input"
            placeholder="如: proxy.example.com"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">端口</label>
          <input
            v-model.number="createForm.port"
            type="number"
            class="form-input"
            placeholder="如: 7890"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">用户名（可选）</label>
          <input
            v-model="createForm.username"
            class="form-input"
            placeholder="如有认证请填写"
          />
        </div>
        <div class="form-group">
          <label class="form-label">密码（可选）</label>
          <input
            v-model="createForm.password"
            type="password"
            class="form-input"
            placeholder="如有认证请填写"
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
import { useProxyStore } from '@/stores/proxy'
import type { Proxy } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const proxyStore = useProxyStore()

const proxies = ref<Proxy[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  name: '',
  type: 'http' as 'http' | 'https' | 'socks5',
  host: '',
  port: 7890,
  username: '',
  password: '',
})

onMounted(async () => {
  await fetchProxies()
})

async function fetchProxies() {
  loading.value = true
  try {
    const data = await proxyStore.fetchProxies()
    proxies.value = data.items
  } catch (error) {
    console.error('Failed to fetch proxies:', error)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!createForm.value.name.trim() || !createForm.value.host.trim()) return
  
  creating.value = true
  try {
    await proxyStore.createProxy({
      ...createForm.value,
      type: createForm.value.type.toLowerCase() as any,
    })
    showCreateDialog.value = false
    createForm.value = {
      name: '',
      type: 'http',
      host: '',
      port: 7890,
      username: '',
      password: '',
    }
    await fetchProxies()
  } catch (error) {
    console.error('Failed to create proxy:', error)
  } finally {
    creating.value = false
  }
}

async function testConnection(id: string) {
  try {
    const result = await proxyStore.testConnection(id)
    alert(result.connected ? '代理连接成功！' : '代理连接失败')
  } catch (error) {
    console.error('Failed to test connection:', error)
    alert('连接测试失败')
  }
}

async function deleteProxy(id: string) {
  if (!confirm('确定要删除这个代理吗？')) return
  try {
    await proxyStore.deleteProxy(id)
    await fetchProxies()
  } catch (error) {
    console.error('Failed to delete proxy:', error)
  }
}
</script>

<style scoped>
.proxy-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.proxy-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4) var(--spacing-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  transition: all var(--transition-fast);
}

.proxy-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.proxy-card__left {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.proxy-card__type {
  width: 60px;
}

.proxy-card__address {
  display: flex;
  align-items: center;
  gap: var(--spacing-1);
}

.proxy-card__host {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.proxy-card__port {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.proxy-card__name {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.proxy-card__right {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
}

.proxy-card__actions {
  display: flex;
  gap: var(--spacing-2);
}
</style>
