/**
 * ECharts lifecycle composable — shared chart instances + resize handler + auto dispose.
 * Used by Dashboard.vue and AnalyticsView.vue.
 */
import { onMounted, onUnmounted } from 'vue'
import type { EChartsType } from '@/utils/echarts'

export function useEchartsChart() {
  const chartInstances: EChartsType[] = []

  const resizeHandler = () => chartInstances.forEach(c => c.resize())

  function disposeAll() {
    chartInstances.forEach(c => c.dispose())
    chartInstances.length = 0
  }

  onMounted(() => {
    window.addEventListener('resize', resizeHandler)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', resizeHandler)
    disposeAll()
  })

  return { chartInstances, disposeAll, resizeHandler }
}
