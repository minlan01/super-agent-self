<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import {
  NModal,
  NSteps,
  NStep,
  NButton,
  NSpace,
  NInput,
  NRadioGroup,
  NRadio,
  NTag,
  NText,
  NIcon,
  NAlert,
  NEmpty,
  NScrollbar,
  NSpin,
  NTooltip,
  NSelect,
  NCollapse,
  NCollapseItem,
  useMessage,
} from 'naive-ui'
import {
  CreateOutline,
  PeopleOutline,
  ListOutline,
  CheckmarkCircleOutline,
  ArrowForwardOutline,
  ArrowBackOutline,
  SparklesOutline,
  AddOutline,
  TrashOutline,
  PlayOutline,
  LinkOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useWizardStore, type GeneratedAgent, type AgentBinding } from '@/stores/wizard'
import { useOfficeStore } from '@/stores/office'
import { useWebSocketStore } from '@/stores/websocket'
import { useAgentStore } from '@/stores/agent'
import { useConfigStore } from '@/stores/config'
import {
  generateDefaultAgentsMd,
  generateDefaultSoulMd,
  generateDefaultUserMd,
  generateDefaultIdentityMd,
  generateTeamLeaderAgent,
} from '@/utils/wizard-agent-generator'
import {
  buildPreparationTasks,
  executeNextTask,
  executeTaskSendTasks,
  executeCreateAgent,
  type ExecutionDeps,
} from '@/utils/wizard-execution'
import WizardConfirmPanel from './WizardConfirmPanel.vue'
import WizardExecutionPanel from './WizardExecutionPanel.vue'

const { t } = useI18n()
const message = useMessage()
const wizardStore = useWizardStore()
const officeStore = useOfficeStore()
const wsStore = useWebSocketStore()
const agentStore = useAgentStore()
const configStore = useConfigStore()

const wizardStep = ref<'scenario' | 'agents' | 'tasks' | 'bindings' | 'confirm' | 'execution'>('scenario')

const scenarioName = ref('')
const scenarioDescription = ref('')
const agentSelectionMode = ref<'existing' | 'ai_create'>('existing')
const workspaceMode = ref<'independent' | 'shared'>('independent')
const selectedAgents = ref<string[]>([])
const aiAgentPrompt = ref('')
const aiGeneratedAgents = ref<GeneratedAgent[]>([])
const isGeneratingAgents = ref(false)

const tasks = ref<Array<{
  id: string
  title: string
  description: string
  priority: 'low' | 'medium' | 'high'
  assignedAgents: string[]
  mode: 'run' | 'session'
}>>([])

const taskTitle = ref('')
const taskDescription = ref('')
const taskPriority = ref<'low' | 'medium' | 'high'>('medium')
const taskMode = ref<'run' | 'session'>('run')
const taskAssignedAgents = ref<string[]>([])

const bindings = ref<AgentBinding[]>([])
const availableChannels = ref([
  { label: 'Feishu', value: 'feishu' },
  { label: 'WhatsApp', value: 'whatsapp' },
  { label: 'Telegram', value: 'telegram' },
  { label: 'Discord', value: 'discord' },
  { label: 'Slack', value: 'slack' },
])

const isExecuting = ref(false)
const isPreparationComplete = ref(false)
const isTaskExecutionComplete = ref(false)
const executionTasks = ref<Array<{
  id: string
  type: 'create_agent' | 'config_update' | 'task_send' | 'skip_agent' | 'set_identity'
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  label: string
  detail?: string
  agentId?: string
}>>([])

const currentStepIndex = computed(() => {
  const steps = ['scenario', 'agents', 'tasks', 'bindings', 'confirm', 'execution']
  return steps.indexOf(wizardStep.value) + 1
})

function getStepStatus(stepIndex: number): 'process' | 'finish' | 'wait' | 'error' {
  if (stepIndex < currentStepIndex.value) {
    return 'finish'
  } else if (stepIndex === currentStepIndex.value) {
    return 'process'
  } else {
    return 'wait'
  }
}

const canProceed = computed(() => {
  switch (wizardStep.value) {
    case 'scenario':
      return scenarioName.value.trim().length > 0
    case 'agents':
      if (agentSelectionMode.value === 'existing') {
        return selectedAgents.value.length > 0
      } else {
        return aiGeneratedAgents.value.length > 0
      }
    case 'tasks':
      return tasks.value.length > 0
    case 'bindings':
      return true
    case 'confirm':
      return true
    default:
      return true
  }
})

const availableAgents = computed(() => agentStore.agents)

const allAgentIds = computed(() => {
  if (agentSelectionMode.value === 'existing') {
    return selectedAgents.value
  }
  
  const existingAgents = agentStore.agents
  const existingAgentNames = new Map<string, string>()
  existingAgents.forEach(a => {
    if (a.name) {
      existingAgentNames.set(a.name, a.id)
    }
  })
  
  const result: string[] = []
  for (const agent of aiGeneratedAgents.value) {
    const existingId = existingAgentNames.get(agent.name)
    if (existingId) {
      result.push(existingId)
    } else {
      result.push(agent.id)
    }
  }
  
  return result
})

