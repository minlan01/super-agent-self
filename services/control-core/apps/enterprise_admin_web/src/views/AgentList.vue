<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between">
      <div>
        <el-select v-model="stateFilter" :placeholder="t('agents.state')" clearable style="width: 160px; margin-right: 10px" @change="loadAgents">
          <el-option :label="t('common.all')" value="" />
          <el-option v-for="s in agentStates" :key="s" :label="s" :value="s" />
        </el-select>
      </div>
      <el-button type="primary" @click="showRegisterDialog = true">{{ t('agents.registerAgent') }}</el-button>
    </div>

    <el-table :data="agents" stripe v-loading="loading">
      <el-table-column prop="name" :label="t('agents.agentName')" width="180">
        <template #default="{ row }">
          <span v-if="row.emoji" style="margin-right: 4px">{{ row.emoji }}</span>
          <el-link type="primary" @click="router.push(`/agents/${row.id}`)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="agent_type" :label="t('agents.agentType')" width="130">
        <template #default="{ row }">
          <el-tag :type="agentTypeTagType(row.agent_type)" size="small">{{ row.agent_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="state" :label="t('agents.state')" width="110">
        <template #default="{ row }">
          <el-tag :type="agentStateType(row.state)" size="small">{{ row.state }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="phase" :label="t('agents.phase')" width="110" />
      <el-table-column prop="current_task_count" :label="t('agents.tasks')" width="80" />
      <el-table-column prop="success_count" :label="t('agents.success')" width="80" />
      <el-table-column prop="failure_count" :label="t('agents.failures')" width="80" />
      <el-table-column :label="t('agents.lastHeartbeat')" width="160">
        <template #default="{ row }">{{ formatTime(row.last_heartbeat) }}</template>
      </el-table-column>
      <el-table-column :label="t('agents.actions')" width="100" fixed="right">
        <template #default="{ row }">
          <el-dropdown trigger="click" @command="(cmd: string) => handleAction(cmd, row)">
            <el-button size="small">{{ t('agents.actions') }}</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="pause" :disabled="row.state !== 'running'">{{ t('agents.pause') }}</el-dropdown-item>
                <el-dropdown-item command="resume" :disabled="row.state !== 'idle'">{{ t('agents.resume') }}</el-dropdown-item>
                <el-dropdown-item command="shutdown" divided>{{ t('agents.shutdown') }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided style="color: #f56c6c">{{ t('agents.delete') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showRegisterDialog" :title="t('agents.registerAgent')" width="520px">
      <el-form :model="newAgent" label-width="140px">
        <el-form-item :label="t('agents.agentId')" required>
          <el-input v-model="newAgent.agent_id" :placeholder="t('agents.agentIdPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('agents.agentName')" required>
          <el-input v-model="newAgent.name" :placeholder="t('agents.agentNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('agents.agentType')">
          <el-select v-model="newAgent.agent_type" style="width: 100%">
            <el-option v-for="at in agentTypes" :key="at" :label="at" :value="at" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('agents.agentDescription')">
          <el-input v-model="newAgent.description" type="textarea" :rows="3" :placeholder="t('agents.agentDescriptionPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('agents.skillTags')">
          <el-input v-model="skillTagsInput" :placeholder="t('agents.skillTagsPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('agents.maxConcurrentTasks')">
          <el-input-number v-model="newAgent.max_concurrent_tasks" :min="1" :max="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRegisterDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleRegister" :disabled="!newAgent.agent_id || !newAgent.name">{{ t('agents.registerAgent') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { agentsApi } from '@/api/agent-control'
import { formatTime } from '@/utils/format'
import { agentStateType } from '@/utils/status'
import { useAsyncData } from '@/composables/useAsyncData'
import type { Agent, AgentState, AgentType } from '@/types'

const { t } = useI18n()
const router = useRouter()

const agentStates: AgentState[] = ['idle', 'assigned', 'running', 'completed', 'failed', 'offline']
const agentTypes: AgentType[] = ['general', 'codegen', 'data_analysis', 'domain']

const stateFilter = ref('')
const showRegisterDialog = ref(false)
const skillTagsInput = ref('')

const newAgent = ref({
  agent_id: '',
  name: '',
  agent_type: 'general' as AgentType,
  description: '',
  max_concurrent_tasks: 5,
})

function agentTypeTagType(type: string): string {
  return ({ general: 'primary', codegen: 'success', data_analysis: 'warning', domain: 'danger' } as Record<string, string>)[type] ?? 'info'
}

const { data: agents, loading, execute: loadAgents } = useAsyncData<Agent[]>(async () => {
  const params: Record<string, unknown> = { page: 1, page_size: 50 }
  if (stateFilter.value) params.state = stateFilter.value
  const res = await agentsApi.list(params)
  return res.items || []
}, [])

async function handleRegister() {
  try {
    const skillTags = skillTagsInput.value.trim()
      ? skillTagsInput.value.split(',').map((t) => t.trim()).filter(Boolean)
      : undefined
    await agentsApi.create({
      agent_id: newAgent.value.agent_id,
      name: newAgent.value.name,
      agent_type: newAgent.value.agent_type,
      description: newAgent.value.description || undefined,
      max_concurrent_tasks: newAgent.value.max_concurrent_tasks,
      skill_tags: skillTags,
    })
    ElMessage.success(t('agents.agentRegistered'))
    showRegisterDialog.value = false
    newAgent.value = { agent_id: '', name: '', agent_type: 'general', description: '', max_concurrent_tasks: 5 }
    skillTagsInput.value = ''
    loadAgents()
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : t('agents.failedToRegister'))
  }
}

async function handleAction(command: string, agent: Agent) {
  const id = String(agent.id)
  try {
    if (command === 'delete') {
      await ElMessageBox.confirm(t('agents.deleteConfirm', { name: agent.name }), t('agents.confirmDelete'), { type: 'warning' })
      await agentsApi.delete(id)
      ElMessage.success(t('agents.agentDeleted'))
    } else if (command === 'pause') {
      await agentsApi.pause(id)
      ElMessage.success(t('agents.agentPaused'))
    } else if (command === 'resume') {
      await agentsApi.resume(id)
      ElMessage.success(t('agents.agentResumed'))
    } else if (command === 'shutdown') {
      await agentsApi.shutdown(id)
      ElMessage.success(t('agents.agentShutdown'))
    }
    loadAgents()
  } catch (e: unknown) {
    if (e !== 'cancel') {
      ElMessage.error(e instanceof Error ? e.message : t('agents.failedToAction', { action: command }))
    }
  }
}

onMounted(loadAgents)
</script>
