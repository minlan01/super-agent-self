<script setup lang="ts">
import {
  NText,
  NTag,
  NSpace,
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NCollapse,
  NCollapseItem,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

defineProps<{
  scenarioName: string
  scenarioDescription: string
  agentSelectionMode: 'existing' | 'ai_create'
  selectedAgents: string[]
  aiGeneratedAgentIds: string[]
  getAgentEmoji: (id: string) => string
  getAgentDisplayName: (id: string) => string
  tasks: Array<{
    id: string
    title: string
    description: string
    priority: 'low' | 'medium' | 'high'
    mode: 'run' | 'session'
    assignedAgents: string[]
  }>
  bindingsCount: number
}>()
</script>

<template>
  <div class="wizard-step-panel wizard-step-confirm">
    <NText strong style="font-size: 16px; display: block; margin-bottom: 16px;">
      {{ t('pages.office.wizard.confirmTitle') }}
    </NText>

    <NDescriptions label-placement="left" :column="1" bordered>
      <NDescriptionsItem :label="t('pages.office.wizard.scenarioName')">
        {{ scenarioName }}
      </NDescriptionsItem>
      <NDescriptionsItem :label="t('pages.office.wizard.scenarioDescription')">
        {{ scenarioDescription || '-' }}
      </NDescriptionsItem>
      <NDescriptionsItem :label="t('pages.office.wizard.agentMode')">
        {{ agentSelectionMode === 'existing' ? t('pages.office.wizard.selectExisting') : t('pages.office.wizard.aiCreateAgents') }}
      </NDescriptionsItem>
      <NDescriptionsItem :label="t('pages.office.wizard.agentsCount')">
        {{ agentSelectionMode === 'existing' ? selectedAgents.length : aiGeneratedAgentIds.length }}
      </NDescriptionsItem>
      <NDescriptionsItem :label="t('pages.office.wizard.tasksCount')">
        {{ tasks.length }}
      </NDescriptionsItem>
      <NDescriptionsItem :label="t('pages.office.wizard.bindingsCount')">
        {{ bindingsCount }}
      </NDescriptionsItem>
    </NDescriptions>

    <NDivider />

    <div class="confirm-agents">
      <NText strong style="display: block; margin-bottom: 8px;">{{ t('pages.office.wizard.agentsList') }}</NText>
      <NSpace wrap>
        <NTag v-for="agentId in (agentSelectionMode === 'existing' ? selectedAgents : aiGeneratedAgentIds)" :key="agentId" type="info">
          <span style="margin-right: 4px;">{{ getAgentEmoji(agentId) }}</span>
          {{ getAgentDisplayName(agentId) }}（{{ agentId }}）
        </NTag>
      </NSpace>
    </div>

    <div class="confirm-tasks" style="margin-top: 16px;">
      <NText strong style="display: block; margin-bottom: 8px;">{{ t('pages.office.wizard.tasksList') }}</NText>
      <NCollapse>
        <NCollapseItem
          v-for="task in tasks"
          :key="task.id"
          :name="task.id"
        >
          <template #header>
            <div class="confirm-task-header">
              <NTag :type="task.priority === 'high' ? 'error' : task.priority === 'low' ? 'default' : 'info'" size="small">
                {{ task.priority }}
              </NTag>
              <NText style="margin-left: 8px;">{{ task.title }}</NText>
              <NTag v-if="task.mode === 'session'" type="warning" size="small" style="margin-left: 8px;">
                {{ t('pages.office.wizard.modeSession') }}
              </NTag>
            </div>
          </template>
          <div class="confirm-task-content">
            <div class="confirm-task-info">
              <div class="confirm-task-info-item">
                <NText depth="3" style="font-size: 12px; min-width: 60px;">{{ t('pages.office.wizard.taskTitle') }}:</NText>
                <NText style="font-size: 13px;">{{ task.title }}</NText>
              </div>
              <div v-if="task.description" class="confirm-task-info-item">
                <NText depth="3" style="font-size: 12px; min-width: 60px;">{{ t('pages.office.wizard.taskDescription') }}:</NText>
                <NText depth="2" style="font-size: 13px;">{{ task.description }}</NText>
              </div>
              <div class="confirm-task-info-item">
                <NText depth="3" style="font-size: 12px; min-width: 60px;">{{ t('pages.office.wizard.taskPriority') }}:</NText>
                <NTag :type="task.priority === 'high' ? 'error' : task.priority === 'low' ? 'default' : 'info'" size="small">
                  {{ task.priority === 'high' ? t('pages.office.wizard.priorityHigh') : task.priority === 'low' ? t('pages.office.wizard.priorityLow') : t('pages.office.wizard.priorityMedium') }}
                </NTag>
              </div>
              <div class="confirm-task-info-item">
                <NText depth="3" style="font-size: 12px; min-width: 60px;">{{ t('pages.office.wizard.taskModeLabel') }}:</NText>
                <NTag :type="task.mode === 'session' ? 'warning' : 'success'" size="small">
                  {{ task.mode === 'session' ? t('pages.office.wizard.modeSession') : t('pages.office.wizard.modeRun') }}
                </NTag>
              </div>
              <div class="confirm-task-info-item">
                <NText depth="3" style="font-size: 12px; min-width: 60px;">{{ t('pages.office.wizard.assignAgents') }}:</NText>
                <NSpace>
                  <NTag v-for="agentId in task.assignedAgents" :key="agentId" size="small">
                    <span style="margin-right: 4px;">{{ getAgentEmoji(agentId) }}</span>
                    {{ getAgentDisplayName(agentId) }}
                  </NTag>
                </NSpace>
              </div>
            </div>
          </div>
        </NCollapseItem>
      </NCollapse>
    </div>
  </div>
</template>

<style scoped>
.confirm-task-header {
  display: flex;
  align-items: center;
}

.confirm-task-content {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  margin-top: 4px;
}

.confirm-task-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.confirm-task-info-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
</style>
