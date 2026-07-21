<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; gap: 10px">
      <el-button type="primary" @click="openDialog()">{{ t('cron.createJob') }}</el-button>
    </div>

    <el-table :data="jobs" stripe v-loading="loading">
      <el-table-column prop="name" :label="t('common.name')" width="180" />
      <el-table-column prop="schedule" :label="t('cron.schedule')" width="140" />
      <el-table-column prop="goal" :label="t('common.goal')" show-overflow-tooltip />
      <el-table-column prop="edition" :label="t('common.edition')" width="120">
        <template #default="{ row }">
          <el-tag :type="row.edition === 'enterprise' ? 'primary' : 'success'" size="small">{{ row.edition }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.enabled')" width="100" align="center">
        <template #default="{ row }">
          <el-switch
            :model-value="row.enabled"
            @change="(val: boolean) => handleToggle(row, val)"
          />
        </template>
      </el-table-column>
      <el-table-column :label="t('cron.lastRun')" width="160">
        <template #default="{ row }">{{ formatTime(row.last_run_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('cron.contextSources')" width="140" align="center">
        <template #default="{ row }">
          <template v-if="row.context_from && row.context_from.length">
            <el-tag v-for="src in row.context_from" :key="src" size="small" style="margin: 2px">{{ src }}</el-tag>
          </template>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="openDialog(row)">{{ t('common.edit') }}</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? t('cron.editCronJob') : t('cron.createCronJob')"
      width="560px"
      destroy-on-close
    >
      <el-form :model="form" label-width="120px" label-position="right">
        <el-form-item :label="t('common.name')" required>
          <el-input v-model="form.name" :placeholder="t('cron.namePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('cron.schedule')" required>
          <el-input v-model="form.schedule" :placeholder="t('cron.schedulePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.goal')" required>
          <el-input v-model="form.goal" type="textarea" :rows="3" :placeholder="t('cron.goalPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.edition')">
          <el-select v-model="form.edition" style="width: 100%">
            <el-option :label="t('common.enterprise')" value="enterprise" />
            <el-option :label="t('common.personal')" value="personal" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('common.enabled')">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item :label="t('cron.contextFrom')">
          <el-select
            v-model="form.context_from"
            multiple
            filterable
            allow-create
            default-first-option
            :placeholder="t('cron.contextFromPlaceholder')"
            style="width: 100%"
          >
            <el-option :label="t('cron.memory')" value="memory" />
            <el-option :label="t('cron.skills')" value="skills" />
            <el-option :label="t('cron.tasks')" value="tasks" />
            <el-option :label="t('cron.conversation')" value="conversation" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cronApi } from '../api'
import { formatTime } from '@/utils/format'
import { useAsyncData } from '@/composables/useAsyncData'
import type { CronJob } from '../types'

const { t } = useI18n()

const dialogVisible = ref(false)
const submitting = ref(false)
const isEditing = ref(false)
const editingId = ref('')

const defaultForm = () => ({
  name: '',
  schedule: '',
  goal: '',
  edition: 'enterprise',
  enabled: true,
  context_from: [] as string[],
})

const form = reactive(defaultForm())

const { data: jobs, loading, execute: loadJobs } = useAsyncData<CronJob[]>(() => cronApi.list(), [])

function openDialog(row?: CronJob) {
  if (row) {
    isEditing.value = true
    editingId.value = row.id
    Object.assign(form, {
      name: row.name,
      schedule: row.schedule,
      goal: row.goal,
      edition: row.edition || 'enterprise',
      enabled: row.enabled ?? true,
      context_from: row.context_from ? [...row.context_from] : [],
    })
  } else {
    isEditing.value = false
    editingId.value = ''
    Object.assign(form, defaultForm())
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.name.trim() || !form.schedule.trim() || !form.goal.trim()) {
    ElMessage.warning(t('cron.requiredFields'))
    return
  }
  submitting.value = true
  try {
    const payload = {
      name: form.name.trim(),
      schedule: form.schedule.trim(),
      goal: form.goal.trim(),
      edition: form.edition,
      enabled: form.enabled,
      context_from: form.context_from,
    }
    if (isEditing.value) {
      await cronApi.update(editingId.value, payload)
      ElMessage.success(t('cron.jobUpdated'))
    } else {
      await cronApi.create(payload)
      ElMessage.success(t('cron.jobCreated'))
    }
    dialogVisible.value = false
    loadJobs()
  } finally {
    submitting.value = false
  }
}

async function handleToggle(row: CronJob, val: boolean) {
  try {
    await cronApi.update(row.id, { ...row, enabled: val })
    row.enabled = val
    ElMessage.success(val ? t('cron.jobEnabled') : t('cron.jobDisabled'))
  } catch {
    loadJobs()
  }
}

async function handleDelete(row: CronJob) {
  await ElMessageBox.confirm(
    t('cron.deleteConfirm', { name: row.name }),
    t('common.confirm'),
    {
      confirmButtonText: t('common.delete'),
      cancelButtonText: t('common.cancel'),
      type: 'warning',
    }
  )
  await cronApi.delete(row.id)
  ElMessage.success(t('cron.jobDeleted'))
  loadJobs()
}

onMounted(loadJobs)
</script>
