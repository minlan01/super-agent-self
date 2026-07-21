<template>
  <div style="display: flex; flex-direction: column; gap: 16px">
    <div style="display: flex; justify-content: space-between; align-items: center">
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-size: 18px; font-weight: 600">{{ t('page.systemHealth') }}</span>
        <el-tag :type="readyStatus ? 'success' : 'danger'" size="large">
          {{ readyStatus ? t('health.ready') : t('health.notReady') }}
        </el-tag>
      </div>
      <el-button @click="refresh" :loading="loading">{{ t('common.refresh') }}</el-button>
    </div>

    <!-- Readiness checks -->
    <el-card v-if="readiness">
      <template #header>{{ t('health.readinessChecks') }}</template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item
          v-for="(status, name) in readiness.checks"
          :key="name"
          :label="name"
        >
          <el-tag :type="status === 'ok' ? 'success' : 'danger'" size="small">{{ status }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- Task metrics -->
    <el-card v-if="metrics">
      <template #header>{{ t('health.taskStatistics') }}</template>
      <el-row :gutter="16">
        <el-col :span="6" v-for="(count, status) in metrics.tasks" :key="status">
          <el-statistic :title="String(status)" :value="count" />
        </el-col>
        <el-col :span="6">
          <el-statistic :title="t('health.totalTasks')" :value="metrics.total_tasks" />
        </el-col>
      </el-row>
    </el-card>

    <!-- Memory metrics -->
    <el-card v-if="metrics">
      <template #header>{{ t('health.memoryStatistics') }}</template>
      <el-row :gutter="16">
        <el-col :span="8">
          <el-statistic :title="t('health.totalMemories')" :value="metrics.memories.total" />
        </el-col>
        <el-col :span="8">
          <el-statistic :title="t('health.activeMemories')" :value="metrics.memories.active" />
        </el-col>
        <el-col :span="8">
          <el-statistic :title="t('health.inactive')" :value="metrics.memories.total - metrics.memories.active" />
        </el-col>
      </el-row>
    </el-card>

    <!-- System info -->
    <el-card v-if="metrics">
      <template #header>{{ t('health.systemInfo') }}</template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item :label="t('health.uptime')">{{ formatUptime(metrics.uptime_seconds) }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.version')">{{ metrics.version }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getReadiness, getMetrics } from '../api'
import type { HealthMetrics, ReadinessCheck } from '../types'

const { t } = useI18n()
const loading = ref(false)
const readiness = ref<ReadinessCheck | null>(null)
const metrics = ref<HealthMetrics | null>(null)

const readyStatus = computed(() => readiness.value?.ready ?? false)

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const parts: string[] = []
  if (days > 0) parts.push(`${days}d`)
  if (hours > 0) parts.push(`${hours}h`)
  parts.push(`${minutes}m`)
  return parts.join(' ')
}

async function refresh() {
  loading.value = true
  try {
    const [r, m] = await Promise.all([getReadiness(), getMetrics()])
    readiness.value = r
    metrics.value = m
  } catch {
    ElMessage.error('Failed to load health data')
  }
  finally { loading.value = false }
}

onMounted(refresh)
</script>
