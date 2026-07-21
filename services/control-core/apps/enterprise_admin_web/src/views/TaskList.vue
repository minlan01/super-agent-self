<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between">
      <div>
        <el-select v-model="filters.status" :placeholder="t('common.status')" clearable style="width: 140px; margin-right: 10px" @change="loadTasks">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-select v-model="filters.edition" :placeholder="t('common.edition')" clearable style="width: 140px" @change="loadTasks">
          <el-option :label="t('common.enterprise')" value="enterprise" />
          <el-option :label="t('common.personal')" value="personal" />
        </el-select>
      </div>
      <el-button type="primary" @click="showCreateDialog = true">{{ t('task.newTask') }}</el-button>
    </div>

    <el-table :data="tasks" stripe v-loading="loading">
      <el-table-column prop="id" :label="t('common.id')" width="280" show-overflow-tooltip />
      <el-table-column prop="goal" :label="t('common.goal')" show-overflow-tooltip />
      <el-table-column prop="status" :label="t('common.status')" width="130">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="edition" :label="t('common.edition')" width="110" />
      <el-table-column :label="t('common.created')" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="160">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/tasks/${row.id}`)">{{ t('common.detail') }}</el-button>
          <el-button size="small" type="danger" @click="handleCancel(row)" v-if="canCancel(row.status)">{{ t('task.cancelTask') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      style="margin-top: 16px; justify-content: center"
      @current-change="loadTasks"
    />

    <el-dialog v-model="showCreateDialog" :title="t('task.createTask')" width="500px">
      <el-form :model="newTask" label-width="80px">
        <el-form-item :label="t('common.goal')">
          <el-input v-model="newTask.goal" type="textarea" :rows="3" :placeholder="t('task.describeGoal')" />
        </el-form-item>
        <el-form-item :label="t('common.edition')">
          <el-select v-model="newTask.edition" style="width: 100%">
            <el-option :label="t('common.enterprise')" value="enterprise" />
            <el-option :label="t('common.personal')" value="personal" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleCreate" :disabled="!newTask.goal">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getTasks, createTask, cancelTask } from '../api'
import { formatTime } from '@/utils/format'
import { taskStatusType as statusType } from '@/utils/status'
import type { Task } from '../types'

const { t } = useI18n()

const statuses = ['pending', 'planning', 'executing', 'completed', 'failed', 'cancelled']
const tasks = ref<Task[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const total = ref(0)
const filters = ref({ status: '', edition: '' })
const showCreateDialog = ref(false)
const newTask = ref({ goal: '', edition: 'enterprise' })

const canCancel = (s: string) => ['pending', 'planning', 'awaiting_approval'].includes(s)

async function loadTasks() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize }
    if (filters.value.status) params.status = filters.value.status
    if (filters.value.edition) params.edition = filters.value.edition
    const res = await getTasks(params)
    tasks.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  try {
    await createTask(newTask.value)
    ElMessage.success(t('task.taskCreated'))
    showCreateDialog.value = false
    newTask.value = { goal: '', edition: 'enterprise' }
    loadTasks()
  } catch { ElMessage.error(t('task.failedToCreate')) }
}

async function handleCancel(task: Task) {
  try {
    await cancelTask(task.id)
    ElMessage.success(t('task.taskCancelled'))
    loadTasks()
  } catch { ElMessage.error(t('task.failedToCancel')) }
}

onMounted(loadTasks)
</script>
