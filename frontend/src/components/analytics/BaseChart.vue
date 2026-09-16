<template>
  <div
    ref="containerRef"
    class="base-chart"
    :style="{ height }"
    role="img"
    :aria-label="ariaLabel"
  ></div>
</template>

<script setup lang="ts">
/**
 * ECharts 基础封装（Phase 6 / P6AN-10）。
 *
 * - 主题感知：通过 useChartTheme 把 design-token CSS 变量解析为实际色值
 *   （canvas 渲染器无法解析 var()），主题切换时自动重设
 * - 容器 resize 自动跟随（ResizeObserver）
 * - 组件卸载时 dispose，避免 ECharts 实例泄漏
 * - 传入的 option 深度 watch，数据变化时增量合并更新
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption, EChartsType } from 'echarts'
import { useChartTheme } from '@/composables/useChartTheme'

const props = defineProps<{
  /** ECharts option（业务部分；组件会按主题注入文字/网格/tooltip 基座） */
  options: EChartsOption
  /** 高度（CSS 长度） */
  height?: string
  /** 无障碍标签 */
  ariaLabel?: string
  /** 是否启用工具栏（数据视图 + 保存图片） */
  withTools?: boolean
}>()

const containerRef = ref<HTMLElement | null>(null)
let chart: EChartsType | null = null
let resizeObserver: ResizeObserver | null = null

const { colors } = useChartTheme()

/** 主题基座：文字 / 网格线 / tooltip / legend 颜色（canvas 可用的实际值） */
function buildOption(): EChartsOption {
  const t = colors.value
  const base: EChartsOption = {
    textStyle: { color: t.textPrimary, fontFamily: 'inherit' },
    tooltip: {
      backgroundColor: t.bgSecondary,
      borderColor: t.border,
      textStyle: { color: t.textPrimary, fontSize: 12 },
    },
    legend: { textStyle: { color: t.textMuted } },
  }
  if (props.withTools) {
    base.toolbox = {
      feature: {
        dataView: { title: '数据视图' },
        saveAsImage: { title: '保存图片' },
      },
    }
  }

  // 业务 option 优先于基座（浅合并顶层键）
  const merged: EChartsOption = { ...base, ...props.options }

  // 坐标轴着色（调用方未显式给颜色时套主题网格色）
  const axisColors = {
    axisLine: { lineStyle: { color: t.border } },
    axisLabel: { color: t.textMuted },
  }
  const splitLine = { lineStyle: { color: t.border, opacity: 0.5 } }
  const applyAxis = (ax: unknown) => {
    if (!ax || typeof ax !== 'object') return
    const a = ax as Record<string, unknown>
    if (!a.axisLine) a.axisLine = axisColors.axisLine
    if (!a.axisLabel) a.axisLabel = axisColors.axisLabel
    if (a.type !== 'category' && a.splitLine === undefined) a.splitLine = splitLine
  }
  if (Array.isArray(merged.xAxis)) merged.xAxis.forEach(applyAxis)
  else applyAxis(merged.xAxis)
  if (Array.isArray(merged.yAxis)) merged.yAxis.forEach(applyAxis)
  else applyAxis(merged.yAxis)

  return merged
}

function initChart() {
  if (!containerRef.value) return
  if (chart) {
    chart.dispose()
    chart = null
  }
  chart = echarts.init(containerRef.value, null, { renderer: 'canvas' })
  chart.setOption(buildOption(), true)

  // 容器尺寸变化 → resize
  resizeObserver = new ResizeObserver(() => {
    chart?.resize()
  })
  resizeObserver.observe(containerRef.value)
}

onMounted(initChart)

// option 数据变化 → 增量合并（不重设主题基座）
watch(
  () => props.options,
  () => {
    if (chart) chart.setOption(buildOption(), false)
  },
  { deep: true }
)

// 主题切换 → 颜色基座重算，整体重设
watch(
  () => colors.value,
  () => {
    if (chart) chart.setOption(buildOption(), true)
  },
  { deep: true }
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  if (chart) {
    chart.dispose()
    chart = null
  }
})

defineExpose({ getChart: () => chart })
</script>

<style scoped>
.base-chart {
  width: 100%;
  min-height: 200px;
}
</style>
