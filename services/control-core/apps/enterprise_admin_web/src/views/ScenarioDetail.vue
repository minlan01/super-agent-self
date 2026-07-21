<template>
  <div v-loading="loading">
    <div style="display: flex; align-items: center; margin-bottom: 16px">
      <el-page-header @back="$router.push('/scenarios')" />
    </div>

    <template v-if="scenario">
      <el-card style="margin-bottom: 20px">
        <template #header>
          <div style="display: flex; align-items: center; gap: 12px">
            <h3 style="margin: 0">{{ scenario.name }}</h3>
            <el-tag :type="scenarioStatusType(scenario.status)">{{ scenario.status }}</el-tag>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item :label="t('common.description')" :span="2">{{ scenario.description || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('scenario.selectionMode')">{{ scenario.agent_selection_mode }}</el-descriptions-item>
          <el-descriptions-item :label="t('scenario.coordinator')">{{ scenario.coordinator_id || '-' }}</el-descriptions-item>
          <el-descriptions-item :label="t('common.created')">{{ formatTime(scenario.created_at) }}</el-descriptions-item>
          <el-descriptions-item :label="t('common.updated')">{{ formatTime(scenario.updated_at) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-tabs>
        <el-tab-pane :label="t('scenario.members')">
          <el-table :data="scenario.members" stripe size="small">
            <el-table-column prop="agent_id" :label="t('scenario.agentId')" show-overflow-tooltip />
            <el-table-column prop="role" :label="t('scenario.role')" width="160" />
            <el-table-column prop="channel" :label="t('scenario.channel')" width="200">
              <template #default="{ row }">{{ row.channel || '-' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="t('scenario.tasks')">
          <div style="margin-bottom: 12px">
            <el-button type="primary" size="small" @click="showTaskDialog = true">{{ t('scenario.addTask') }}</el-button>
          </div>
          <el-table :data="scenario.tasks" stripe size="small">
            <el-table-column prop="title" :label="t('scenario.taskTitle')" width="200" show-overflow-tooltip />
            <el-table-column prop="status" :label="t('common.status')" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="scenarioStatusType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" :label="t('scenario.priority')" width="100" />
            <el-table-column :label="t('scenario.assignedAgents')" min-width="180">
              <template #default="{ row }">
                <el-tag v-for="aid in row.assigned_agents" :key="aid" size="small" style="margin: 2px">{{ aid }}</el-tag>
                <span v-if="!row.assigned_agents?.length">-</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.created')" width="170">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="120">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="handleExecuteTask(row)">{{ t('scenario.execute') }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="t('scenario.logs')">
          <el-timeline v-if="scenario.logs?.length">
            <el-timeline-item
              v-for="log in scenario.logs"
              :key="log.id"
              :timestamp="formatTime(log.created_at)"
              placement="top"
            >
              <div style="display: flex; align-items: center; gap: 8px">
                <el-tag :type="logLevelType(log.level)" size="small">{{ log.level }}</el-tag>
                <span>{{ log.message }}</span>
              </div>
              <div v-if="log.agent_id || log.task_id" style="margin-top: 4px; font-size: 12px; color: var(--theme-color-info)">
                <span v-if="log.agent_id">{{ t('scenario.logAgent') }}: {{ log.agent_id }}</span>
                <span v-if="log.agent_id && log.task_id"> | </span>
                <span v-if="log.task_id">{{ t('scenario.logTask') }}: {{ log.task_id }}</span>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else :description="t('scenario.noLogsYet')" />
        </el-tab-pane>

        <el-tab-pane :label="t('scenario.info')">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('scenario.scenarioId')">{{ scenario.scenario_id }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.status')">
              <el-tag :type="scenarioStatusType(scenario.status)">{{ scenario.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item :label="t('common.name')">{{ scenario.name }}</el-descriptions-item>
            <el-descriptions-item :label="t('scenario.selectionMode')">{{ scenario.agent_selection_mode }}</el-descriptions-item>
            <el-descriptions-item :label="t('scenario.coordinator')">{{ scenario.coordinator_id || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('scenario.membersCount')">{{ scenario.members?.length ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('scenario.tasksCount')">{{ scenario.tasks?.length ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('scenario.logsCount')">{{ scenario.logs?.length ?? 0 }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.description')" :span="2">{{ scenario.description || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.created')">{{ formatTime(scenario.created_at) }}</el-descriptions-item>
            <el-descriptions-item :label="t('common.updated')">{{ formatTime(scenario.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="showTaskDialog" :title="t('scenario.addTask')" width="500px" destroy-on-close>
      <el-form :model="taskForm" label-width="120px">
        <el-form-item :label="t('scenario.taskTitle')" required>
          <el-input v-model="taskForm.title" :placeholder="t('scenario.taskTitlePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="taskForm.description" type="textarea" :rows="3" :placeholder="t('scenario.taskDescriptionPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('scenario.assignedAgents')">
          <el-select
            v-model="taskForm.assigned_agents"
            multiple
            filterable
            allow-create
            default-first-option
            :placeholder="t('scenario.agentIdsPlaceholder')"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTaskDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="taskSubmitting" :disabled="!taskForm.title" @click="handleAddTask">{{ t('scenario.add') }}</el-button>
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
import type { Scenario, ScenarioTask } from '@/types'

const { t } = useI18n()

const props = defineProps<{ id: string }>()

const showTaskDialog = ref(false)
const taskSubmitting = ref(false)
const taskForm = reactive({
  title: '',
  description: '',
  assigned_agents: [] as string[],
})

const { data: scenario, loading, execute: loadScenario } = useAsyncData<Scenario>(
  () => scenariosApi.get(props.id),
)

const logLevelType = (level: string): string =>
  ({ error: 'danger', warning: 'warning', info: 'primary', debug: 'info' }[level] ?? 'info')

async function handleAddTask() {
  if (!taskForm.title.trim()) return
  taskSubmitting.value = true
  try {
    await scenariosApi.addTask(props.id, {
      title: taskForm.title.trim(),
      description: taskForm.description.trim() || undefined,
      assigned_agents: taskForm.assigned_agents.length ? taskForm.assigned_agents : undefined,
    })
    ElMessage.success(t('scenario.taskAdded'))
    showTaskDialog.value = false
    Object.assign(taskForm, { title: '', description: '', assigned_agents: [] })
    loadScenario()
  } finally {
    taskSubmitting.value = false
  }
}

async function handleExecuteTask(task: ScenarioTask) {
  try {
    await scenariosApi.executeTask(props.id, String(task.id))
    ElMessage.success(t('scenario.taskExecutionStarted'))
    loadScenario()
  } catch { ElMessage.error(t('scenario.failedToExecuteTask')) }
}

onMounted(loadScenario)
</script>
