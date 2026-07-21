<template>
  <div>
    <!-- Date range selector -->
    <div style="margin-bottom: 16px; display: flex; justify-content: flex-end">
      <el-radio-group v-model="daysRange" @change="fetchAll">
        <el-radio-button :value="7">7d</el-radio-button>
        <el-radio-button :value="30">30d</el-radio-button>
        <el-radio-button :value="90">90d</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Top stats row -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6">
        <StatCard :label="t('analytics.totalTasks')" :value="overview.total_tasks" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('analytics.successRate')" :value="`${overview.success_rate}%`" :color="overview.success_rate >= 80 ? '#67c23a' : '#e6a23c'" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('analytics.activeSkills')" :value="overview.active_skills" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('analytics.totalMemories')" :value="overview.total_memories" />
      </el-col>
    </el-row>

    <!-- Real-time Execution Metrics -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6">
        <StatCard label="Running" :value="realtime.running_tasks" color="#409eff" />
      </el-col>
      <el-col :span="6">
        <StatCard label="Completed/h" :value="realtime.completed_last_hour" color="#67c23a" />
      </el-col>
      <el-col :span="6">
        <StatCard label="Failed/h" :value="realtime.failed_last_hour" :color="realtime.failed_last_hour > 3 ? '#f56c6c' : '#e6a23c'" />
      </el-col>
      <el-col :span="6">
        <StatCard label="Tasks/h" :value="realtime.tasks_per_hour" />
      </el-col>
    </el-row>

    <!-- Anomaly Alerts -->
    <el-card v-if="anomalies.length > 0" style="margin-bottom: 20px">
      <template #header>
        <span style="color: #f56c6c; font-weight: 600">Anomaly Alerts</span>
      </template>
      <el-table :data="anomalies" stripe size="small">
        <el-table-column prop="type" label="Type" width="160" />
        <el-table-column prop="severity" label="Severity" width="100">
          <template #default="{ row }">
            <el-tag :type="row.severity === 'critical' ? 'danger' : 'warning'" size="small">
              {{ row.severity }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="Message" show-overflow-tooltip />
        <el-table-column prop="resource" label="Resource" width="140" />
        <el-table-column label="Time" width="180">
          <template #default="{ row }">{{ formatTime(row.detected_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Charts row: Task Trend + Status Distribution -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('analytics.taskTrend') }}</template>
          <div ref="taskTrendChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('analytics.statusDistribution') }}</template>
          <div ref="statusPieChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Charts row: Cost Trend + Cost Breakdown -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>Cost Trend (USD)</template>
          <div ref="costTrendChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>Cost by Provider</template>
          <div ref="costBreakdownChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Charts row: Skill Performance + Memory Growth -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('analytics.skillPerformance') }}</template>
          <div ref="skillBarChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('analytics.memoryGrowth') }}</template>
          <div ref="memoryAreaChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Skill Benchmark: With vs Without Skill Duration -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="24">
        <el-card>
          <template #header>Skill Benchmark: With Skill vs Baseline Duration</template>
          <div ref="skillBenchmarkChartRef" style="height: 320px"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Recent Activity table -->
    <el-card>
      <template #header>{{ t('analytics.recentActivity') }}</template>
      <el-table :data="recentEvents" stripe size="small">
        <el-table-column prop="event_type" :label="t('audit.eventType')" width="180" />
        <el-table-column prop="actor" :label="t('audit.actor')" width="120" />
        <el-table-column prop="task_id" :label="t('audit.taskId')" width="160" show-overflow-tooltip />
        <el-table-column :label="t('common.time')" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('audit.detail')" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.detail ? JSON.stringify(row.detail) : '-' }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import echarts, { createPieSeriesOption } from '@/utils/echarts'
import { analyticsApi } from '../api'
import { formatTime } from '@/utils/format'
import { useEchartsChart } from '@/composables/useEchartsChart'
import StatCard from '@/components/StatCard.vue'
import { STATUS_COLORS } from '@/utils/status'
import type {
  RecentActivityItem, TaskTrendPoint, SkillsPerformanceItem,
  MemoriesGrowthPoint, AnalyticsOverview, RealtimeMetrics,
  CostTrendPoint, CostBreakdownItem, SkillBenchmarkItem, AnomalyAlert,
} from '../types'

const { t } = useI18n()

const daysRange = ref(30)

const overview = ref<AnalyticsOverview>({
  total_tasks: 0,
  completed_tasks: 0,
  failed_tasks: 0,
  active_tasks: 0,
  total_skills: 0,
  active_skills: 0,
  total_memories: 0,
  avg_task_duration: 0,
  success_rate: 0,
  recent_activity_24h: 0,
})

const realtime = ref<RealtimeMetrics>({
  running_tasks: 0,
  completed_last_hour: 0,
  failed_last_hour: 0,
  avg_execution_time_seconds: null,
  tasks_per_hour: 0,
  active_skills: 0,
  total_cost_usd: 0,
})

const anomalies = ref<AnomalyAlert[]>([])
const recentEvents = ref<RecentActivityItem[]>([])

const taskTrendChartRef = ref<HTMLElement>()
const statusPieChartRef = ref<HTMLElement>()
const skillBarChartRef = ref<HTMLElement>()
const memoryAreaChartRef = ref<HTMLElement>()
const costTrendChartRef = ref<HTMLElement>()
const costBreakdownChartRef = ref<HTMLElement>()
const skillBenchmarkChartRef = ref<HTMLElement>()

const { chartInstances, disposeAll } = useEchartsChart()

let realtimeTimer: ReturnType<typeof setInterval> | null = null


function renderTaskTrendChart(trend: { date: string; count: number }[]) {
  if (!taskTrendChartRef.value) return
  const chart = echarts.init(taskTrendChartRef.value)
  chartInstances.push(chart)

  const dates = trend.map(d => d.date)
  const counts = trend.map(d => d.count)

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      type: 'line',
      data: counts,
      smooth: true,
      areaStyle: { opacity: 0.15 },
      itemStyle: { color: '#409eff' },
    }],
  })
}

