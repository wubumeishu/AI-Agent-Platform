<template>
  <BaseChart :options="option" :height="height" aria-label="消息发送状态分布" />
</template>

<script setup lang="ts">
/**
 * 消息发送状态环形图（P6AN-10 Dashboard）。
 * 数据源：DashboardOverviewResponse.messages（total / delivered / failed）。
 * "在途" = total - delivered - failed（已发送未回执）。
 */
import { computed } from 'vue'
import type { MessagesOverview } from '@/api/analytics-types'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { useChartTheme } from '@/composables/useChartTheme'

const props = defineProps<{
  data: MessagesOverview
  height?: string
}>()

const { colors } = useChartTheme()

const option = computed<EChartsOption>(() => {
  const m = props.data
  const c = colors.value
  const inFlight = Math.max(0, m.total - m.delivered - m.failed)
  const hasAny = m.total > 0

  return {
    tooltip: { trigger: 'item' },
    legend: {
      orient: 'vertical',
      right: 8,
      top: 'center',
      icon: 'circle',
    },
    series: [
      {
        name: '消息状态',
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['40%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 4, borderColor: c.bgSecondary, borderWidth: 2 },
        label: { show: false },
        data: hasAny
          ? [
              { value: m.delivered, name: '已送达', itemStyle: { color: c.success } },
              { value: m.failed, name: '失败', itemStyle: { color: c.error } },
              { value: inFlight, name: '在途', itemStyle: { color: c.info } },
            ]
          : [
              // 无数据占位（灰色整环），空态由视图层文字提示
              { value: 1, name: '暂无数据', itemStyle: { color: c.border } },
            ],
      },
    ],
  }
})
</script>
