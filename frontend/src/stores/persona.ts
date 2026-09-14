import { defineStore } from 'pinia'
import { ref } from 'vue'
import { personaApi } from '@/api/persona'
import type { Persona, CreatePersonaRequest, UpdatePersonaRequest, PaginatedResponse } from '@/api/types'

export const usePersonaStore = defineStore('persona', () => {
  // State
  const personas = ref<Persona[]>([])
  const loading = ref(false)
  const currentPersona = ref<Persona | null>(null)
  const currentPersonaLoading = ref(false)

  // Actions
  async function fetchPersonas(): Promise<PaginatedResponse<Persona>> {
    loading.value = true
    try {
      const data = await personaApi.list()
      personas.value = data.items
      return data
    } catch (error) {
      console.error('[PersonaStore] Failed to fetch personas:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  async function fetchPersona(id: string) {
    currentPersonaLoading.value = true
    try {
      const persona = await personaApi.detail(id)
      currentPersona.value = persona
      return persona
    } catch (error) {
      console.error('[PersonaStore] Failed to fetch persona:', error)
      throw error
    } finally {
      currentPersonaLoading.value = false
    }
  }

  async function createPersona(data: CreatePersonaRequest) {
    try {
      const persona = await personaApi.create(data)
      personas.value.unshift(persona)
      return persona
    } catch (error) {
      console.error('[PersonaStore] Failed to create persona:', error)
      throw error
    }
  }

  async function updatePersona(id: string, data: UpdatePersonaRequest) {
    try {
      const persona = await personaApi.update(id, data)
      const index = personas.value.findIndex(p => p.id === id)
      if (index !== -1) {
        personas.value[index] = persona
      }
      if (currentPersona.value?.id === id) {
        currentPersona.value = persona
      }
      return persona
    } catch (error) {
      console.error('[PersonaStore] Failed to update persona:', error)
      throw error
    }
  }

  async function deletePersona(id: string) {
    try {
      await personaApi.delete(id)
      personas.value = personas.value.filter(p => p.id !== id)
      if (currentPersona.value?.id === id) {
        currentPersona.value = null
      }
    } catch (error) {
      console.error('[PersonaStore] Failed to delete persona:', error)
      throw error
    }
  }

  async function clone(id: string) {
    try {
      const persona = await personaApi.clone(id)
      personas.value.unshift(persona)
      return persona
    } catch (error) {
      console.error('[PersonaStore] Failed to clone persona:', error)
      throw error
    }
  }

  async function fetchVersions(id: string): Promise<Persona[]> {
    try {
      return await personaApi.versions(id)
    } catch (error) {
      console.error('[PersonaStore] Failed to fetch versions:', error)
      throw error
    }
  }

  function clearCurrentPersona() {
    currentPersona.value = null
  }

  return {
    // State
    personas,
    loading,
    currentPersona,
    currentPersonaLoading,
    // Actions
    fetchPersonas,
    fetchPersona,
    createPersona,
    updatePersona,
    deletePersona,
    clone,
    fetchVersions,
    clearCurrentPersona,
  }
})