const agentOptions = computed(() => {
  return allAgentIds.value.map(id => {
    const agent = agentStore.agents.find(a => a.id === id)
    const generatedAgent = aiGeneratedAgents.value.find(a => a.id === id)
    const emoji = generatedAgent?.emoji || agent?.identity?.emoji || '🤖'
    const name = generatedAgent?.name || agent?.name || id
    return {
      label: `${emoji} ${name}`,
      value: id,
    }
  })
})

// ─── 执行依赖对象 ─────────────────────────────────────────

const executionDeps = computed<ExecutionDeps>(() => ({
  agentSelectionMode,
  workspaceMode,
  aiGeneratedAgents,
  bindings,
  tasks,
  allAgentIds,
  isExecuting,
  isPreparationComplete,
  isTaskExecutionComplete,
  executionTasks,
  agentStore,
  wsStore,
  configStore,
}))

// ─── 表单操作 ─────────────────────────────────────────────

function resetForm() {
  scenarioName.value = ''
  scenarioDescription.value = ''
  agentSelectionMode.value = 'existing'
  workspaceMode.value = 'independent'
  selectedAgents.value = []
  aiAgentPrompt.value = ''
  aiGeneratedAgents.value = []
  tasks.value = []
  bindings.value = []
  taskTitle.value = ''
  taskDescription.value = ''
  taskPriority.value = 'medium'
  taskMode.value = 'run'
  taskAssignedAgents.value = []
  isExecuting.value = false
  executionTasks.value = []
}

async function handleGenerateAgents() {
  if (!aiAgentPrompt.value.trim()) {
    message.warning(t('pages.office.wizard.aiPromptRequired'))
    return
  }

  isGeneratingAgents.value = true
  aiGeneratedAgents.value = []

  try {
    const agentId = 'main'
    const channel = 'main'
    const peer = 'ai-agent-creator'
    const sessionKey = `agent:${agentId}:${channel}:dm:${peer}`
    const idempotencyKey = `wizard-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`

    const systemPrompt = `这是一个新的任务，请忽略之前的所有对话内容，只关注本次请求。

你是一个团队配置专家。根据用户的需求，生成合适的 AI 智能体团队配置。

请以 JSON 数组格式返回智能体配置，每个智能体包含：
- id: 唯一标识符（使用英文，如 "content-collector"）
- name: 显示名称（中文）
- role: 角色类型（英文，如 "collector", "writer", "reviewer" 等）
- emoji: 代表该角色的 emoji 表情
- skills: 该智能体擅长的技能列表（字符串数组）

示例输出格式：
[
  {"id": "content-collector", "name": "信息收集员", "role": "collector", "emoji": "🔍", "skills": ["信息检索", "数据分析"]},
  {"id": "content-writer", "name": "内容创作员", "role": "writer", "emoji": "✍️", "skills": ["文案写作", "创意策划"]},
  {"id": "content-reviewer", "name": "内容审核员", "role": "reviewer", "emoji": "✅", "skills": ["内容审核", "质量把控"]}
]

只返回 JSON 数组，不要有其他文字。`

    const userMessage = `${systemPrompt}\n\n用户需求：${aiAgentPrompt.value}`

    await wsStore.rpc.sendChatMessage({
      sessionKey,
      message: userMessage,
      idempotencyKey,
    })

    try {
      await wsStore.rpc.patchSession({
        sessionKey,
        label: 'AI自动创建智能体助手',
      })
    } catch (e) {
      console.warn('[Wizard] Failed to set session label:', e)
    }

    let lastMessageContent = ''
    let attempts = 0
    const maxAttempts = 60
    const pollInterval = 1000
    
    while (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, pollInterval))
      attempts++
      
      try {
        const history = await wsStore.rpc.listChatHistory(sessionKey)
        if (history && history.length > 0) {
          const lastMessage = history[history.length - 1]
          if (lastMessage && lastMessage.role === 'assistant' && lastMessage.content) {
            lastMessageContent = lastMessage.content
            break
          }
        }
      } catch (e) {
        console.warn('[Wizard] Poll error:', e)
      }
    }

    if (!lastMessageContent) {
      message.warning(t('pages.office.wizard.agentGenerationFailed'))
      return
    }

    let generated: GeneratedAgent[] = []
    
    const jsonMatch = lastMessageContent.match(/\[[\s\S]*\]/)
    if (jsonMatch) {
      try {
        const parsed = JSON.parse(jsonMatch[0])
        if (Array.isArray(parsed) && parsed.length > 0) {
          const existingAgents = agentStore.agents
          const existingAgentNames = new Map<string, typeof existingAgents[0]>()
          existingAgents.forEach(a => {
            if (a.name) {
              existingAgentNames.set(a.name, a)
            }
          })
          
          generated = parsed.map((item: Record<string, unknown>) => {
            const agentName = (item.name as string) || ''
            const existingAgent = existingAgentNames.get(agentName)
            
            if (existingAgent) {
              return {
                id: existingAgent.id,
                name: existingAgent.name || agentName,
                role: (item.role as string) || 'assistant',
                emoji: (item.emoji as string) || existingAgent.identity?.emoji || '🤖',
                skills: Array.isArray(item.skills) ? item.skills as string[] : [],
                agentsMd: '',
                soulMd: '',
                userMd: '',
                identityMd: '',
                created: false,
              }
            }
            
            return {
              id: item.id as string,
              name: agentName,
              role: (item.role as string) || 'assistant',
              emoji: (item.emoji as string) || '🤖',
              skills: Array.isArray(item.skills) ? item.skills as string[] : [],
              agentsMd: generateDefaultAgentsMd(agentName, (item.role as string) || 'assistant'),
              soulMd: generateDefaultSoulMd(agentName),
              userMd: generateDefaultUserMd(agentName),
              identityMd: generateDefaultIdentityMd(agentName, (item.emoji as string) || '🤖'),
              created: false,
            }
          })
        }
      } catch (e) {
        console.error('[Wizard] Failed to parse generated agents:', e)
        message.error(t('pages.office.wizard.agentGenerationFailed'))
        return
      }
    }

    if (generated.length === 0) {
      message.warning(t('pages.office.wizard.agentGenerationFailed'))
      return
    }

    const teamLeader = generateTeamLeaderAgent(scenarioName.value, generated)
    aiGeneratedAgents.value = [teamLeader, ...generated]
    
    message.success(t('pages.office.wizard.agentsGenerated', { count: aiGeneratedAgents.value.length }))
  } catch (error) {
    console.error('[Wizard] Agent generation error:', error)
    message.error(t('pages.office.wizard.agentGenerationFailed'))
  } finally {
    isGeneratingAgents.value = false
  }
}

