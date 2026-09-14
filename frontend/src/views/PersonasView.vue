<template>
  <div class="personas-view">
    <PageHeader title="Persona 管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建 Persona
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && personas.length === 0"
      icon="🎭"
      title="暂无 Persona"
      description="创建你的第一个 AI Persona"
      :show-action="true"
      action-text="新建 Persona"
      @action="showCreateDialog = true"
    />

    <!-- Persona Grid -->
    <div v-else class="persona-grid">
      <PersonaCard
        v-for="persona in personas"
        :key="persona.id"
        :persona="persona"
        @click="navigateToDetail(persona.id)"
      />
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建 Persona"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">Persona 名称 <span class="required">*</span></label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入 Persona 名称"
            required
            autofocus
          />
        </div>
        
        <div class="form-group">
          <label class="form-label">头像图标</label>
          <div class="icon-picker">
            <button
              v-for="icon in availableIcons"
              :key="icon"
              type="button"
              class="icon-btn"
              :class="{ 'icon-btn--active': createForm.icon === icon }"
              @click="createForm.icon = icon"
            >
              {{ icon }}
            </button>
          </div>
        </div>
        
        <div class="form-group">
          <label class="form-label">描述</label>
          <textarea
            v-model="createForm.description"
            class="form-textarea"
            placeholder="请输入描述（可选）"
            rows="2"
          ></textarea>
        </div>
        
        <div class="form-group">
          <label class="form-label">语气风格</label>
          <select v-model="createForm.personality.tone" class="form-select">
            <option value="professional">专业严谨</option>
            <option value="friendly">友好亲切</option>
            <option value="casual">随意轻松</option>
          </select>
        </div>
        
        <div class="form-group">
          <label class="form-label">回复长度</label>
          <select v-model="createForm.personality.reply_length" class="form-select">
            <option value="concise">简洁明了</option>
            <option value="balanced">适中平衡</option>
            <option value="detailed">详细全面</option>
          </select>
        </div>
        
        <div class="form-group">
          <label class="form-label">主动性</label>
          <select v-model="createForm.personality.proactiveness" class="form-select">
            <option value="low">被动响应</option>
            <option value="medium">适中引导</option>
            <option value="high">主动推进</option>
          </select>
        </div>
        
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="showCreateDialog = false">
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
import { useRouter } from 'vue-router'
import { usePersonaStore } from '@/stores/persona'
import type { Persona } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PersonaCard from '@/components/persona/PersonaCard.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const personaStore = usePersonaStore()

const personas = ref<Persona[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const availableIcons = ['🎭', '💬', '👤', '🤖', '💡', '🎯', '⚡', '🔧', '📝', '🎨']

const createForm = ref({
  name: '',
  description: '',
  icon: '🎭',
  personality: {
    tone: 'professional',
    reply_length: 'concise',
    proactiveness: 'medium',
    style_boundaries: [] as string[],
  },
})

onMounted(async () => {
  await fetchPersonas()
})

async function fetchPersonas() {
  loading.value = true
  try {
    const data = await personaStore.fetchPersonas()
    personas.value = data.items
  } catch (error) {
    console.error('Failed to fetch personas:', error)
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!createForm.value.name.trim()) return
  
  creating.value = true
  try {
    await personaStore.createPersona({
      name: createForm.value.name,
      description: createForm.value.description || undefined,
      personality: createForm.value.personality,
    })
    showCreateDialog.value = false
    createForm.value = {
      name: '',
      description: '',
      icon: '🎭',
      personality: {
        tone: 'professional',
        reply_length: 'concise',
        proactiveness: 'medium',
        style_boundaries: [],
      },
    }
    await fetchPersonas()
  } catch (error) {
    console.error('Failed to create persona:', error)
  } finally {
    creating.value = false
  }
}

function navigateToDetail(id: string) {
  router.push(`/personas/${id}`)
}
</script>

<style scoped>
.persona-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.required {
  color: var(--color-error);
}

.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  border-color: var(--color-primary);
  transform: scale(1.1);
}

.icon-btn--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}
</style>
