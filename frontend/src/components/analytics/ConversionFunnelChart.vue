<template>
  <BaseChart :options="option" :height="height" aria-label="线索转化漏斗" />
</template>

<script setup lang="ts">
/**
 * 线索转化漏斗图（P6AN-10 Dashboard 概览）。
 * 数据源：DashboardOverviewResponse.conversion
 * （new_leads / total_leads / closed_leads + conversion_rate）。
 *
 * 注意口径（与 P6AN-02 文档一致）：conversion_rate =
 * closed_leads / total_leads（全量存量口径，非窗口内），视图层文案需标注。
 */
import { computed } from 'vue'
import type { ConversionOverview } from '@/api/analytics-types'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { useChartTheme } from '@/composables/useChartTheme'

const props = defineProps<{
  data: ConversionOverview
  height?: string
}>()

const { colors } = useChartTheme()

const option = computed<EChartsOption>(() => {
  const d = props.data
  const c = colors.value
  const hasAny = d.total_leads > 0 || d.new_leads > 0
  const fmtTooltip = (params: unknown): string => {
    const p = (Array.isArray(params) ? params[0] : params) as {
      name?: string
      value?: number
    } | null
    return `${p?.name ?? ''}：${p?.value ?? 0}`
  }

  return {
    tooltip: {
      trigger: 'item',
      formatter: fmtTooltip,
    },
    series: [
      {
        name: '线索转化',
        type: 'funnel',
        left: '12%',
        right: '12%',
        top: 16,
        bottom: 16,
        minSize: '18%',
        gap: 4,
        label: { show: true, position: 'inside', color: '#fff' },
        labelLine: { length: 8, lineStyle: { type: 'dashed' } },
        itemStyle: { borderColor: c.bgSecondary, borderWidth: 1 },
        data: hasAny
          ? [
              { value: d.total_leads, name: `全部线索 ${d.total_leads}`, itemStyle: { color: c.primary } },
              { value: Math.max(0, d.total_leads - d.new_leads), name: `存量线索 ${Math.max(0, d.total_leads - d.new_leads)}`, itemStyle: { color: c.info } },
              { value: d.closed_leads, name: `已转化 ${d.closed_leads}`, itemStyle: { color: c.success } },
            ]
          : [{ value: 1, name: '暂无线索', itemStyle: { color: c.border } }],
      },
    ],
  }
})
</script>