function handleRemoveGeneratedAgent(index: number) {
  aiGeneratedAgents.value.splice(index, 1)
}

function handleAddCustomAgent() {
  aiGeneratedAgents.value.push({
    id: `custom-${Date.now()}`,
    name: `自定义角色 ${aiGeneratedAgents.value.length + 1}`,
    role: 'custom',
    emoji: '👤',
    skills: [],
    agentsMd: '',
    soulMd: '',
    userMd: '',
    created: false,
  })
}

function handleAddTask() {
  if (!taskTitle.value.trim()) {
    message.warning(t('pages.office.wizard.taskTitleRequired'))
    return
  }
  
  if (taskAssignedAgents.value.length === 0) {
    message.warning(t('pages.office.wizard.taskAgentRequired'))
    return
  }
  
  tasks.value.push({
    id: `task-${Date.now()}`,
    title: taskTitle.value.trim(),
    description: taskDescription.value.trim(),
    priority: taskPriority.value,
    assignedAgents: [...taskAssignedAgents.value],
    mode: taskMode.value,
  })
  
  taskTitle.value = ''
  taskDescription.value = ''
  taskPriority.value = 'medium'
  taskMode.value = 'run'
  if (aiGeneratedAgents.value.length > 0 && aiGeneratedAgents.value[0]) {
    taskAssignedAgents.value = [aiGeneratedAgents.value[0].id]
  } else {
    taskAssignedAgents.value = []
  }
}

function handleRemoveTask(index: number) {
  tasks.value.splice(index, 1)
}

function getAgentEmoji(agentId: string): string {
  const generatedAgent = aiGeneratedAgents.value.find(a => a.id === agentId)
  if (generatedAgent?.emoji) {
    return generatedAgent.emoji
  }
  const agent = agentStore.agents.find(a => a.id === agentId)
  return agent?.identity?.emoji || '🤖'
}

function getAgentDisplayName(agentId: string): string {
  const generatedAgent = aiGeneratedAgents.value.find(a => a.id === agentId)
  if (generatedAgent?.name) {
    return generatedAgent.name
  }
  const agent = agentStore.agents.find(a => a.id === agentId)
  return agent?.name || agentId
}

function handleAssignAgent(taskIndex: number, agentId: string) {
  const task = tasks.value[taskIndex]
  if (!task) return
  
  const idx = task.assignedAgents.indexOf(agentId)
  if (idx >= 0) {
    task.assignedAgents.splice(idx, 1)
  } else {
    task.assignedAgents.push(agentId)
  }
}

function handleAddBinding() {
  const agentId = allAgentIds.value[0] || ''
  bindings.value.push({
    agentId,
    channel: 'feishu',
    peerId: '',
    peerKind: 'group',
  })
}

function handleRemoveBinding(index: number) {
  bindings.value.splice(index, 1)
}

// ─── 步骤导航 ─────────────────────────────────────────────

