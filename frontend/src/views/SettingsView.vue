<template>
  <div class="settings-view">
    <h2 class="settings-view__title">设置</h2>
    <p class="settings-view__desc">配置应用基础参数</p>

    <div class="settings-section">
      <h3 class="settings-section__title">基础设置</h3>

      <!-- 应用名称 -->
      <div class="setting-item">
        <div class="setting-item__label">
          <span class="setting-item__name">应用名称</span>
          <span class="setting-item__hint">设置显示在标题栏和侧边栏的应用名称</span>
        </div>
        <div class="setting-item__control">
          <input
            v-model="appName"
            type="text"
            class="setting-input"
            placeholder="请输入应用名称"
            maxlength="50"
            @input="handleAppNameChange"
          />
          <span class="setting-input__count">{{ appName.length }}/50</span>
        </div>
      </div>

      <!-- 主题设置 -->
      <div class="setting-item">
        <div class="setting-item__label">
          <span class="setting-item__name">主题模式</span>
          <span class="setting-item__hint">选择浅色或深色主题</span>
        </div>
        <div class="setting-item__control">
          <div class="theme-selector">
            <button
              v-for="option in themeOptions"
              :key="option.value"
              :class="['theme-option', { 'theme-option--active': settingsStore.theme === option.value }]"
              @click="handleThemeChange(option.value)"
            >
              <span class="theme-option__icon">{{ option.icon }}</span>
              <span class="theme-option__label">{{ option.label }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 语言设置 -->
      <div class="setting-item">
        <div class="setting-item__label">
          <span class="setting-item__name">语言</span>
          <span class="setting-item__hint">选择界面显示语言</span>
        </div>
        <div class="setting-item__control">
          <select v-model="selectedLanguage" class="setting-select" @change="handleLanguageChange">
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>
    </div>

    <!-- 保存状态提示 -->
    <div v-if="saveStatus" class="save-status" :class="`save-status--${saveStatus.type}`">
      <span class="save-status__icon">{{ saveStatus.icon }}</span>
      <span class="save-status__message">{{ saveStatus.message }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useSettingsStore, type ThemeMode, type Language } from '@/stores/settings'

const settingsStore = useSettingsStore()

// Form state
const appName = ref(settingsStore.appName)
const selectedLanguage = ref<Language>(settingsStore.language)
const saveStatus = ref<{ type: 'success' | 'error'; icon: string; message: string } | null>(null)

// Theme options
const themeOptions = [
  { value: 'light' as ThemeMode, label: '浅色', icon: '☀️' },
  { value: 'dark' as ThemeMode, label: '深色', icon: '🌙' },
]

// Debounce timer
let debounceTimer: ReturnType<typeof setTimeout> | null = null

// Handle app name change with debounce
function handleAppNameChange() {
  clearTimeoutDebounce()
  debounceTimer = setTimeout(() => {
    settingsStore.setAppName(appName.value)
    showSaveStatus('success', '应用名称已保存')
  }, 500)
}

// Handle theme change
function handleThemeChange(theme: ThemeMode) {
  settingsStore.setTheme(theme)
  showSaveStatus('success', theme === 'dark' ? '已切换到深色主题' : '已切换到浅色主题')
}

// Handle language change
function handleLanguageChange() {
  settingsStore.setLanguage(selectedLanguage.value)
  showSaveStatus('success', '语言设置已保存')
}

// Show save status notification
function showSaveStatus(type: 'success' | 'error', message: string) {
  saveStatus.value = {
    type,
    icon: type === 'success' ? '✓' : '✗',
    message,
  }
  setTimeout(() => {
    saveStatus.value = null
  }, 2000)
}

// Clear debounce timer
function clearTimeoutDebounce() {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
}

// Watch for external changes to sync form state
watch(
  () => settingsStore.appName,
  (newName) => {
    if (newName !== appName.value) {
      appName.value = newName
    }
  }
)

watch(
  () => settingsStore.language,
  (newLang) => {
    if (newLang !== selectedLanguage.value) {
      selectedLanguage.value = newLang
    }
  }
)
</script>

<style scoped>
.settings-view {
  max-width: 720px;
}

.settings-view__title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.settings-view__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--spacing-8);
}

/* Section */
.settings-section {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-6);
  margin-bottom: var(--spacing-6);
}

.settings-section__title {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-6);
  padding-bottom: var(--spacing-4);
  border-bottom: 1px solid var(--color-border);
}

/* Setting item */
.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: var(--spacing-4) 0;
  border-bottom: 1px solid var(--color-bg-tertiary);
}

.setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.setting-item:first-child {
  padding-top: 0;
}

.setting-item__label {
  flex: 1;
  padding-right: var(--spacing-6);
}

.setting-item__name {
  display: block;
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.setting-item__hint {
  display: block;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.setting-item__control {
  flex-shrink: 0;
}

/* Input */
.setting-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.setting-input {
  width: 280px;
  padding: var(--spacing-2) var(--spacing-3);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.setting-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.setting-input::placeholder {
  color: var(--color-text-muted);
}

.setting-input__count {
  position: absolute;
  right: var(--spacing-3);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

/* Select */
.setting-select {
  padding: var(--spacing-2) var(--spacing-3);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
  min-width: 140px;
}

.setting-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* Theme selector */
.theme-selector {
  display: flex;
  gap: var(--spacing-3);
}

.theme-option {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-4) var(--spacing-6);
  background: var(--color-bg-secondary);
  border: 2px solid var(--color-border);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast);
  min-width: 100px;
}

.theme-option:hover {
  border-color: var(--color-border-hover);
  background: var(--color-bg-tertiary);
}

.theme-option--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.theme-option--active .theme-option__label {
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

.theme-option__icon {
  font-size: 24px;
}

.theme-option__label {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

/* Save status */
.save-status {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: var(--spacing-3) var(--spacing-4);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  animation: slideIn var(--transition-normal);
}

.save-status--success {
  background: var(--color-success-light);
  color: var(--color-success);
}

.save-status--error {
  background: var(--color-error-light);
  color: var(--color-error);
}

.save-status__icon {
  font-weight: var(--font-weight-bold);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
