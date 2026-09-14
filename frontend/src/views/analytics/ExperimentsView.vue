<template>
  <div class="analytics-placeholder">
    <PageHeader title="数据洞察 · 实验" />
    <EmptyState
      icon="🧪"
      title="实验视图开发中"
      description="P6AN-12 将在此落地实验 UI（P6AN-08 API 的 typed client 与 experiment store 已就绪）。"
      :show-action="true"
      action-text="查看概览"
      @action="$router.push('/analytics/dashboard')"
    />
  </div>
</template>

<script setup lang="ts">
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
</script>

<style scoped>
.analytics-placeholder {
  max-width: 1200px;
  margin: 0 auto;
}
</style>
