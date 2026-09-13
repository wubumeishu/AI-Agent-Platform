<template>
  <aside class="sidebar" :class="{ 'sidebar--collapsed': collapsed }">
    <!-- Logo -->
    <div class="sidebar__header">
      <div class="sidebar__logo">
        <span class="sidebar__logo-icon">⚡</span>
        <span class="sidebar__logo-text" v-show="!collapsed">AI Agent</span>
      </div>
      <button
        class="sidebar__toggle"
        @click="$emit('toggle')"
        :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'"
      >
        {{ collapsed ? '›' : '‹' }}
      </button>
    </div>

    <!-- Navigation -->
    <nav class="sidebar__nav">
      <ul class="sidebar__menu">
        <li
          v-for="item in menuItems"
          :key="item.path"
          class="sidebar__menu-item"
          :class="{ 'sidebar__menu-item--active': isActive(item.path) }"
        >
          <router-link
            :to="item.path"
            class="sidebar__menu-link"
          >
            <span class="sidebar__menu-icon">{{ item.icon }}</span>
            <span class="sidebar__menu-label" v-show="!collapsed">{{ item.label }}</span>
          </router-link>
        </li>
      </ul>
    </nav>

    <!-- Footer -->
    <div class="sidebar__footer" v-show="!collapsed">
      <div class="sidebar__version">v0.0.1</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

defineProps<{
  collapsed?: boolean
}>()

defineEmits<{
  (e: 'toggle'): void
}>()

const route = useRoute()

const menuItems = [
  { path: '/', label: '首页', icon: '🏠' },
  { path: '/dashboard', label: '工作台', icon: '📊' },
  { path: '/agents', label: 'Agent 管理', icon: '🤖' },
  { path: '/personas', label: 'Persona 管理', icon: '🎭' },
  { path: '/accounts', label: '账号管理', icon: '👤' },
  { path: '/platforms', label: '平台管理', icon: '🔌' },
  { path: '/browsers', label: '浏览器管理', icon: '🌐' },
  { path: '/proxies', label: '代理管理', icon: '🔀' },
  { path: '/settings', label: '设置', icon: '⚙️' },
]

const isActive = (path: string) => {
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 100vh;
  background: var(--color-bg-primary);
  border-right: 1px solid var(--color-border);
  transition: width var(--transition-normal);
}

.sidebar--collapsed {
  width: 64px;
}

/* Header */
.sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-4);
  border-bottom: 1px solid var(--color-border);
  height: 56px;
}

.sidebar__logo {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.sidebar__logo-icon {
  font-size: var(--font-size-xl);
  flex-shrink: 0;
}

.sidebar__logo-text {
  white-space: nowrap;
  overflow: hidden;
}

.sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--font-size-lg);
  transition: background var(--transition-fast);
  flex-shrink: 0;
}

.sidebar__toggle:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

/* Navigation */
.sidebar__nav {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--spacing-2) 0;
}

.sidebar__menu {
  list-style: none;
  padding: 0;
  margin: 0;
}

.sidebar__menu-item {
  margin: var(--spacing-1) var(--spacing-2);
}

.sidebar__menu-link {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-2) var(--spacing-3);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: all var(--transition-fast);
  white-space: nowrap;
  overflow: hidden;
}

.sidebar__menu-link:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.sidebar__menu-item--active .sidebar__menu-link {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: var(--font-weight-medium);
}

.sidebar__menu-icon {
  font-size: var(--font-size-lg);
  flex-shrink: 0;
  width: 20px;
  text-align: center;
}

.sidebar__menu-label {
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Footer */
.sidebar__footer {
  padding: var(--spacing-4);
  border-top: 1px solid var(--color-border);
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.sidebar__version {
  text-align: center;
}
</style>
