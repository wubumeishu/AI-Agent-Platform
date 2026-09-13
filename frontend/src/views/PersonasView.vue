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
      <div
        v-for="persona in personas"
        :key="persona.id"
        class="persona-card"
        @click="navigateToDetail(persona.id)"
      >
        <div class="persona-card__header">
          <div class="persona-card__icon">🎭</div>
          <span class="persona-card__version">v{{ persona.version }}</span>
        </div>
        <div class="persona-card__content">
          <h3 class="persona-card__name">{{ persona.name }}</h3>
          <p class="persona-card__desc">{{ persona.description || '暂无描述' }}</p>
          <div class="persona-card__preview">
            <span class="preview-tag">{{ persona.personality.tone }}</span>
            <span class="preview-tag">{{ persona.personality.reply_length }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal
      v-if="showCreateDialog"
      title="新建 Persona"
      @close="showCreateDialog = false"
    >
      <form @submit.prevent="handleCreate">
        <div class="form-group">
          <label class="form-label">Persona 名称</label>
          <input
            v-model="createForm.name"
            class="form-input"
            placeholder="请输入 Persona 名称"
            required
          />
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
          <label class="form-label">语气</label>
          <select v-model="createForm.personality.tone" class="form-select">
            <option value="professional">专业</option>
            <option value="friendly">友好</option>
            <option value="casual">随意</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">回复长度</label>
          <select v-model="createForm.personality.reply_length" class="form-select">
            <option value="concise">简洁</option>
            <option value="balanced">适中</option>
            <option value="detailed">详细</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">主动性</label>
          <select v-model="createForm.personality.proactiveness" class="form-select">
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
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
import { useRouter } from 'vue-router'
import { usePersonaStore } from '@/stores/persona'
import type { Persona } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const router = useRouter()
const personaStore = usePersonaStore()

const personas = ref<Persona[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)

const createForm = ref({
  name: '',
  description: '',
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
    await personaStore.createPersona(createForm.value)
    showCreateDialog.value = false
    createForm.value = {
      name: '',
      description: '',
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

.persona-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-5);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.persona-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.persona-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-3);
}

.persona-card__icon {
  width: 48px;
  height: 48px;
  background: var(--color-primary-light);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
}

.persona-card__version {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  background: var(--color-bg-tertiary);
  padding: var(--spacing-1) var(--spacing-2);
  border-radius: var(--radius-sm);
}

.persona-card__content {
  margin-bottom: var(--spacing-3);
}

.persona-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0 0 var(--spacing-1);
}

.persona-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.persona-card__preview {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.preview-tag {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
}
</style>
