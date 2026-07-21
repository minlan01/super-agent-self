<template>
  <div v-loading="loading">
    <div style="display: flex; align-items: center; margin-bottom: 16px">
      <el-page-header @back="$router.push('/tasks')" />
      <div style="margin-left: auto; display: flex; align-items: center; gap: 12px">
        <!-- Live badge -->
        <el-tag v-if="wsConnected" type="success" effect="dark" size="small" round>
          <span style="display: inline-flex; align-items: center; gap: 4px">
            <span
              style="width: 6px; height: 6px; border-radius: 50%; background: #fff; display: inline-block"
            />
            {{ t('taskLive.liveUpdates') }}
          </span>
        </el-tag>
        <!-- Connection indicator -->
        <span
          :style="{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: wsConnected ? 'var(--theme-color-success)' : 'var(--theme-color-info)',
            display: 'inline-block',
          }"
          :title="wsConnected ? t('taskLive.connected') : t('taskLive.disconnected')"
        />
        <!-- Step progress counter -->
        <span v-if="totalSteps > 0" style="font-size: 13px; color: var(--theme-color-info)">
          {{ t('taskLive.stepProgress') }}: {{ completedStepCount }}/{{ totalSteps }}
        </span>
      </div>
    </div>

    <div v-if="error" style="padding: 20px; text-align: center; color: var(--theme-color-danger)">
      {{ error }}
    </div>
    <el-descriptions :column="2" border v-if="task">
      <el-descriptions-item :label="t('common.id')">{{ task.id }}</el-descriptions-item>
      <el-descriptions-item :label="t('common.status')">
        <el-tag :type="statusType(task.status)">{{ statusLabel(task.status) }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item :label="t('common.edition')">{{ task.edition }}</el-descriptions-item>
      <el-descriptions-item :label="t('task.riskLevel')">{{ task.risk_level || '-' }}</el-descriptions-item>
      <el-descriptions-item :label="t('common.goal')" :span="2">{{ task.goal }}</el-descriptions-item>
      <el-descriptions-item :label="t('common.result')" :span="2" v-if="task.result">
        <el-input type="textarea" :rows="3" :model-value="task.result" readonly />
      </el-descriptions-item>
      <el-descriptions-item :label="t('common.error')" :span="2" v-if="task.error">
        <div style="color: var(--theme-color-danger)">{{ task.error }}</div>
      </el-descriptions-item>
      <el-descriptions-item :label="t('common.created')">{{ formatTime(task.created_at) }}</el-descriptions-item>
      <el-descriptions-item :label="t('common.updated')">{{ formatTime(task.updated_at) }}</el-descriptions-item>
    </el-descriptions>

    <el-tabs style="margin-top: 20px">
      <el-tab-pane :label="t('step.steps')">
        <el-table :data="steps" stripe size="small">
          <el-table-column prop="step_order" :label="t('step.stepOrder')" width="60" />
          <el-table-column prop="tool_name" :label="t('step.tool')" width="160" />
          <el-table-column :label="t('step.args')" show-overflow-tooltip>
            <template #default="{ row }">
              <pre style="margin:0; font-size: 12px">{{ JSON.stringify(row.args, null, 2) }}</pre>
            </template>
          </el-table-column>
          <el-table-column prop="status" :label="t('common.status')" width="120">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="result" :label="t('common.result')" show-overflow-tooltip />
          <el-table-column prop="error" :label="t('common.error')" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>
      <el-tab-pane :label="t('step.auditTrail')">
        <el-timeline>
          <el-timeline-item
            v-for="event in auditEvents" :key="event.id"
            :timestamp="formatTime(event.created_at)"
            placement="top"
          >
            <el-tag size="small" style="margin-right: 8px">{{ event.event_type }}</el-tag>
            <span>{{ event.detail ? JSON.stringify(event.detail) : '-' }}</span>
          </el-timeline-item>
        </el-timeline>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElNotification } from 'element-plus'
import { getTask, getTaskSteps, getTaskAudit } from '../api'
import { formatTime } from '@/utils/format'
import { extendedTaskStatusType as statusType } from '@/utils/status'
import { useTaskWS } from '../composables/useTaskWS'
import type { Task, TaskStep, AuditEvent } from '../types'

const { t } = useI18n()
const props = defineProps<{ id: string }>()
const route = useRoute()
const taskId = props.id || (route.params.id as string)

const task = ref<Task | null>(null)
const steps = ref<TaskStep[]>([])
const auditEvents = ref<AuditEvent[]>([])
const loading = ref(true)
const error = ref<string | null>(null)


const statusLabelMap: Record<string, string> = {
  pending: t('task.statusPending'),
  planning: t('task.statusPlanning'),
  awaiting_approval: t('task.statusAwaitingApproval'),
  executing: t('task.statusExecuting'),
  completed: t('task.statusCompleted'),
  failed: t('task.statusFailed'),
  cancelled: t('task.statusCancelled'),
  approved: t('task.statusApproved'),
  rejected: t('task.statusRejected'),
}
const statusLabel = (s: string) => statusLabelMap[s] || s


// ── WebSocket real-time updates ────────────────────────────────────────────

const {
  connected: wsConnected,
  lastEvent: wsLastEvent,
  taskStatus: wsTaskStatus,
  connect: wsConnect,
  disconnect: wsDisconnect,
} = useTaskWS(taskId)

const totalSteps = computed(() => steps.value.length)
const completedStepCount = computed(() =>
  steps.value.filter((s) => s.status === 'completed' || s.status === 'failed' || s.status === 'rejected').length
)

async function loadData() {
  try {
    const [taskRes, stepsRes, auditRes] = await Promise.all([
      getTask(taskId),
      getTaskSteps(taskId),
      getTaskAudit(taskId),
    ])
    task.value = taskRes.data
    steps.value = stepsRes
    auditEvents.value = auditRes.data ?? []
  } catch {
    error.value = t('common.loadFailed')
  }
}

// Watch for incoming WS events and refresh data on step changes
watch(wsLastEvent, (evt) => {
  if (!evt) return

  if (
    evt.event === 'step_completed' ||
    evt.event === 'step_failed' ||
    evt.event === 'step_rejected'
  ) {
    loadData()
  }
})

// Watch for terminal task events — notify and refresh
watch(wsTaskStatus, (status) => {
  if (status === 'completed') {
    ElNotification({
      title: t('taskLive.taskCompleted'),
      type: 'success',
      duration: 5000,
    })
    loadData()
  } else if (status === 'failed') {
    ElNotification({
      title: t('taskLive.taskFailed'),
      type: 'error',
      duration: 5000,
    })
    loadData()
  }
})

onMounted(async () => {
  await loadData()
  loading.value = false

  // Connect WebSocket after initial data load
  wsConnect()
})

onUnmounted(() => {
  wsDisconnect()
})
</script>
