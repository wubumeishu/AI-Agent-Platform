import { ref, computed } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark'
export type Language = 'zh' | 'en'

const STORAGE_KEY = 'app-settings'

interface SettingsState {
  appName: string
  theme: ThemeMode
  language: Language
}

const DEFAULT_SETTINGS: SettingsState = {
  appName: 'AI Agent Platform',
  theme: 'light',
  language: 'zh',
}

function loadSettings(): SettingsState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(stored) }
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_SETTINGS
}

function saveSettings(settings: SettingsState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

export const useSettingsStore = defineStore('settings', () => {
  const state = ref<SettingsState>(loadSettings())

  const appName = computed(() => state.value.appName)
  const theme = computed(() => state.value.theme)
  const language = computed(() => state.value.language)

  const isDark = computed(() => state.value.theme === 'dark')

  function setAppName(name: string) {
    state.value = { ...state.value, appName: name.trim() || DEFAULT_SETTINGS.appName }
    saveSettings(state.value)
    applyTheme()
  }

  function setTheme(mode: ThemeMode) {
    state.value = { ...state.value, theme: mode }
    saveSettings(state.value)
    applyTheme()
  }

  function setLanguage(lang: Language) {
    state.value = { ...state.value, language: lang }
    saveSettings(state.value)
  }

  function applyTheme() {
    document.documentElement.classList.toggle('dark', state.value.theme === 'dark')
  }

  // Initialize theme on store creation
  applyTheme()

  return {
    appName,
    theme,
    language,
    isDark,
    setAppName,
    setTheme,
    setLanguage,
  }
})
