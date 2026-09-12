<script setup lang="ts">
import { ref } from 'vue'

const message = ref('AI Agent Platform')
</script>

<template>
  <div class="container">
    <h1>{{ message }}</h1>
    <p class="subtitle">基础骨架已搭建完成 (◕‿◕)</p>
    <div class="status">
      <span class="badge success">✓ Vue 3</span>
      <span class="badge success">✓ TypeScript</span>
      <span class="badge success">✓ Pinia</span>
      <span class="badge success">✓ Vue Router</span>
      <span class="badge success">✓ Tauri 2</span>
    </div>
  </div>
</template>

<style scoped>
.container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  font-family: system-ui, -apple-system, sans-serif;
}

h1 {
  font-size: 2.5rem;
  color: #1a1a2e;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: #666;
  font-size: 1.2rem;
  margin-bottom: 2rem;
}

.status {
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
  justify-content: center;
}

.badge {
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
}

.badge.success {
  background: #d4edda;
  color: #155724;
}
</style>
