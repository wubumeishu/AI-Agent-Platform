<template>
  <BaseChart :options="option" :height="height" aria-label="Agent 消息量与成功率" />
</template>

<script setup lang="ts">
/**
 * Agent 活跃度柱状图（P6AN-10 Dashboard）。
 * 数据源：DashboardOverviewResponse.by_agent（Top 10 by message volume）。
 * 双系列：消息量（bar）+ 成功率（line，第二轴，null 段断开）。
 */
import { computed } from 'vue'
import type { AgentStat } from '@/api/analytics-types'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { useChartTheme } from '@/composables/useChartTheme'

const props = defineProps<{
  data: AgentStat[]
  height?: string
}>()

const { colors } = useChartTheme()

const option = computed<EChartsOption>(() => {
  const t = props.data
  const c = colors.value
  const names = t.map((a) => a.agent_name || a.agent_id.slice(0, 8))
  const successRates = t.map((a) =>
    a.message_success_rate === null ? null : Math.round(a.message_success_rate * 1000) / 10
  )

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: { data: ['消息量', '成功率'] },
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: names,
      axisLabel: {
        interval: 0,
        rotate: names.length > 4 ? 30 : 0,
        overflow: 'truncate',
        width: 80,
      },
    },
    yAxis: [
      {
        type: 'value',
        name: '消息量',
      },
      {
        type: 'value',
        name: '成功率 %',
        min: 0,
        max: 100,
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '消息量',
        type: 'bar',
        data: t.map((a) => a.messages),
        barMaxWidth: 32,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: c.primary,
        },
      },
      {
        name: '成功率',
        type: 'line',
        yAxisIndex: 1,
        data: successRates,
        connectNulls: false,
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2, color: c.success },
        itemStyle: { color: c.success },
      },
    ],
  }
})
</script>
