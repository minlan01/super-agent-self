<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between">
      <div style="display: flex; align-items: center; gap: 12px">
        <h2 style="margin: 0">{{ t('scenario.management') }}</h2>
        <el-select v-model="statusFilter" :placeholder="t('common.status')" clearable style="width: 140px" @change="loadScenarios">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
      </div>
      <el-button type="primary" @click="showCreateDialog = true">{{ t('scenario.createScenario') }}</el-button>
    </div>

    <el-table :data="scenarios" stripe v-loading="loading">
      <el-table-column prop="name" :label="t('common.name')" width="200" show-overflow-tooltip />
      <el-table-column prop="status" :label="t('common.status')" width="120">
        <template #default="{ row }">
          <el-tag :type="scenarioStatusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="agent_selection_mode" :label="t('scenario.selectionMode')" width="140" />
      <el-table-column :label="t('scenario.members')" width="100" align="center">
        <template #default="{ row }">{{ row.members?.length ?? 0 }}</template>
      </el-table-column>
      <el-table-column :label="t('scenario.tasks')" width="100" align="center">
        <template #default="{ row }">{{ row.tasks?.length ?? 0 }}</template>
      </el-table-column>
      <el-table-column :label="t('common.created')" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="240">
        <template #default="{ row }">
          <el-button v-if="row.status === 'draft'" size="small" type="warning" @click="handleActivate(row)">{{ t('scenario.activate') }}</el-button>
          <el-button v-if="row.status === 'active'" size="small" type="success" @click="handleComplete(row)">{{ t('scenario.complete') }}</el-button>
          <el-button size="small" @click="$router.push(`/scenarios/${row.id}`)">{{ t('scenario.viewDetail') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      style="margin-top: 16px; justify-content: center"
      @current-change="loadScenarios"
    />

    <el-dialog v-model="showCreateDialog" :title="t('scenario.createScenario')" width="500px" destroy-on-close>
      <el-form :model="form" label-width="140px">
        <el-form-item :label="t('common.name')" required>
          <el-input v-model="form.name" :placeholder="t('scenario.namePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="form.description" type="textarea" :rows="3" :placeholder="t('scenario.descriptionPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('scenario.selectionMode')">
          <el-select v-model="form.agent_selection_mode" style="width: 100%">
            <el-option :label="t('scenario.modeManual')" value="manual" />
            <el-option :label="t('scenario.modeAuto')" value="auto" />
            <el-option :label="t('scenario.modeBalanced')" value="balanced" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('scenario.coordinatorId')">
          <el-input v-model="form.coordinator_id" :placeholder="t('scenario.coordinatorIdPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" :disabled="!form.name" @click="handleCreate">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { scenariosApi } from '@/api/agent-control'
import { formatTime } from '@/utils/format'
import { scenarioStatusType } from '@/utils/status'
import { useAsyncData } from '@/composables/useAsyncData'
import type { Scenario } from '@/types'

const { t } = useI18n()

const statuses = ['draft', 'active', 'completed', 'archived']

const statusFilter = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const showCreateDialog = ref(false)
const submitting = ref(false)
const form = reactive({
  name: '',
  description: '',
  agent_selection_mode: 'auto',
  coordinator_id: '',
})

const { data: scenarios, loading, execute: loadScenarios } = useAsyncData<Scenario[]>(async () => {
  const params: Record<string, unknown> = { page: page.value, page_size: pageSize }
  if (statusFilter.value) params.status = statusFilter.value
  const res = await scenariosApi.list(params)
  total.value = res.total ?? 0
  return res.items ?? []
}, [])

async function handleCreate() {
  if (!form.name.trim()) return
  submitting.value = true
  try {
    await scenariosApi.create({
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      agent_selection_mode: form.agent_selection_mode,
      coordinator_id: form.coordinator_id.trim() || undefined,
    })
    ElMessage.success(t('scenario.created'))
    showCreateDialog.value = false
    Object.assign(form, { name: '', description: '', agent_selection_mode: 'auto', coordinator_id: '' })
    loadScenarios()
  } finally {
    submitting.value = false
  }
}

async function handleActivate(row: Scenario) {
  try {
    await scenariosApi.activate(String(row.id))
    ElMessage.success(t('scenario.activated'))
    loadScenarios()
  } catch { ElMessage.error(t('scenario.failedToActivate')) }
}

async function handleComplete(row: Scenario) {
  try {
    await scenariosApi.complete(String(row.id))
    ElMessage.success(t('scenario.completed'))
    loadScenarios()
  } catch { ElMessage.error(t('scenario.failedToComplete')) }
}

onMounted(loadScenarios)
</script>
