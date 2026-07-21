<template>
  <div>
    <!-- Toolbar -->
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px">
      <div>
        <el-button @click="handleZoomIn" :icon="ZoomIn" size="small">{{ t('dag.zoomIn') }}</el-button>
        <el-button @click="handleZoomOut" :icon="ZoomOut" size="small">{{ t('dag.zoomOut') }}</el-button>
        <el-button @click="handleReset" size="small">{{ t('dag.reset') }}</el-button>
        <el-button @click="fetchDAG" :icon="Refresh" size="small">{{ t('dag.refresh') }}</el-button>
      </div>
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-size: 13px; color: var(--theme-text-regular)">
          {{ t('dag.nodes') }}: {{ nodeCount }} &nbsp; {{ t('dag.edges') }}: {{ edgeCount }}
        </span>
        <el-select v-model="statusFilter" :placeholder="t('dag.filterStatus')" clearable size="small" style="width: 160px" @change="renderChart">
          <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </div>
    </div>

    <!-- Empty state -->
    <el-empty v-if="nodeCount === 0 && !loading" :description="t('dag.noData')" />

    <!-- Chart container -->
    <el-card v-show="nodeCount > 0">
      <div ref="chartRef" style="height: calc(100vh - 220px); min-height: 400px; width: 100%"></div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import echarts from '@/utils/echarts'
import { ZoomIn, ZoomOut, Refresh } from '@element-plus/icons-vue'
import { dagApi } from '../api'
import { STATUS_COLORS as SHARED_STATUS_COLORS } from '@/utils/status'
import type { TaskDAGNode, TaskDAGEdge } from '../types'

const { t } = useI18n()
const router = useRouter()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const nodes = ref<TaskDAGNode[]>([])
const edges = ref<TaskDAGEdge[]>([])
const loading = ref(false)
const statusFilter = ref<string>('')

const nodeCount = computed(() => nodes.value.length)
const edgeCount = computed(() => edges.value.length)

const statusOptions = computed(() => [
  { value: 'pending', label: t('dag.statusPending') },
  { value: 'planning', label: t('dag.statusPlanning') },
  { value: 'awaiting_approval', label: t('dag.statusAwaitingApproval') },
  { value: 'executing', label: t('dag.statusExecuting') },
  { value: 'completed', label: t('dag.statusCompleted') },
  { value: 'failed', label: t('dag.statusFailed') },
  { value: 'cancelled', label: t('dag.statusCancelled') },
])

const STATUS_COLORS: Record<string, string> = {
  ...SHARED_STATUS_COLORS,
  pending: '#909399',
  planning: '#409eff',
  cancelled: '#606266',
}

const resizeHandler = () => chartInstance?.resize()

function buildEchartsOption(filteredNodes: TaskDAGNode[], filteredEdges: TaskDAGEdge[]) {
  const categorySet = new Set(filteredNodes.map((n) => n.status))
  const categories = Array.from(categorySet).map((status: string) => ({
    name: status,
    itemStyle: { color: STATUS_COLORS[status] || '#909399' },
  }))

  const echartsNodes = filteredNodes.map((n) => ({
    id: n.id,
    name: n.name,
    category: categorySet.has(n.status) ? Array.from(categorySet).indexOf(n.status) : 0,
    symbolSize: 36,
    itemStyle: {
      color: STATUS_COLORS[n.status] || '#909399',
      borderColor: '#fff',
      borderWidth: 2,
    },
    label: {
      show: true,
      fontSize: 11,
      color: '#fff',
      formatter: (params: { name?: string }) => {
        const name = params.name || ''
        return name.length > 18 ? name.slice(0, 18) + '...' : name
      },
    },
    tooltip: {
      formatter: () => {
        const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
        const risk = n.risk_level ? `<br/>${t('dag.riskLabel')}${esc(n.risk_level)}` : ''
        return `<strong>${esc(n.name)}</strong><br/>${t('dag.statusLabel')}${esc(n.status)}${risk}`
      },
    },
  }))

  const echartsEdges = filteredEdges
    .filter((e) => filteredNodes.some((n) => n.id === e.source) && filteredNodes.some((n) => n.id === e.target))
    .map((e) => ({
      source: e.source,
      target: e.target,
      lineStyle: {
        color: '#aaa',
        width: 2,
        curveness: 0.2,
      },
    }))

  return {
    tooltip: {
      trigger: 'item',
      confine: true,
    },
    legend: {
      data: categories.map((c) => c.name),
      bottom: 0,
      type: 'scroll',
      textStyle: { fontSize: 12 },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        animation: true,
        draggable: true,
        roam: true,
        zoom: 1,
        force: {
          repulsion: 300,
          gravity: 0.1,
          edgeLength: [100, 200],
          friction: 0.6,
        },
        categories,
        data: echartsNodes,
        edges: echartsEdges,
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [4, 10],
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 4 },
        },
      },
    ],
  }
}

function renderChart() {
  if (!chartRef.value) return

  let filteredNodes = nodes.value
  let filteredEdges = edges.value

  if (statusFilter.value) {
    const visibleIds = new Set(filteredNodes.filter((n) => n.status === statusFilter.value).map((n) => n.id))
    // Also include connected nodes
    const connectedIds = new Set(visibleIds)
    filteredEdges.forEach((e) => {
      if (visibleIds.has(e.source) || visibleIds.has(e.target)) {
        connectedIds.add(e.source)
        connectedIds.add(e.target)
      }
    })
    filteredNodes = filteredNodes.filter((n) => connectedIds.has(n.id))
    filteredEdges = filteredEdges.filter((e) => connectedIds.has(e.source) && connectedIds.has(e.target))
  }

  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }

  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(buildEchartsOption(filteredNodes, filteredEdges))

  chartInstance.on('click', (params: unknown) => {
    const p = params as { dataType?: string; data?: { id?: string } }
    if (p.dataType === 'node' && p.data?.id) {
      router.push({ name: 'TaskDetail', params: { id: p.data.id } })
    }
  })
}

function handleZoomIn() {
  if (chartInstance) {
    const opt = chartInstance.getOption() as { series?: { zoom?: number }[] }
    const currentZoom = opt?.series?.[0]?.zoom ?? 1
    chartInstance.setOption({ series: [{ zoom: Math.min(currentZoom * 1.3, 5) }] })
  }
}

function handleZoomOut() {
  if (chartInstance) {
    const opt = chartInstance.getOption() as { series?: { zoom?: number }[] }
    const currentZoom = opt?.series?.[0]?.zoom ?? 1
    chartInstance.setOption({ series: [{ zoom: Math.max(currentZoom / 1.3, 0.3) }] })
  }
}

function handleReset() {
  statusFilter.value = ''
  if (chartInstance) {
    chartInstance.setOption({ series: [{ zoom: 1, center: undefined }] })
  }
  renderChart()
}

async function fetchDAG() {
  loading.value = true
  try {
    const res = await dagApi.getGraph()
    nodes.value = res.nodes || []
    edges.value = res.edges || []
  } catch (e) {
    console.error('Failed to load DAG', e)
  } finally {
    loading.value = false
  }
  await nextTick()
  renderChart()
}

onMounted(() => {
  window.addEventListener('resize', resizeHandler)
  fetchDAG()
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})
</script>

<style scoped>
</style>
