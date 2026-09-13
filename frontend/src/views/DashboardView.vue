<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="dashboard__header">
      <div>
        <h1 class="dashboard__title">工作台</h1>
        <p class="dashboard__subtitle">AI Agent 智能获客与私域运营平台</p>
      </div>
      <div class="dashboard__date">{{ currentDate }}</div>
    </header>

    <!-- Empty State -->
    <section v-if="isEmpty" class="dashboard__empty">
      <div class="dashboard__empty-icon">🤖</div>
      <h2 class="dashboard__empty-title">暂无数据</h2>
      <p class="dashboard__empty-desc">开始创建你的第一个 AI Agent，享受智能获客的乐趣吧！</p>
    </section>

    <!-- Function Cards -->
    <section v-else class="dashboard__cards">
      <div class="dashboard__card" @click="navigateTo('/agents')">
        <div class="dashboard__card-icon">🤖</div>
        <h3 class="dashboard__card-title">Agent 管理</h3>
        <p class="dashboard__card-desc">创建和管理你的 AI Agent，配置Persona和策略</p>
        <span class="dashboard__card-arrow">→</span>
      </div>

      <div class="dashboard__card" @click="navigateTo('/accounts')">
        <div class="dashboard__card-icon">👤</div>
        <h3 class="dashboard__card-title">账号管理</h3>
        <p class="dashboard__card-desc">管理社交账号和浏览器配置</p>
        <span class="dashboard__card-arrow">→</span>
      </div>

      <div class="dashboard__card" @click="navigateTo('/settings')">
        <div class="dashboard__card-icon">⚙️</div>
        <h3 class="dashboard__card-title">设置</h3>
        <p class="dashboard__card-desc">应用基础设置和偏好配置</p>
        <span class="dashboard__card-arrow">→</span>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const isEmpty = ref(true)

const currentDate = computed(() => {
  const now = new Date()
  return now.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    weekday: 'long'
  })
})

const navigateTo = (path: string) => {
  router.push(path)
}
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--spacing-8) var(--spacing-6);
}

/* Header */
.dashboard__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--spacing-8);
}

.dashboard__title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-1);
}

.dashboard__subtitle {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
}

.dashboard__date {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  text-align: right;
}

/* Empty State */
.dashboard__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  padding: var(--spacing-8);
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 2px dashed var(--color-border);
}

.dashboard__empty-icon {
  font-size: 64px;
  margin-bottom: var(--spacing-4);
}

.dashboard__empty-title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.dashboard__empty-desc {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  text-align: center;
  max-width: 400px;
  line-height: var(--line-height-relaxed);
}

/* Cards */
.dashboard__cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.dashboard__card {
  position: relative;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-6);
  cursor: pointer;
  transition: all var(--transition-normal);
}

.dashboard__card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.dashboard__card-icon {
  font-size: 32px;
  margin-bottom: var(--spacing-3);
}

.dashboard__card-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin-bottom: var(--spacing-2);
}

.dashboard__card-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
  margin-bottom: var(--spacing-4);
  padding-right: 24px;
}

.dashboard__card-arrow {
  position: absolute;
  top: var(--spacing-6);
  right: var(--spacing-6);
  font-size: var(--font-size-lg);
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.dashboard__card:hover .dashboard__card-arrow {
  transform: translateX(4px);
  color: var(--color-primary);
}

/* Responsive */
@media (max-width: 768px) {
  .dashboard {
    padding: var(--spacing-4);
  }

  .dashboard__header {
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .dashboard__date {
    text-align: left;
  }

  .dashboard__cards {
    grid-template-columns: 1fr;
  }
}
</style>
