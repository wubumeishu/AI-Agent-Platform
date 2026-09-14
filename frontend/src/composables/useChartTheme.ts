import { computed } from 'vue'
import { useSettingsStore } from '@/stores/settings'

export interface ChartPalette {
  dark: boolean
  textPrimary: string
  textMuted: string
  border: string
  bgSecondary: string
  primary: string
  success: string
  warning: string
  error: string
  info: string
}

/**
 * 读取当前主题下的图表配色（从 design-token CSS 变量解析为实际色值）。
 *
 * ECharts 的 canvas 渲染器无法解析 `var(--token)`，所以这里用
 * getComputedStyle 读出已解析的十六进制/rgb 值，并挂到 settings store 的
 * isDark 上，主题切换时自动重算。
 */
export function useChartTheme() {
  const settings = useSettingsStore()

  const colors = computed<ChartPalette>(() => {
    void settings.isDark // 响应式依赖：主题切换时重算
    const css = getComputedStyle(document.documentElement)
    const v = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback
    const dark = settings.isDark
    return {
      dark,
      textPrimary: v('--color-text-primary', dark ? '#F9FAFB' : '#111827'),
      textMuted: v('--color-text-muted', dark ? '#6B7280' : '#9CA3AF'),
      border: v('--color-border', dark ? '#374151' : '#E5E7EB'),
      bgSecondary: v('--color-bg-secondary', dark ? '#0F172A' : '#F9FAFB'),
      primary: v('--color-primary', dark ? '#818CF8' : '#4F46E5'),
      success: v('--color-success', dark ? '#34D399' : '#10B981'),
      warning: v('--color-warning', dark ? '#FBBF24' : '#F59E0B'),
      error: v('--color-error', dark ? '#F87171' : '#EF4444'),
      info: '#3B82F6',
    }
  })

  return { colors }
}