async function handleNext() {
  switch (wizardStep.value) {
    case 'scenario':
      const scenario = wizardStore.createScenario({
        name: scenarioName.value.trim(),
        description: scenarioDescription.value.trim(),
        agentSelectionMode: agentSelectionMode.value,
      })
      await wizardStore.saveScenario(scenario)
      wizardStore.setCurrentScenario(scenario)
      wizardStep.value = 'agents'
      break
      
    case 'agents':
      if (wizardStore.currentScenario) {
        if (agentSelectionMode.value === 'ai_create') {
          wizardStore.currentScenario.generatedAgents = [...aiGeneratedAgents.value]
        } else {
          wizardStore.currentScenario.selectedAgents = [...selectedAgents.value]
        }
        await wizardStore.saveScenario(wizardStore.currentScenario)
      }
      wizardStep.value = 'tasks'
      break
      
    case 'tasks':
      if (wizardStore.currentScenario) {
        const wizardTasks = []
        for (const task of tasks.value) {
          const wizardTask = wizardStore.createTask({
            scenarioId: wizardStore.currentScenario!.id,
            title: task.title,
            description: task.description,
            assignedAgents: task.assignedAgents,
            priority: task.priority,
            mode: task.mode,
          })
          await wizardStore.saveTask(wizardTask)
          wizardTasks.push(wizardTask)
        }
        wizardStore.currentScenario.tasks = wizardTasks
        await wizardStore.saveScenario(wizardStore.currentScenario)
      }
      
      await configStore.fetchConfig()
      const existingBindings = configStore.config?.bindings || []
      const agentIds = allAgentIds.value
      
      const existingBindingsMap = new Map<string, typeof existingBindings[0]>()
      for (const b of existingBindings) {
        if (b.agentId) {
          existingBindingsMap.set(b.agentId, b)
        }
      }
      
      bindings.value = agentIds.map((agentId) => {
        const existing = existingBindingsMap.get(agentId)
        if (existing) {
          const channel = existing.match?.channel || 'feishu'
          const accountId = existing.match?.accountId || ''
          const peerId = existing.match?.peer?.id || ''
          const peerKind = existing.match?.peer?.kind || 'group' as const
          
          return {
            agentId,
            accountId,
            channel,
            peerId,
            peerKind,
          }
        }
        
        return {
          agentId,
          accountId: agentId,
          channel: 'feishu',
          peerId: '',
          peerKind: 'group' as const,
        }
      })
      
      wizardStep.value = 'bindings'
      break
      
    case 'bindings':
      if (wizardStore.currentScenario) {
        wizardStore.currentScenario.bindings = [...bindings.value]
        await wizardStore.saveScenario(wizardStore.currentScenario)
      }
      wizardStep.value = 'confirm'
      break
      
    case 'confirm':
      startExecution()
      break
      
    default:
      break
  }
}

function handleBack() {
  switch (wizardStep.value) {
    case 'agents':
      wizardStep.value = 'scenario'
      break
    case 'tasks':
      wizardStep.value = 'agents'
      break
    case 'bindings':
      wizardStep.value = 'tasks'
      break
    case 'confirm':
      wizardStep.value = 'bindings'
      break
    case 'execution':
      wizardStep.value = 'confirm'
      break
    default:
      break
  }
}

// ─── 执行阶段 ─────────────────────────────────────────────

function startExecution() {
  wizardStep.value = 'execution'
  isPreparationComplete.value = false
  buildPreparationTasks(executionDeps.value)
  executeNextTask(executionDeps.value)
}

async function handleExecuteAndClose() {
  await executeTaskSendTasks(executionDeps.value)
  handleClose()
}

function handleClose() {
  resetForm()
  wizardStep.value = 'scenario'
  wizardStore.setCurrentScenario(null)
  officeStore.hideWizard()
}

// ─── 生命周期 ─────────────────────────────────────────────

watch(
  () => wizardStore.currentScenario,
  (scenario) => {
    if (scenario) {
      scenarioName.value = scenario.name
      scenarioDescription.value = scenario.description
      agentSelectionMode.value = scenario.agentSelectionMode
      selectedAgents.value = scenario.selectedAgents
      aiGeneratedAgents.value = scenario.generatedAgents
    }
  }
)

onMounted(() => {
  wizardStore.initialize()
  agentStore.fetchAgents()
  configStore.fetchConfig()
})
</script>