function renderStatusPieChart(distribution: Record<string, number>) {
  if (!statusPieChartRef.value) return
  const chart = echarts.init(statusPieChartRef.value)
  chartInstances.push(chart)

  const colorMap = STATUS_COLORS

  const data = Object.entries(distribution)
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({
      name, value,
      itemStyle: { color: colorMap[name] || '#409eff' },
    }))

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [createPieSeriesOption(data)],
  })
}

function renderSkillBarChart(skills: { name: string; success_rate: number }[]) {
  if (!skillBarChartRef.value) return
  const chart = echarts.init(skillBarChartRef.value)
  chartInstances.push(chart)

  const topSkills = skills.slice(0, 10)
  const names = topSkills.map(s => s.name?.length > 16 ? s.name.slice(0, 16) + '...' : s.name || 'Unknown')
  const rates = topSkills.map(s => s.success_rate)

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', containLabel: true },
    xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    yAxis: { type: 'category', data: names.reverse(), axisLabel: { width: 120, overflow: 'truncate' } },
    series: [{
      type: 'bar',
      data: rates.reverse().map(v => ({
        value: v,
        itemStyle: {
          color: v >= 80 ? '#67c23a' : v >= 50 ? '#e6a23c' : '#f56c6c',
        },
      })),
      barMaxWidth: 24,
      label: { show: true, position: 'right', formatter: '{c}%' },
    }],
  })
}

function renderMemoryAreaChart(growth: { date: string; cumulative: number }[]) {
  if (!memoryAreaChartRef.value) return
  const chart = echarts.init(memoryAreaChartRef.value)
  chartInstances.push(chart)

  const dates = growth.map(d => d.date)
  const cumulative = growth.map(d => d.cumulative)

  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{
      type: 'line',
      data: cumulative,
      smooth: true,
      areaStyle: { opacity: 0.25, color: '#67c23a' },
      itemStyle: { color: '#67c23a' },
    }],
  })
}

function renderCostTrendChart(trend: CostTrendPoint[]) {
  if (!costTrendChartRef.value) return
  const chart = echarts.init(costTrendChartRef.value)
  chartInstances.push(chart)

  const dates = trend.map(d => d.date)
  const costs = trend.map(d => d.cost_usd)

  chart.setOption({
    tooltip: { trigger: 'axis', formatter: (params: any) => {
      const p = Array.isArray(params) ? params[0] : params
      return `${p.axisValue}<br/>Cost: $${Number(p.value).toFixed(4)}`
    }},
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: dates, boundaryGap: false },
    yAxis: { type: 'value', axisLabel: { formatter: '${value}' } },
    series: [{
      type: 'line',
      data: costs,
      smooth: true,
      areaStyle: { opacity: 0.2, color: '#f56c6c' },
      itemStyle: { color: '#f56c6c' },
    }],
  })
}

