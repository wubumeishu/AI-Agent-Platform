<template>
  <div class="persona-detail-view" v-loading="currentPersonaLoading">
    <PageHeader title="Persona 详情" show-back />

    <div v-if="!currentPersona" class="empty-state">
      <p>Persona 不存在</p>
    </div>

    <div v-else class="persona-editor">
      <Card>
        <template #header>
          <h3>基本信息</h3>
        </template>
        <div class="form-group">
          <label class="form-label">名称</label>
          <input
            v-model="editForm.name"
            class="form-input"
          />
        </div>
        <div class="form-group">
          <label class="form-label">描述</label>
          <textarea
            v-model="editForm.description"
            class="form-textarea"
            rows="3"
          ></textarea>
        </div>
      </Card>

      <Card class="mt-5">
        <template #header>
          <h3>性格参数</h3>
        </template>
        <div class="form-group">
          <label class="form-label">语气</label>
          <select v-model="editForm.personality.tone" class="form-select">
            <option value="professional">专业</option>
            <option value="friendly">友好</option>
            <option value="casual">随意</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">回复长度</label>
          <select v-model="editForm.personality.reply_length" class="form-select">
            <option value="concise">简洁</option>
            <option value="balanced">适中</option>
            <option value="detailed">详细</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">主动性</label>
          <select v-model="editForm.personality.proactiveness" class="form-select">
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </div>
      </Card>

      <div class="actions mt-5">
        <button class="btn btn--primary" :disabled="saving" @click="handleSave">
          {{ saving ? '保存中...' : '保存修改' }}
        </button>
        <button class="btn btn--ghost ml-2" @click="handleClone">克隆为新版</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePersonaStore } from '@/stores/persona'
import type { Persona } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import Card from '@/components/common/Card.vue'

const route = useRoute()
const router = useRouter()
const personaStore = usePersonaStore()

const currentPersona = ref<Persona | null>(null)
const currentPersonaLoading = ref(false)
const saving = ref(false)

const editForm = ref({
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
  const id = route.params.id as string
  await fetchPersona(id)
})

watch(() => route.params.id, async (newId) => {
  if (newId) await fetchPersona(newId as string)
})

async function fetchPersona(id: string) {
  currentPersonaLoading.value = true
  try {
    const persona = await personaStore.fetchPersona(id)
    currentPersona.value = persona
    editForm.value = {
      name: persona.name,
      description: persona.description || '',
      personality: { ...persona.personality },
    }
  } catch (error) {
    console.error('Failed to fetch persona:', error)
  } finally {
    currentPersonaLoading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    await personaStore.updatePersona(route.params.id as string, editForm.value)
    alert('保存成功！')
  } catch (error) {
    console.error('Failed to save persona:', error)
  } finally {
    saving.value = false
  }
}

async function handleClone() {
  try {
    await personaStore.clone(route.params.id as string)
    router.push('/personas')
  } catch (error) {
    console.error('Failed to clone persona:', error)
  }
}
</script>

<style scoped>
.persona-editor {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
}

.actions {
  display: flex;
  align-items: center;
}

.ml-2 {
  margin-left: var(--spacing-2);
}

.mt-5 {
  margin-top: var(--spacing-5);
}
</style>