<template>
  <NModal
    :show="officeStore.wizardVisible"
    :mask-closable="false"
    :close-on-esc="false"
    preset="card"
    :title="t('pages.office.wizard.title')"
    style="width: 900px; max-width: calc(100vw - 32px); max-height: 99vh;"
    @update:show="(v) => !v && handleClose()"
  >
    <div class="wizard-container">
      <NSteps :current="currentStepIndex" :vertical="false" class="wizard-steps">
        <NStep :status="getStepStatus(1)" :title="t('pages.office.wizard.steps.scenario')" :description="t('pages.office.wizard.steps.scenarioDesc')">
          <template #icon><NIcon :component="CreateOutline" /></template>
        </NStep>
        <NStep :status="getStepStatus(2)" :title="t('pages.office.wizard.steps.agents')" :description="t('pages.office.wizard.steps.agentsDesc')">
          <template #icon><NIcon :component="PeopleOutline" /></template>
        </NStep>
        <NStep :status="getStepStatus(3)" :title="t('pages.office.wizard.steps.tasks')" :description="t('pages.office.wizard.steps.tasksDesc')">
          <template #icon><NIcon :component="ListOutline" /></template>
        </NStep>
        <NStep :status="getStepStatus(4)" :title="t('pages.office.wizard.steps.bindings')" :description="t('pages.office.wizard.steps.bindingsDesc')">
          <template #icon><NIcon :component="LinkOutline" /></template>
        </NStep>
        <NStep :status="getStepStatus(5)" :title="t('pages.office.wizard.steps.confirm')" :description="t('pages.office.wizard.steps.confirmDesc')">
          <template #icon><NIcon :component="CheckmarkCircleOutline" /></template>
        </NStep>
        <NStep :status="getStepStatus(6)" :title="t('pages.office.wizard.steps.execution')" :description="t('pages.office.wizard.steps.executionDesc')">
          <template #icon><NIcon :component="PlayOutline" /></template>
        </NStep>
      </NSteps>

      <NScrollbar class="wizard-content">
        <div v-if="wizardStep === 'scenario'" class="wizard-step-panel">
          <NInput
            v-model:value="scenarioName"
            :placeholder="t('pages.office.wizard.scenarioNamePlaceholder')"
            maxlength="100"
            style="margin-bottom: 12px;"
          >
            <template #prefix>
              <NText depth="3">{{ t('pages.office.wizard.scenarioName') }}:</NText>
            </template>
          </NInput>
          <NInput
            v-model:value="scenarioDescription"
            type="textarea"
            :placeholder="t('pages.office.wizard.scenarioDescriptionPlaceholder')"
            :autosize="{ minRows: 3, maxRows: 6 }"
            maxlength="500"
          />
          <NAlert type="info" :bordered="false" style="margin-top: 12px;">
            {{ t('pages.office.wizard.scenarioHint') }}
          </NAlert>
        </div>

        <div v-else-if="wizardStep === 'agents'" class="wizard-step-panel">
          <NRadioGroup v-model:value="agentSelectionMode" style="margin-bottom: 16px;">
            <NSpace>
              <NRadio value="existing">
                <NIcon :component="PeopleOutline" style="margin-right: 4px;" />
                {{ t('pages.office.wizard.selectExisting') }}
              </NRadio>
              <NRadio value="ai_create">
                <NIcon :component="SparklesOutline" style="margin-right: 4px;" />
                {{ t('pages.office.wizard.aiCreateAgents') }}
              </NRadio>
            </NSpace>
          </NRadioGroup>

          <div v-if="agentSelectionMode === 'existing'">
            <NText depth="3" style="display: block; margin-bottom: 12px;">
              {{ t('pages.office.wizard.selectAgentsHint') }}
            </NText>
            <NScrollbar v-if="availableAgents.length > 0" style="max-height: 280px; padding-right: 4px;">
              <div class="agent-selection-grid">
                <div
                  v-for="agent in availableAgents"
                  :key="agent.id"
                  class="agent-selection-card"
                  :class="{ 'is-selected': selectedAgents.includes(agent.id) }"
                  @click="() => {
                    const idx = selectedAgents.indexOf(agent.id)
                    if (idx >= 0) selectedAgents.splice(idx, 1)
                    else selectedAgents.push(agent.id)
                  }"
                >
                  <div class="agent-avatar">
                    <span v-if="agent.identity?.emoji" class="agent-emoji">{{ agent.identity.emoji }}</span>
                    <span v-else class="agent-initial">{{ (agent.name || agent.id).charAt(0).toUpperCase() }}</span>
                  </div>
                  <div class="agent-info">
                    <NText strong>{{ agent.name || agent.id }}</NText>
                    <NText depth="3" style="font-size: 12px;">{{ agent.id }}</NText>
                  </div>
                  <div v-if="selectedAgents.includes(agent.id)" class="agent-check">
                    <NIcon :component="CheckmarkCircleOutline" />
                  </div>
                </div>
              </div>
            </NScrollbar>
            <NEmpty v-else :description="t('pages.office.noAgents')" />
          </div>

          <div v-else class="ai-agent-creation">
            <NText depth="3" style="display: block; margin-bottom: 12px;">
              {{ t('pages.office.wizard.aiCreateHint') }}
            </NText>
            
            <div class="workspace-mode-section">
              <NText depth="3" style="font-size: 12px; display: block; margin-bottom: 8px;">
                {{ t('pages.office.wizard.workspaceMode') }}
              </NText>
              <NRadioGroup v-model:value="workspaceMode" style="margin-bottom: 12px;">
                <NSpace>
                  <NRadio value="independent">
                    <NTooltip>
                      <template #trigger>
                        <span>{{ t('pages.office.wizard.workspaceIndependent') }}</span>
                      </template>
                      {{ t('pages.office.wizard.workspaceIndependentHint') }}
                    </NTooltip>
                  </NRadio>
                  <NRadio value="shared">
                    <NTooltip>
                      <template #trigger>
                        <span>{{ t('pages.office.wizard.workspaceShared') }}</span>
                      </template>
                      {{ t('pages.office.wizard.workspaceSharedHint') }}
                    </NTooltip>
                  </NRadio>
                </NSpace>
              </NRadioGroup>
            </div>
            
            <div class="ai-prompt-input">
              <NInput
                v-model:value="aiAgentPrompt"
                type="textarea"
                :placeholder="t('pages.office.wizard.aiPromptPlaceholder')"
                :autosize="{ minRows: 2, maxRows: 4 }"
                :disabled="isGeneratingAgents"
              />
              <NButton
                type="primary"
                :loading="isGeneratingAgents"
                :disabled="!aiAgentPrompt.trim()"
                @click="handleGenerateAgents"
              >
                <template #icon><NIcon :component="SparklesOutline" /></template>
                {{ t('pages.office.wizard.generateAgents') }}
              </NButton>
            </div>

            <NAlert
              v-if="isGeneratingAgents"
              type="info"
              :bordered="false"
              style="margin-top: 12px;"
            >
              <template #icon>
                <NSpin size="small" />
              </template>
              {{ t('pages.office.wizard.generatingHint') }}
            </NAlert>

            <div v-if="aiGeneratedAgents.length > 0" class="generated-agents-list">
              <div class="generated-agents-header">
                <NText strong>{{ t('pages.office.wizard.generatedAgents') }} ({{ aiGeneratedAgents.length }})</NText>
                <NButton size="small" quaternary @click="handleAddCustomAgent">
                  <template #icon><NIcon :component="AddOutline" /></template>
                  {{ t('pages.office.wizard.addCustomAgent') }}
                </NButton>
              </div>
              <NScrollbar style="max-height: 280px; padding-right: 4px;">
                <div v-for="(agent, index) in aiGeneratedAgents" :key="agent.id" class="generated-agent-item" :class="{ 'is-team-leader': index === 0 }">
                  <div class="generated-agent-emoji">
                    <span>{{ agent.emoji || '👤' }}</span>
                  </div>
                  <div class="generated-agent-info">
                    <div style="display: flex; align-items: center; gap: 4px;">
                      <NInput
                        v-model:value="agent.name"
                        size="small"
                        style="width: 120px;"
                        :placeholder="t('pages.office.wizard.agentName')"
                      />
                      <NTag v-if="index === 0" type="warning" size="small">
                        {{ t('pages.office.wizard.teamLeader') }}
                      </NTag>
                    </div>
                    <NInput
                      v-model:value="agent.role"
                      size="small"
                      style="width: 100px;"
                      :placeholder="t('pages.office.wizard.agentRole')"
                    />
                    <NTooltip>
                      <template #trigger>
                        <NButton size="small" quaternary>
                          <template #icon><NIcon :component="ListOutline" /></template>
                        </NButton>
                      </template>
                      {{ t('pages.office.wizard.viewFiles') }}
                    </NTooltip>
                  </div>
                  <NButton v-if="index !== 0" size="small" quaternary type="error" @click="handleRemoveGeneratedAgent(index)">
                    <template #icon><NIcon :component="TrashOutline" /></template>
                  </NButton>
                </div>
              </NScrollbar>
            </div>
          </div>
        </div>

        <div v-else-if="wizardStep === 'tasks'" class="wizard-step-panel">
          <NText depth="3" style="display: block; margin-bottom: 12px;">
            {{ t('pages.office.wizard.addTasksHint') }}
          </NText>

          <div class="task-input-form">
            <NInput
              v-model:value="taskTitle"
              :placeholder="t('pages.office.wizard.taskTitlePlaceholder')"
              style="flex: 1;"
            />
            <NSelect
              v-model:value="taskPriority"
              :options="[
                { label: '低', value: 'low' },
                { label: '中', value: 'medium' },
                { label: '高', value: 'high' },
              ]"
              style="width: 80px;"
            />
            <NButton type="primary" @click="handleAddTask">
              {{ t('pages.office.wizard.addTask') }}
            </NButton>
          </div>

          <NInput
            v-model:value="taskDescription"
            type="textarea"
            :placeholder="t('pages.office.wizard.taskDescriptionPlaceholder')"
            :autosize="{ minRows: 2, maxRows: 4 }"
            style="margin-top: 8px;"
          />

          <div class="task-options">
            <NText depth="3" style="font-size: 12px;">{{ t('pages.office.wizard.taskModeLabel') }}:</NText>
            <NRadioGroup v-model:value="taskMode" size="small">
              <NRadio value="run">{{ t('pages.office.wizard.modeRun') }}</NRadio>
              <NRadio value="session">{{ t('pages.office.wizard.modeSession') }}</NRadio>
            </NRadioGroup>
          </div>

          <div class="task-options" style="margin-top: 8px;">
            <NText depth="3" style="font-size: 12px;">
              <span style="color: #d03050; margin-right: 2px;">*</span>{{ t('pages.office.wizard.assignAgents') }}:
            </NText>
            <NSelect
              v-model:value="taskAssignedAgents"
              multiple
              :options="agentOptions"
              :placeholder="t('pages.office.wizard.selectAgentsPlaceholder')"
              style="flex: 1; max-width: 400px;"
              size="small"
              :status="taskAssignedAgents.length === 0 ? 'warning' : undefined"
            />
            <NText v-if="taskAssignedAgents.length === 0" type="warning" style="font-size: 11px; margin-left: 4px;">
              ({{ t('common.required') }})
            </NText>
          </div>

          <div v-if="tasks.length > 0" class="task-list">
            <NCollapse>
              <NCollapseItem
                v-for="(task, index) in tasks"
                :key="task.id"
                :name="task.id"
              >
                <template #header>
                  <div class="task-item-header">
                    <NTag :type="task.priority === 'high' ? 'error' : task.priority === 'low' ? 'default' : 'info'" size="small">
                      {{ task.priority }}
                    </NTag>
                    <NText strong style="margin-left: 8px;">{{ task.title }}</NText>
                    <NTag v-if="task.mode === 'session'" type="warning" size="small" style="margin-left: 8px;">
                      {{ t('pages.office.wizard.modeSession') }}
                    </NTag>
                    <NButton size="tiny" text type="error" style="margin-left: auto;" @click.stop="handleRemoveTask(index)">
                      {{ t('common.delete') }}
                    </NButton>
                  </div>
                </template>
                <div class="task-item-content">
                  <NText v-if="task.description" depth="3" style="font-size: 12px; display: block; margin-bottom: 8px;">
                    {{ task.description }}
                  </NText>
                  <div class="task-agents-assign">
                    <NText depth="3" style="font-size: 12px; margin-right: 8px;">{{ t('pages.office.wizard.assignAgents') }}:</NText>
                    <div class="agent-chips">
                      <NTooltip
                        v-for="agentId in (agentSelectionMode === 'existing' ? selectedAgents : aiGeneratedAgents.map(a => a.id))"
                        :key="agentId"
                        placement="top"
                      >
                        <template #trigger>
                          <div
                            class="agent-chip"
                            :class="{ 'is-assigned': task.assignedAgents.includes(agentId) }"
                            @click="handleAssignAgent(index, agentId)"
                          >
                            <span>{{ getAgentEmoji(agentId) }}</span>
                          </div>
                        </template>
                        {{ getAgentDisplayName(agentId) }}
                      </NTooltip>
                    </div>
                  </div>
                </div>
              </NCollapseItem>
            </NCollapse>
          </div>
          <NEmpty v-else :description="t('pages.office.wizard.noTasks')" style="margin-top: 16px;" />
        </div>

        <div v-else-if="wizardStep === 'bindings'" class="wizard-step-panel">
          <NText depth="3" style="display: block; margin-bottom: 12px;">
            {{ t('pages.office.wizard.bindingsHint') }}
          </NText>

          <NButton size="small" @click="handleAddBinding" style="margin-bottom: 12px;">
            <template #icon><NIcon :component="AddOutline" /></template>
            {{ t('pages.office.wizard.addBinding') }}
          </NButton>

          <NScrollbar v-if="bindings.length > 0" style="max-height: 280px; padding-right: 4px;">
            <div class="bindings-list">
              <div v-for="(binding, index) in bindings" :key="index" class="binding-item">
                <div style="display: flex; align-items: center; gap: 6px; min-width: 140px;">
                  <span style="font-size: 18px;">{{ getAgentEmoji(binding.agentId) }}</span>
                  <NText style="font-size: 13px;">
                    {{ getAgentDisplayName(binding.agentId) }}
                  </NText>
                </div>
                <NSelect
                  v-model:value="binding.agentId"
                  :options="allAgentIds.map(id => ({ label: id, value: id }))"
                  style="width: 150px;"
                  :placeholder="t('pages.office.wizard.selectAgent')"
                />
                <NSelect
                  v-model:value="binding.channel"
                  :options="availableChannels"
                  style="width: 120px;"
                  :placeholder="t('pages.office.wizard.selectChannel')"
                />
                <NInput
                  v-model:value="binding.peerId"
                  :placeholder="t('pages.office.wizard.peerIdPlaceholder')"
                  style="flex: 1;"
                />
                <NSelect
                  v-model:value="binding.peerKind"
                  :options="[
                    { label: 'Group', value: 'group' },
                    { label: 'Direct', value: 'direct' },
                    { label: 'Channel', value: 'channel' },
                    { label: 'DM', value: 'dm' },
                    { label: 'ACP', value: 'acp' },
                  ]"
                  style="width: 100px;"
                />
                <NButton size="small" quaternary type="error" @click="handleRemoveBinding(index)">
                  <template #icon><NIcon :component="TrashOutline" /></template>
                </NButton>
              </div>
            </div>
          </NScrollbar>
          <NAlert v-else type="info" :bordered="false">
            {{ t('pages.office.wizard.noBindingsHint') }}
          </NAlert>
        </div>

        <WizardConfirmPanel
          v-else-if="wizardStep === 'confirm'"
          :scenario-name="scenarioName"
          :scenario-description="scenarioDescription"
          :agent-selection-mode="agentSelectionMode"
          :selected-agents="selectedAgents"
          :ai-generated-agent-ids="aiGeneratedAgents.map(a => a.id)"
          :get-agent-emoji="getAgentEmoji"
          :get-agent-display-name="getAgentDisplayName"
          :tasks="tasks"
          :bindings-count="bindings.length"
        />

        <WizardExecutionPanel
          v-else-if="wizardStep === 'execution'"
          :is-executing="isExecuting"
          :execution-tasks="executionTasks"
        />
      </NScrollbar>
    </div>

    <template #footer>
      <div class="wizard-footer">
        <NButton v-if="wizardStep !== 'scenario' && wizardStep !== 'execution'" @click="handleBack">
          <template #icon><NIcon :component="ArrowBackOutline" /></template>
          {{ t('pages.office.wizard.previous') }}
        </NButton>
        <div v-else></div>
        <NSpace>
          <NButton v-if="wizardStep !== 'execution'" @click="handleClose">{{ t('common.cancel') }}</NButton>
          <NButton
            v-if="wizardStep !== 'execution'"
            type="primary"
            :disabled="!canProceed"
            @click="handleNext"
          >
            <template #icon><NIcon :component="ArrowForwardOutline" /></template>
            {{ wizardStep === 'confirm' ? t('pages.office.wizard.confirmAndExecute') : t('pages.office.wizard.next') }}
          </NButton>
          <template v-else>
            <NButton 
              :type="isTaskExecutionComplete ? 'default' : 'primary'"
              :disabled="!isPreparationComplete || isExecuting || isTaskExecutionComplete"
              @click="handleExecuteAndClose"
            >
              <template #icon><NIcon :component="PlayOutline" /></template>
              {{ t('pages.office.wizard.executeTasksNow') }}
            </NButton>
            <NButton 
              :type="isTaskExecutionComplete ? 'primary' : 'default'"
              :disabled="!isPreparationComplete || isExecuting"
              @click="handleClose"
            >
              {{ t('pages.office.wizard.done') }}
            </NButton>
          </template>
        </NSpace>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.wizard-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.wizard-steps {
  padding: 0 16px;
}

