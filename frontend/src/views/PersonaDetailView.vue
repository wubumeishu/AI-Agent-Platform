<template>
  <div class="persona-detail-view" v-loading="currentPersonaLoading">
    <PageHeader title="Persona 详情" show-back />

    <div v-if="!currentPersona" class="empty-state">
      <p>Persona 不存在</p>
    </div>

    <div v-else>
      <PersonaEditor
        :persona="currentPersona"
        :versions="versions"
        @save="handleSave"
        @clone="handleClone"
        @delete="handleDelete"
        @view-all="router.push('/personas')"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usePersonaStore } from '@/stores/persona'
import type { Persona } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import PersonaEditor from '@/components/persona/PersonaEditor.vue'

const route = useRoute()
const router = useRouter()
const personaStore = usePersonaStore()

const currentPersona = ref<Persona | null>(null)
const currentPersonaLoading = ref(false)
const versions = ref<Persona[]>([])

onMounted(async () => {
  const id = route.params.id as string
  await fetchPersona(id)
  await fetchVersions(id)
})

watch(() => route.params.id, async (newId) => {
  if (newId) {
    await fetchPersona(newId as string)
    await fetchVersions(newId as string)
  }
})

async function fetchPersona(id: string) {
  currentPersonaLoading.value = true
  try {
    const persona = await personaStore.fetchPersona(id)
    currentPersona.value = persona
  } catch (error) {
    console.error('Failed to fetch persona:', error)
  } finally {
    currentPersonaLoading.value = false
  }
}

async function fetchVersions(id: string) {
  try {
    const versionsData = await personaStore.fetchVersions(id)
    versions.value = versionsData
  } catch (error) {
    console.error('Failed to fetch versions:', error)
  }
}

async function handleSave() {
  if (!currentPersona.value) return
  
  try {
    await personaStore.updatePersona(route.params.id as string, {
      name: currentPersona.value.name,
      description: currentPersona.value.description || undefined,
      personality: currentPersona.value.personality,
    })
    // Show success feedback
    alert('保存成功！')
  } catch (error) {
    console.error('Failed to save persona:', error)
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

async function handleDelete() {
  if (!confirm('确定要删除这个 Persona 吗？此操作不可恢复。')) return
  try {
    await personaStore.deletePersona(route.params.id as string)
    router.push('/personas')
  } catch (error) {
    console.error('Failed to delete persona:', error)
  }
}
</script>

<style scoped>
.empty-state {
  text-align: center;
  padding: var(--spacing-12);
  color: var(--color-text-muted);
}
</style>
