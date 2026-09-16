<template>
  <div class="analytics-placeholder">
    <PageHeader title="数据洞察 · 获客漏斗" />
    <EmptyState
      icon="🪜"
      title="漏斗视图开发中"
      description="P6AN-11 将在此落地漏斗 / 转化 UI（P6AN-03 / P6AN-05 API 的 typed client 与 funnelStore 已就绪）。"
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
