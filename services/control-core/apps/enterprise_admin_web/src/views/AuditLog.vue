<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; gap: 10px">
      <el-input v-model="filters.task_id" :placeholder="t('audit.taskId')" clearable style="width: 280px" @clear="loadEvents" />
      <el-select v-model="filters.event_type" :placeholder="t('audit.eventType')" clearable style="width: 200px" @change="loadEvents">
        <el-option v-for="et in eventTypes" :key="et" :label="et" :value="et" />
      </el-select>
      <el-button type="primary" @click="loadEvents">{{ t('common.search') }}</el-button>
    </div>

    <el-table :data="events" stripe v-loading="loading">
      <el-table-column :label="t('common.time')" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="event_type" :label="t('audit.event')" width="200">
        <template #default="{ row }">
          <el-tag size="small">{{ row.event_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="task_id" :label="t('audit.taskId')" width="280" show-overflow-tooltip />
      <el-table-column prop="step_id" :label="t('audit.stepId')" width="280" show-overflow-tooltip />
      <el-table-column prop="actor" :label="t('audit.actor')" width="100" />
      <el-table-column :label="t('audit.detail')" show-overflow-tooltip>
        <template #default="{ row }">
          <pre style="margin: 0; font-size: 12px">{{ row.detail ? JSON.stringify(row.detail, null, 2) : '-' }}</pre>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="50"
      :total="total"
      layout="total, prev, pager, next"
      style="margin-top: 16px; justify-content: center"
      @current-change="loadEvents"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAuditEvents } from '../api'
import { formatTime } from '@/utils/format'
import { useAsyncData } from '@/composables/useAsyncData'
import type { AuditEvent } from '../types'

const { t } = useI18n()

const eventTypes = [
  'task_created', 'plan_generated', 'policy_check', 'policy_approved', 'policy_rejected',
  'step_executing', 'step_completed', 'step_failed',
  'task_completed', 'task_failed', 'task_cancelled',
  'memory_written', 'skill_extracted', 'skill_approved',
  'approval_requested', 'approval_granted', 'approval_rejected',
]

const page = ref(1)
const total = ref(0)
const filters = ref({ task_id: '', event_type: '' })

const { data: events, loading, execute: loadEvents } = useAsyncData<AuditEvent[]>(async () => {
  const params: Record<string, unknown> = { skip: (page.value - 1) * 50, limit: 50 }
  if (filters.value.task_id) params.task_id = filters.value.task_id
  if (filters.value.event_type) params.event_type = filters.value.event_type
  const res = await getAuditEvents(params)
  total.value = res.data?.length || 0
  return res.data || []
}, [])

onMounted(loadEvents)
</script>
