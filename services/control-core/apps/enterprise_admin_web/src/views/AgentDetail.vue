<template>
  <div v-loading="loading">
    <div style="display: flex; align-items: center; margin-bottom: 16px">
      <el-page-header @back="router.back()" :content="agent?.name || t('agents.agentDetail')" />
    </div>

    <div v-if="agent">
      <!-- Top info card -->
      <el-card shadow="never">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px">
          <span v-if="agent.emoji" style="font-size: 28px">{{ agent.emoji }}</span>
          <h2 style="margin: 0">{{ agent.name }}</h2>
          <el-tag :type="agentTypeTagType(agent.agent_type)" size="small">{{ agent.agent_type }}</el-tag>
          <el-tag :type="agentStateType(agent.state)" size="small">{{ agent.state }}</el-tag>
          <el-tag type="info" size="small">{{ agent.phase }}</el-tag>
        </div>
        <p v-if="agent.description" style="color: var(--theme-text-regular); margin: 0">{{ agent.description }}</p>
      </el-card>

      <!-- Stats row -->
      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic :title="t('agents.currentTasks')" :value="agent.current_task_count" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic :title="t('agents.successCount')" :value="agent.success_count" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic :title="t('agents.failureCount')" :value="agent.failure_count" />
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never">
            <el-statistic :title="t('agents.maxConcurrent')" :value="agent.max_concurrent_tasks" />
          </el-card>
        </el-col>
      </el-row>

      <!-- Tabs -->
      <el-tabs style="margin-top: 20px" v-model="activeTab">
        <el-tab-pane :label="t('agents.tasks')" name="tasks">
          <el-table :data="tasks" stripe size="small">
            <el-table-column prop="title" :label="t('common.name')" show-overflow-tooltip />
            <el-table-column prop="state" :label="t('agents.state')" width="120">
              <template #default="{ row }">
                <el-tag size="small">{{ row.state }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" :label="t('agents.priority')" width="100" />
            <el-table-column prop="progress" :label="t('agents.progress')" width="120">
              <template #default="{ row }">
                <el-progress :percentage="row.progress" :stroke-width="14" style="width: 100px" />
              </template>
            </el-table-column>
            <el-table-column :label="t('agents.updated')" width="160">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="t('agents.capabilities')" name="capabilities">
          <el-table :data="agent.capabilities" stripe size="small">
            <el-table-column prop="name" :label="t('common.name')" width="200" />
            <el-table-column prop="description" :label="t('common.description')" show-overflow-tooltip />
            <el-table-column :label="t('agents.skillTags')" width="300">
              <template #default="{ row }">
                <el-tag v-for="tag in row.skill_tags" :key="tag" size="small" style="margin-right: 4px">{{ tag }}</el-tag>
                <span v-if="!row.skill_tags?.length">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="t('agents.config')" name="config">
          <el-descriptions :column="1" border v-if="agent.config && Object.keys(agent.config).length">
            <el-descriptions-item v-for="(value, key) in agent.config" :key="key" :label="String(key)">
              <pre style="margin: 0; font-size: 12px">{{ typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value) }}</pre>
            </el-descriptions-item>
          </el-descriptions>
          <el-empty v-else :description="t('agents.noConfigData')" />
        </el-tab-pane>

        <el-tab-pane :label="t('agents.heartbeat')" name="heartbeat">
          <el-descriptions :column="1" border>
            <el-descriptions-item :label="t('agents.lastHeartbeat')">{{ agent.last_heartbeat ? formatTime(agent.last_heartbeat) : '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('agents.workspace')">{{ agent.workspace || '-' }}</el-descriptions-item>
            <el-descriptions-item :label="t('agents.priorityWeight')">{{ agent.priority_weight }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { agentsApi } from '@/api/agent-control'
import { formatTime } from '@/utils/format'
import { agentStateType } from '@/utils/status'
import { useAsyncData } from '@/composables/useAsyncData'
import type { Agent } from '@/types'

const { t } = useI18n()
const props = defineProps<{ id: string }>()
const router = useRouter()
const activeTab = ref('tasks')

const tasks = ref<unknown[]>([])

function agentTypeTagType(type: string): string {
  return ({ general: 'primary', codegen: 'success', data_analysis: 'warning', domain: 'danger' } as Record<string, string>)[type] ?? 'info'
}

const { data: agent, loading, execute: loadAgent } = useAsyncData<Agent>(async () => {
  const res = await agentsApi.get(props.id)
  return res
})

async function loadTasks() {
  try {
    const res = await agentsApi.getTasks(props.id)
    tasks.value = res.items || []
  } catch {
    tasks.value = []
  }
}

onMounted(async () => {
  await loadAgent()
  loadTasks()
})
</script>
