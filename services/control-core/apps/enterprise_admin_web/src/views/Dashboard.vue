<template>
  <div v-loading="loading">
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="6">
        <StatCard :label="t('task.totalTasks')" :value="stats.totalTasks" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('task.successRate')" :value="`${stats.successRate}%`" :color="stats.successRate >= 80 ? '#67c23a' : '#e6a23c'" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('nav.skills')" :value="stats.totalSkills" />
      </el-col>
      <el-col :span="6">
        <StatCard :label="t('nav.memory')" :value="stats.totalMemories" />
      </el-col>
    </el-row>

    <!-- Charts row -->
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('task.taskStatusDistribution') }}</template>
          <div ref="statusChartRef" style="height: 300px"></div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('skill.skillSuccessRates') }}</template>
          <div ref="skillChartRef" style="height: 300px"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('task.recentTasks') }}</template>
          <el-table :data="recentTasks" stripe size="small">
            <el-table-column prop="goal" :label="t('common.goal')" show-overflow-tooltip />
            <el-table-column prop="status" :label="t('common.status')" width="120">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.time')" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>{{ t('task.pendingApprovals') }}</template>
          <el-table :data="pendingApprovals" stripe size="small">
            <el-table-column prop="approval_type" :label="t('common.type')" width="120" />
            <el-table-column prop="reason" :label="t('task.reason')" show-overflow-tooltip />
            <el-table-column :label="t('common.time')" width="160">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import echarts, { createPieSeriesOption } from '@/utils/echarts'
import { getTasks, getSkills, getMemories, getApprovals, getMetrics } from '../api'
import { formatTime } from '@/utils/format'
import { taskStatusType as statusType, STATUS_COLORS } from '@/utils/status'
import { useEchartsChart } from '@/composables/useEchartsChart'
import StatCard from '@/components/StatCard.vue'
import type { Task, Skill, Approval } from '../types'

const { t } = useI18n()

const stats = ref({
  totalTasks: 0,
  successRate: 0,
  totalSkills: 0,
  totalMemories: 0,
})
const recentTasks = ref<Task[]>([])
const pendingApprovals = ref<Approval[]>([])
const loading = ref(true)

const statusChartRef = ref<HTMLElement>()
const skillChartRef = ref<HTMLElement>()

const { chartInstances, disposeAll } = useEchartsChart()


function renderStatusChart(tasks: Task[]) {
  if (!statusChartRef.value) return
  const chart = echarts.init(statusChartRef.value)
  chartInstances.push(chart)

  const statusCounts: Record<string, number> = {}
  for (const t of tasks) {
    statusCounts[t.status] = (statusCounts[t.status] || 0) + 1
  }

  const colorMap = STATUS_COLORS

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0, type: 'scroll' },
    series: [createPieSeriesOption(
      Object.entries(statusCounts).map(([name, value]) => ({
        name, value,
        itemStyle: { color: colorMap[name] || '#409eff' },
      })),
    )],
  })
}

function renderSkillChart(skills: Skill[]) {
  if (!skillChartRef.value) return
  const chart = echarts.init(skillChartRef.value)
  chartInstances.push(chart)

  const topSkills = skills.slice(0, 10)

  chart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: topSkills.map((s) => s.name?.length > 12 ? s.name.slice(0, 12) + '...' : s.name || t('common.unknown')),
      axisLabel: { rotate: 30 },
    },
    yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: topSkills.map((s) => ({
        value: Math.round((s.success_rate || 0) * 100),
        itemStyle: {
          color: (s.success_rate || 0) >= 0.8 ? '#67c23a'
            : (s.success_rate || 0) >= 0.5 ? '#e6a23c' : '#f56c6c',
        },
      })),
      barMaxWidth: 40,
    }],
  })
}

onMounted(async () => {
  try {
    const [tasksRes, skillsRes, memRes, approvalsRes] = await Promise.all([
      getTasks({ page: 1, page_size: 100 }),
      getSkills({ page: 1, page_size: 50 }),
      getMemories({ page: 1, page_size: 50 }),
      getApprovals({ status: 'pending', page: 1, page_size: 5 }),
    ])

    // Axios interceptor already unwraps response.data, so tasksRes IS the response body
    const taskData = tasksRes || {}
    const tasks = taskData.items || []
    const total = taskData.total || 0

    recentTasks.value = tasks.slice(0, 5)

    // Success rate from all fetched tasks (up to 100)
    const completedCount = tasks.filter((t) => t.status === 'completed').length
    const successRate = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0

    stats.value = {
      totalTasks: total,
      successRate,
      totalSkills: skillsRes.total || 0,
      totalMemories: memRes.total || 0,
    }

    pendingApprovals.value = approvalsRes.items || []

    // Render charts after DOM update
    await nextTick()
    renderStatusChart(tasks)
    renderSkillChart(skillsRes.data || [])
  } catch {
    ElMessage.error(t('common.failedToLoad'))
  } finally {
    loading.value = false
  }
})
</script>
