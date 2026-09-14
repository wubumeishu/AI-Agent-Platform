<template>
  <BaseChart :options="option" :height="height" aria-label="Agent 24 小时活跃直方图" />
</template>

<script setup lang="ts">
/**
 * Agent 活跃时段直方图（Phase 6 / P6AN-12，对接 P6AN-07 active_hours）。
 *
 * 数据源：AgentPerformanceMetrics.active_hours（24 桶 UTC 小时消息量）。
 * 单系列 bar，峰值小时（peak_hour）高亮为强调色，其余为主色。
 */
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { useChartTheme } from '@/composables/useChartTheme'

const props = defineProps<{
  /** 24 桶 UTC 小时消息量 */
  data: number[]
  /** 消息量峰值小时（0-23），null = 无数据 */
  peakHour?: number | null
  height?: string
}>()

const { colors } = useChartTheme()

const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}`)

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const peak = props.peakHour
  const barData = props.data.map((v, i) => ({
    value: v,
    itemStyle: {
      color: i === peak ? c.warning : c.primary,
      borderRadius: [3, 3, 0, 0] as number[],
    },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : []
        const p = (list[0] ?? {}) as { dataIndex?: number; value?: number }
        const h = p.dataIndex ?? 0
        return `${String(h).padStart(2, '0')}:00 UTC<br/>消息量：${p.value ?? 0}`
      },
    },
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { interval: 1 },
    },
    yAxis: {
      type: 'value',
      name: '消息量',
      minInterval: 1,
    },
    series: [
      {
        name: '消息量',
        type: 'bar',
        data: barData,
        barMaxWidth: 18,
        markPoint:
          peak !== null && peak !== undefined
            ? {
                data: [
                  {
                    name: '峰值',
                    coord: [peak, props.data[peak] ?? 0],
                    symbol: 'pin',
                    symbolSize: 36,
                    itemStyle: { color: c.warning },
                    label: {
                      color: '#fff',
                      fontSize: 10,
                      formatter: '峰值',
                    },
                  },
                ],
              }
            : undefined,
      },
    ],
  } as EChartsOption
})
</script>