.wizard-content {
  min-height: 280px;
  max-height: 390px;
}

.wizard-step-panel {
  padding: 16px 0;
}

.agent-selection-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
  padding-right: 12px;
}

.agent-selection-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 2px solid var(--border-color);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.agent-selection-card:hover {
  border-color: var(--primary-color);
  background: rgba(24, 160, 88, 0.05);
}

.agent-selection-card.is-selected {
  border-color: var(--primary-color);
  background: rgba(24, 160, 88, 0.1);
}

.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 600;
}

.agent-emoji {
  font-size: 20px;
}

.agent-initial {
  font-size: 16px;
}

.agent-info {
  flex: 1;
  min-width: 0;
}

.agent-info > * {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-check {
  position: absolute;
  top: 8px;
  right: 8px;
  color: var(--primary-color);
}

.ai-agent-creation {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.workspace-mode-section {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  border: 1px solid var(--border-color);
}

.ai-prompt-input {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.generated-agents-list {
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 12px;
}

.generated-agents-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
}

.generated-agent-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
}

.generated-agent-item.is-team-leader {
  background: linear-gradient(135deg, rgba(250, 173, 20, 0.1) 0%, rgba(250, 173, 20, 0.05) 100%);
  border: 1px solid rgba(250, 173, 20, 0.3);
}

.generated-agent-item:last-child {
  margin-bottom: 0;
}

.generated-agent-emoji {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.generated-agent-info {
  display: flex;
  gap: 8px;
  flex: 1;
}

.task-input-form {
  display: flex;
  gap: 8px;
}

.task-options {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 12px;
}

.task-list {
  margin-top: 16px;
}

.task-item-header {
  display: flex;
  align-items: center;
  width: 100%;
}

.task-item-content {
  padding: 8px 0;
}

.task-agents-assign {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.agent-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.agent-chip {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--bg-secondary);
  border: 2px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;
}

.agent-chip:hover {
  border-color: var(--primary-color);
}

.agent-chip.is-assigned {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: white;
}

.bindings-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.binding-item {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
}

.wizard-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  min-height: 54px;
}
</style>
