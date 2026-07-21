<script setup lang="ts">
import {
  NText,
  NIcon,
  NScrollbar,
  NProgress,
  NSpin,
} from 'naive-ui'
import {
  CheckmarkCircleOutline,
  InformationCircleOutline,
  AlertCircleOutline,
  RefreshOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { ExecutionTask } from '@/utils/wizard-execution'

const { t } = useI18n()

defineProps<{
  isExecuting: boolean
  executionTasks: ExecutionTask[]
}>()

function getTaskStatusColor(status: string): string {
  switch (status) {
    case 'completed': return '#18a058'
    case 'failed': return '#d03050'
    case 'in_progress': return '#2080f0'
    default: return '#909399'
  }
}

function getTaskStatusIcon(status: string) {
  switch (status) {
    case 'completed': return CheckmarkCircleOutline
    case 'failed': return AlertCircleOutline
    case 'in_progress': return RefreshOutline
    default: return InformationCircleOutline
  }
}
</script>

<template>
  <div class="wizard-step-panel wizard-step-execution">
    <div class="execution-header">
      <NSpin v-if="isExecuting" size="small" />
      <NIcon v-else :component="CheckmarkCircleOutline" size="20" style="color: #18a058;" />
      <NText strong style="margin-left: 8px;">
        {{ isExecuting ? t('pages.office.wizard.executing') : t('pages.office.wizard.executionComplete') }}
      </NText>
    </div>

    <NScrollbar style="max-height: 390px; padding-right: 4px;">
      <div class="execution-tasks">
        <div
          v-for="task in executionTasks"
          :key="task.id"
          class="execution-task-item"
          :class="`status-${task.status}`"
        >
          <div class="execution-task-icon" :style="{ color: getTaskStatusColor(task.status) }">
            <NIcon :component="getTaskStatusIcon(task.status)" />
          </div>
          <div class="execution-task-content">
            <NText strong style="font-size: 13px;">{{ task.label }}</NText>
            <NText depth="3" style="font-size: 11px;">{{ task.detail }}</NText>
          </div>
          <NProgress
            v-if="task.status === 'in_progress'"
            type="circle"
            :percentage="50"
            :show-indicator="false"
            :stroke-width="16"
            style="width: 20px; height: 20px;"
          />
        </div>
      </div>
    </NScrollbar>
  </div>
</template>

<style scoped>
.wizard-step-execution {
  display: flex;
  flex-direction: column;
}

.execution-header {
  display: flex;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
  margin-bottom: 12px;
}

.execution-tasks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.execution-task-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  border-left: 3px solid transparent;
}

.execution-task-item.status-pending {
  border-left-color: #909399;
}

.execution-task-item.status-in_progress {
  border-left-color: #2080f0;
}

.execution-task-item.status-completed {
  border-left-color: #18a058;
}

.execution-task-item.status-failed {
  border-left-color: #d03050;
}

.execution-task-icon {
  flex-shrink: 0;
  width: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.execution-task-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
</style>
