<template>
  <Card>
    <template #header>
      <div class="tab-header">
        <h3>绑定 Agent</h3>
        <button class="btn btn--primary btn--sm" @click="showBindDialog = true">
          + 绑定 Agent
        </button>
      </div>
    </template>
    
    <div v-if="bindings.length === 0" class="empty-binding">
      <p class="text-muted">暂无绑定的 Agent</p>
    </div>
    
    <div v-else class="binding-list">
      <div
        v-for="binding in bindings"
        :key="binding.agent_id"
        class="binding-item"
      >
        <div class="binding-item__info">
          <span class="binding-item__icon">🤖</span>
          <div>
            <p class="binding-item__name">{{ binding.agent_name }}</p>
            <p class="binding-item__desc">{{ binding.agent_description }}</p>
          </div>
        </div>
        <div class="binding-item__actions">
          <span v-if="binding.is_primary" class="badge badge--primary">主绑定</span>
          <button class="btn btn--ghost btn--sm" @click="removeBinding(binding.agent_id)">
            解除绑定
          </button>
        </div>
      </div>
    </div>

    <!-- Bind Dialog -->
    <Modal
      v-if="showBindDialog"
      title="绑定 Agent"
      @close="showBindDialog = false"
    >
      <div class="form-group">
        <label class="form-label">选择 Agent</label>
        <select v-model="selectedAgentId" class="form-select" required>
          <option value="" disabled>请选择 Agent</option>
          <option v-for="agent in availableAgents" :key="agent.id" :value="agent.id">
            {{ agent.name }}
          </option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">
          <input v-model="isPrimary" type="checkbox" />
          设为主绑定
        </label>
      </div>
      <ModalFooter>
        <button class="btn btn--ghost" @click="showBindDialog = false">取消</button>
        <button class="btn btn--primary" :disabled="!selectedAgentId" @click="bindAgent">
          确认绑定
        </button>
      </ModalFooter>
    </Modal>
  </Card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import Card from '@/components/common/Card.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

defineProps<{
  accountId: string
}>()

const bindings = ref<any[]>([])
const availableAgents = ref<any[]>([])
const showBindDialog = ref(false)
const selectedAgentId = ref('')
const isPrimary = ref(false)

onMounted(async () => {
  await fetchBindings()
  await fetchAvailableAgents()
})

async function fetchBindings() {
  // Mock data - would be replaced with real API call
  bindings.value = []
}

async function fetchAvailableAgents() {
  // Mock data - would be replaced with real API call
  availableAgents.value = [
    { id: '1', name: '客服助手', description: '处理客户咨询' },
    { id: '2', name: '营销助手', description: '自动化营销流程' },
  ]
}

async function bindAgent() {
  if (!selectedAgentId.value) return
  
  // Mock binding
  const agent = availableAgents.value.find(a => a.id === selectedAgentId.value)
  if (agent) {
    bindings.value.push({
      agent_id: agent.id,
      agent_name: agent.name,
      agent_description: agent.description,
      is_primary: isPrimary.value,
    })
    showBindDialog.value = false
    selectedAgentId.value = ''
    isPrimary.value = false
  }
}

async function removeBinding(agentId: string) {
  bindings.value = bindings.value.filter(b => b.agent_id !== agentId)
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

.binding-item__icon {
  font-size: 24px;
}

.binding-item__name {
  margin: 0 0 var(--spacing-1);
  font-weight: var(--font-weight-medium);
}

.binding-item__desc {
  margin: 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.binding-item__actions {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.badge {
  display: inline-block;
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.badge--primary {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.text-muted {
  color: var(--color-text-muted);
}
</style>