function renderCostBreakdownChart(breakdown: CostBreakdownItem[]) {
  if (!costBreakdownChartRef.value) return
  const chart = echarts.init(costBreakdownChartRef.value)
  chartInstances.push(chart)

  const top10 = breakdown.slice(0, 10)
  const labels = top10.map(b => `${b.provider}/${b.model}`)
  const costs = top10.map(b => b.estimated_cost_usd)

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any) => {
      const p = Array.isArray(params) ? params[0] : params
      return `${p.name}<br/>Cost: $${Number(p.value).toFixed(4)}`
    }},
    grid: { left: '3%', right: '8%', bottom: '3%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: '${value}' } },
    yAxis: { type: 'category', data: labels.reverse(), axisLabel: { width: 140, overflow: 'truncate' } },
    series: [{
      type: 'bar',
      data: costs.reverse(),
      barMaxWidth: 24,
      itemStyle: { color: '#e6a23c' },
      label: { show: true, position: 'right', formatter: (p: any) => `$${Number(p.value).toFixed(4)}` },
    }],
  })
}

function renderSkillBenchmarkChart(skills: SkillBenchmarkItem[]) {
  if (!skillBenchmarkChartRef.value) return
  const chart = echarts.init(skillBenchmarkChartRef.value)
  chartInstances.push(chart)

  // Only include skills that have benchmark data
  const benchmarkSkills = skills.filter(s => s.with_skill_duration != null || s.without_skill_duration != null)
  if (benchmarkSkills.length === 0) return

  const names = benchmarkSkills.map(s => s.name?.length > 16 ? s.name.slice(0, 16) + '...' : s.name || 'Unknown')
  const withData = benchmarkSkills.map(s => s.with_skill_duration ?? 0)
  const withoutData = benchmarkSkills.map(s => s.without_skill_duration ?? 0)

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        let html = items[0].axisValue + '<br/>'
        for (const item of items) {
          html += `${item.marker} ${item.seriesName}: ${Number(item.value).toFixed(2)}s<br/>`
        }
        return html
      },
    },
    legend: { data: ['With Skill', 'Without Skill (baseline)'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '12%', top: '8%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}s' } },
    yAxis: { type: 'category', data: names, axisLabel: { width: 140, overflow: 'truncate' } },
    series: [
      {
        name: 'With Skill',
        type: 'bar',
        data: withData,
        barMaxWidth: 20,
        itemStyle: { color: '#67c23a' },
      },
      {
        name: 'Without Skill (baseline)',
        type: 'bar',
        data: withoutData,
        barMaxWidth: 20,
        itemStyle: { color: '#909399' },
      },
    ],
  })
}

async function fetchRealtime() {
  try {
    const res = await analyticsApi.realtimeMetrics()
    if (res) realtime.value = res
  } catch { /* silent */ }
}

async function fetchAnomalies() {
  try {
    const res = await analyticsApi.anomalies()
    if (res) anomalies.value = res.alerts || []
  } catch { /* silent */ }
}

async function fetchAll() {
  try {
    const [overviewRes, trendRes, statusRes, skillsRes, memRes, activityRes, costTrendRes, costSummaryRes, benchmarkRes] = await Promise.all([
      analyticsApi.overview(),
      analyticsApi.taskTrend(daysRange.value),
      analyticsApi.statusDistribution(),
      analyticsApi.skillsPerformance(),
      analyticsApi.memoriesGrowth(daysRange.value),
      analyticsApi.recentActivity(20),
      analyticsApi.costTrend(daysRange.value),
      analyticsApi.costSummary(daysRange.value),
      analyticsApi.skillBenchmark(),
    ])

    overview.value = overviewRes || overview.value
    recentEvents.value = activityRes.events || []

    // Dispose existing charts before re-rendering
    chartInstances.forEach(c => c.dispose())
    chartInstances.length = 0

    await nextTick()
    renderTaskTrendChart(trendRes.trend || [])
    renderStatusPieChart(statusRes.distribution || {})
    renderSkillBarChart(skillsRes.skills || [])
    renderMemoryAreaChart(memRes.growth || [])
    renderCostTrendChart(costTrendRes.trend || [])
    renderCostBreakdownChart(costSummaryRes.breakdown || [])
    renderSkillBenchmarkChart(benchmarkRes.skills || [])
  } catch {
    ElMessage.error('Failed to load analytics data')
  }
}

onMounted(() => {
  fetchAll()
  fetchRealtime()
  fetchAnomalies()
  // Auto-refresh realtime metrics every 30s
  realtimeTimer = setInterval(() => {
    fetchRealtime()
    fetchAnomalies()
  }, 30000)
})

onUnmounted(() => {
  if (realtimeTimer) clearInterval(realtimeTimer)
})
</script>
