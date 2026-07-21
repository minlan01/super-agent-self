import * as echarts from 'echarts/core'
import { PieChart, BarChart, LineChart, GraphChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, BarChart, LineChart, GraphChart,
  TitleComponent, TooltipComponent, LegendComponent, GridComponent, CanvasRenderer])

export default echarts
export type { EChartsType } from 'echarts/core'

/**
 * Creates a common donut-style pie series option used across the app.
 * @param data Array of { name, value, itemStyle? } entries
 * @param options Optional overrides for radius, label, etc.
 */
export function createPieSeriesOption(
  data: Array<{ name: string; value: number; itemStyle?: Record<string, unknown> }>,
  options?: {
    radius?: [string, string]
    avoidLabelOverlap?: boolean
    label?: Record<string, unknown>
  },
): Record<string, unknown> {
  return {
    type: 'pie' as const,
    radius: options?.radius ?? ['40%', '70%'],
    avoidLabelOverlap: options?.avoidLabelOverlap ?? true,
    itemStyle: {
      borderRadius: 6,
      borderColor: getComputedStyle(document.documentElement).getPropertyValue('--theme-chart-border').trim(),
      borderWidth: 2,
    },
    label: options?.label ?? { show: true, formatter: '{b}\n{c}' },
    data,
  }
}
