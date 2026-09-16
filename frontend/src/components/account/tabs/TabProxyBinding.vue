<template>
  <Card>
    <template #header>
      <div class="tab-header">
        <h3>绑定 Proxy</h3>
        <button class="btn btn--primary btn--sm" @click="showBindDialog = true">
          + 绑定 Proxy
        </button>
      </div>
    </template>
    
    <div v-if="bindings.length === 0" class="empty-binding">
      <p class="text-muted">暂无绑定的 Proxy</p>
    </div>
    
    <div v-else class="binding-list">
      <div
        v-for="binding in bindings"
        :key="binding.proxy_id"
        class="binding-item"
      >
        <div class="binding-item__info">
          <span class="proxy-type-badge">{{ binding.proxy_type }}</span>
          <div>
            <p class="binding-item__name">{{ binding.proxy_name }}</p>
            <p class="binding-item__address">{{ binding.proxy_host }}:{{ binding.proxy_port }}</p>
          </div>
        </div>
        <button class="btn btn--ghost btn--sm" @click="removeBinding(binding.proxy_id)">
          解除绑定
        </button>
      </div>
    </div>

    <!-- Bind Dialog -->
    <Modal
      v-if="showBindDialog"
      title="绑定 Proxy"
      @close="showBindDialog = false"
    >
      <div class="form-group">
        <label class="form-label">选择 Proxy</label>
        <select v-model="selectedProxyId" class="form-select" required>
          <option value="" disabled>请选择 Proxy</option>
          <option v-for="proxy in proxies" :key="proxy.id" :value="proxy.id">
            {{ proxy.name }} ({{ proxy.type }} - {{ proxy.host }}:{{ proxy.port }})
          </option>
        </select>
      </div>
      <ModalFooter>
        <button class="btn btn--ghost" @click="showBindDialog = false">取消</button>
        <button class="btn btn--primary" :disabled="!selectedProxyId" @click="bindProxy">
          确认绑定
        </button>
      </ModalFooter>
    </Modal>
  </Card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useProxyStore } from '@/stores/proxy'
import type { Proxy } from '@/api/types'
import Card from '@/components/common/Card.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

defineProps<{
  accountId: string
}>()

const proxyStore = useProxyStore()
const proxies = ref<Proxy[]>([])
const bindings = ref<any[]>([])
const showBindDialog = ref(false)
const selectedProxyId = ref('')

onMounted(async () => {
  await fetchProxies()
})

async function fetchProxies() {
  try {
    const data = await proxyStore.fetchProxies()
    proxies.value = data.items
  } catch (error) {
    console.error('Failed to fetch proxies:', error)
  }
}

async function bindProxy() {
  if (!selectedProxyId.value) return
  
  const proxy = proxies.value.find(p => p.id === selectedProxyId.value)
  if (proxy) {
    bindings.value.push({
      proxy_id: proxy.id,
      proxy_name: proxy.name,
      proxy_type: proxy.type.toUpperCase(),
      proxy_host: proxy.host,
      proxy_port: proxy.port,
    })
    showBindDialog.value = false
    selectedProxyId.value = ''
  }
}

async function removeBinding(proxyId: string) {
  bindings.value = bindings.value.filter(b => b.proxy_id !== proxyId)
}
</script>

<style scoped>
.tab-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

.proxy-type-badge {
  display: inline-block;
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-info-light);
  color: var(--color-info);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  text-transform: uppercase;
}

.binding-item__name {
  margin: 0 0 var(--spacing-1);
  font-weight: var(--font-weight-medium);
}

.binding-item__address {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-family: monospace;
}

.text-muted {
  color: var(--color-text-muted);
}
</style>
