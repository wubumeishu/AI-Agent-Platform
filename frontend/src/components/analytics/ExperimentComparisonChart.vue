<template>
  <BaseChart
    :options="option"
    :height="height"
    aria-label="实验变组指标对比"
    :with-tools="true"
  />
</template>

<script setup lang="ts">
/**
 * 实验结果对比视图（Phase 6 / P6AN-12，对接 P6AN-08 summary）。
 *
 * 数据源：ExperimentResultSummaryResponse.metrics（每指标一行，
 * variants[] 为各变组最新快照）。分组柱状图：x 轴 = 指标，
 * 每个变组一条 series；数值为 Decimal 字符串 → Number 转换，
 * 缺失快照 → null（ECharts 断柱）。
 */
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import type {
  ExperimentResultSummaryResponse,
  ExperimentResultSummaryRow,
} from '@/api/analytics-types'
import BaseChart from './BaseChart.vue'
import { useChartTheme } from '@/composables/useChartTheme'

/** 变组配色（按 label 顺序取色，最多 6 色循环） */
const VARIANT_COLORS = [
  '#4F46E5',
  '#10B981',
  '#F59E0B',
  '#EF4444',
  '#0EA5E9',
  '#A855F7',
]

const props = defineProps<{
  summary: ExperimentResultSummaryResponse
  height?: string
}>()

const { colors } = useChartTheme()

/** 变组 label 去重（保持 summary 中每个指标行的顺序，基线恒在前） */
const variantLabels = computed<string[]>(() => {
  const seen: string[] = []
  for (const m of props.summary.metrics) {
    for (const row of m.variants) {
      if (!seen.includes(row.variant_label)) seen.push(row.variant_label)
    }
  }
  return seen
})

/** 每个变组在每个指标下的值（null = 无快照） */
const seriesData = (variant: string) =>
  props.summary.metrics.map((m) => {
    const row: ExperimentResultSummaryRow | undefined = m.variants.find(
      (r) => r.variant_label === variant
    )
    if (!row) return null
    const n = Number(row.metric_value)
    return Number.isNaN(n) ? null : n
  })

const option = computed<EChartsOption>(() => {
  const c = colors.value
  const metricNames = props.summary.metrics.map((m) =>
    m.is_primary ? `${m.metric_code}（主）` : m.metric_code
  )
  const baseline = props.summary.baseline_variant

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: unknown) =>
        v === null || v === undefined ? '无快照' : Number(v).toLocaleString('en-US'),
    },
    legend: { data: variantLabels.value },
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: metricNames,
      axisLabel: {
        interval: 0,
        rotate: metricNames.length > 3 ? 20 : 0,
        overflow: 'truncate',
        width: 120,
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    series: variantLabels.value.map((label, i) => ({
      name: baseline === label ? `${label}（基线）` : label,
      type: 'bar' as const,
      data: seriesData(label),
      barMaxWidth: 40,
      itemStyle: {
        color: VARIANT_COLORS[i % VARIANT_COLORS.length],
        borderRadius: [3, 3, 0, 0],
        opacity: baseline === label ? 1 : 0.85,
      },
    })),
  } as EChartsOption
})
</script>
