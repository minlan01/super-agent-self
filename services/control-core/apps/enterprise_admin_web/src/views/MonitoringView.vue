<template>
  <div>
    <!-- Row 1: Stat Cards -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>{{ t('monitoring.totalAgents') }}</template>
          <div class="stat-value">{{ overview.total_agents }}</div>
          <div class="stat-breakdown">
            <span style="color: var(--theme-color-success)">{{ overview.active_agents }} {{ t('monitoring.active') }}</span>
            <span style="margin: 0 6px">/</span>
            <span style="color: var(--theme-color-info)">{{ overview.idle_agents }} {{ t('monitoring.idle') }}</span>
            <span style="margin: 0 6px">/</span>
            <span style="color: var(--theme-text-placeholder)">{{ overview.offline_agents }} {{ t('monitoring.offline') }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>{{ t('monitoring.runningTasks') }}</template>
          <div class="stat-value" style="color: var(--theme-color-warning)">{{ overview.running_tasks }}</div>
          <div class="stat-breakdown">
            {{ overview.pending_tasks }} {{ t('monitoring.pending') }} / {{ overview.completed_tasks }} {{ t('monitoring.completed') }}
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>{{ t('monitoring.successRate') }}</template>
          <div class="stat-value" :style="{ color: metrics.success_rate >= 80 ? '#67c23a' : metrics.success_rate >= 50 ? '#e6a23c' : '#f56c6c' }">
            {{ metrics.success_rate }}%
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <template #header>{{ t('monitoring.avgTaskDuration') }}</template>
          <div class="stat-value">{{ formatDuration(metrics.avg_task_duration) }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 2: Agent Overview Pie Chart -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('monitoring.agentOverview') }}</template>
          <div ref="agentChartRef" style="height: 300px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('monitoring.taskDistribution') }}</template>
          <div ref="taskChartRef" style="height: 300px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Row 3: Error Log Table -->
    <el-card>
      <template #header>{{ t('monitoring.errorLog') }}</template>
      <el-table :data="errorLogs" stripe size="small" v-loading="errorsLoading">
        <el-table-column prop="level" :label="t('monitoring.level')" width="100">
          <template #default="{ row }">
            <el-tag :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'info'" size="small">
              {{ row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" :label="t('monitoring.message')" show-overflow-tooltip />
        <el-table-column prop="agent_id" :label="t('monitoring.agent')" width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.agent_id || '-' }}</template>
        </el-table-column>
        <el-table-column :label="t('monitoring.time')" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 16px; display: flex; justify-content: flex-end">
        <el-pagination
          v-model:current-page="errorPage"
          :page-size="errorPageSize"
          :total="errorTotal"
          layout="total, prev, pager, next"
          @current-change="fetchErrors"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import echarts, { createPieSeriesOption } from '@/utils/echarts'
import { monitoringApi } from '@/api/agent-control'
import { formatTime } from '@/utils/format'
import { STATUS_COLORS } from '@/utils/status'
import { useEchartsChart } from '@/composables/useEchartsChart'
import { useAsyncData } from '@/composables/useAsyncData'
import type { MonitoringOverview } from '@/types'

const { t } = useI18n()

// ── Data refs ───────────────────────────────────────────────────────────

const overview = ref<MonitoringOverview>({
  total_agents: 0,
  active_agents: 0,
  idle_agents: 0,
  offline_agents: 0,
  total_tasks: 0,
  pending_tasks: 0,
  running_tasks: 0,
  completed_tasks: 0,
  failed_tasks: 0,
  cancelled_tasks: 0,
})

const metrics = ref({
  success_rate: 0,
  agent_utilization: 0,
  avg_task_duration: 0,
})

const errorLogs = ref<{ id: number; level: string; message: string; agent_id: string | null; created_at: string }[]>([])
const errorPage = ref(1)
const errorPageSize = ref(10)
const errorTotal = ref(0)
const errorsLoading = ref(false)

// ── Chart refs ──────────────────────────────────────────────────────────

const agentChartRef = ref<HTMLElement>()
const taskChartRef = ref<HTMLElement>()

const { chartInstances } = useEchartsChart()

// ── Helpers ─────────────────────────────────────────────────────────────

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

// ── Async data loaders ──────────────────────────────────────────────────

const { execute: loadOverview } = useAsyncData(
  () => monitoringApi.overview(),
  undefined as MonitoringOverview | undefined,
)

const { execute: loadMetrics } = useAsyncData(
  () => monitoringApi.metrics(),
  undefined as { success_rate: number; agent_utilization: number; avg_task_duration: number } | undefined,
)

// ── Chart renderers ─────────────────────────────────────────────────────

function renderAgentChart(data: MonitoringOverview) {
  if (!agentChartRef.value) return
  const chart = echarts.init(agentChartRef.value)
  chartInstances.push(chart)

  const items = [
    { name: 'active', value: data.active_agents, label: t('monitoring.chartActive') },
    { name: 'idle', value: data.idle_agents, label: t('monitoring.chartIdle') },
    { name: 'offline', value: data.offline_agents, label: t('monitoring.chartOffline') },
  ].filter(i => i.value > 0)

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [createPieSeriesOption(
      items.map(i => ({
        name: i.label,
        value: i.value,
        itemStyle: { color: STATUS_COLORS[i.name] || '#409eff' },
      })),
    )],
  })
}

function renderTaskChart(data: MonitoringOverview) {
  if (!taskChartRef.value) return
  const chart = echarts.init(taskChartRef.value)
  chartInstances.push(chart)

  const categories = [
    { key: 'pending', label: t('monitoring.chartPending') },
    { key: 'running', label: t('monitoring.chartRunning') },
    { key: 'completed', label: t('monitoring.chartCompleted') },
    { key: 'failed', label: t('monitoring.chartFailed') },
    { key: 'cancelled', label: t('monitoring.chartCancelled') },
  ]

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: categories.map(c => c.label),
    },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      type: 'bar',
      data: categories.map(c => ({
        value: data[`${c.key}_tasks` as keyof MonitoringOverview] as number,
        itemStyle: { color: STATUS_COLORS[c.key] || '#409eff' },
      })),
      barMaxWidth: 48,
      label: { show: true, position: 'top' },
    }],
  })
}

// ── Error log fetcher ───────────────────────────────────────────────────

async function fetchErrors() {
  errorsLoading.value = true
  try {
    const res = await monitoringApi.errors({ page: errorPage.value, page_size: errorPageSize.value })
    if (res) {
      errorLogs.value = res.items || []
      errorTotal.value = res.total || 0
    }
  } catch {
    ElMessage.error(t('monitoring.failedToLoadErrors'))
  } finally {
    errorsLoading.value = false
  }
}

// ── Main data load ──────────────────────────────────────────────────────

async function fetchAll() {
  try {
    const [overviewRes, metricsRes] = await Promise.all([
      loadOverview(),
      loadMetrics(),
    ])

    if (overviewRes) overview.value = overviewRes
    if (metricsRes) metrics.value = metricsRes

    // Dispose existing charts before re-rendering
    chartInstances.forEach(c => c.dispose())
    chartInstances.length = 0

    await nextTick()
    renderAgentChart(overview.value)
    renderTaskChart(overview.value)
  } catch {
    ElMessage.error(t('monitoring.failedToLoadData'))
  }
}

// ── Lifecycle ───────────────────────────────────────────────────────────

onMounted(() => {
  fetchAll()
  fetchErrors()
})
</script>

<style scoped>
.stat-value {
  font-size: 32px;
  font-weight: bold;
  text-align: center;
  padding: 10px 0;
  color: var(--theme-stat-value-color);
}

.stat-breakdown {
  text-align: center;
  font-size: 13px;
  color: var(--theme-color-info);
  padding-bottom: 4px;
}
</style>
