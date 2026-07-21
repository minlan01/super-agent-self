/**
 * Wizard Execution — 场景向导的执行逻辑模块
 * 提取自 ScenarioWizard.vue，包含准备任务构建、Agent创建、配置更新、任务发送等
 */
import type { GeneratedAgent, AgentBinding } from '@/stores/wizard'
import type { Ref } from 'vue'

// ─── 类型定义 ───────────────────────────────────────────────

export interface WizardTaskItem {
  id: string
  title: string
  description: string
  priority: 'low' | 'medium' | 'high'
  assignedAgents: string[]
  mode: 'run' | 'session'
}

export interface ExecutionTask {
  id: string
  type: 'create_agent' | 'config_update' | 'task_send' | 'skip_agent' | 'set_identity'
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  label: string
  detail?: string
  agentId?: string
}

export interface ExecutionDeps {
  agentSelectionMode: Ref<'existing' | 'ai_create'>
  workspaceMode: Ref<'independent' | 'shared'>
  aiGeneratedAgents: Ref<GeneratedAgent[]>
  bindings: Ref<AgentBinding[]>
  tasks: Ref<WizardTaskItem[]>
  allAgentIds: Ref<string[]>
  isExecuting: Ref<boolean>
  isPreparationComplete: Ref<boolean>
  isTaskExecutionComplete: Ref<boolean>
  executionTasks: Ref<ExecutionTask[]>
  // Store 方法
  agentStore: {
    agents: Array<{ id: string; name: string }>
    addAgent: (params: { id: string; name: string; workspace: string }) => Promise<void>
    fetchAgents: () => Promise<void>
    setAgentsIdentityBatch: (params: Array<{ agentId: string; name: string; emoji?: string }>) => Promise<void>
  }
  wsStore: {
    rpc: {
      setAgentFile: (agentId: string, filename: string, content: string) => Promise<void>
      callAgent: (params: { sessionKey: string; message: string; idempotencyKey: string }) => Promise<void>
    }
  }
  configStore: {
    fetchConfig: () => Promise<void>
    config: Record<string, unknown> | null
    setConfig: (config: Record<string, unknown>) => Promise<void>
  }
}

// ─── 准备任务构建 ───────────────────────────────────────────

export function buildPreparationTasks(deps: ExecutionDeps): void {
  const { agentSelectionMode, aiGeneratedAgents, agentStore, tasks, executionTasks, bindings } = deps
  executionTasks.value = []

  if (agentSelectionMode.value === 'ai_create') {
    aiGeneratedAgents.value.forEach((agent) => {
      const existingAgent = agentStore.agents.find(
        (a) => a.id === agent.id || a.name === agent.name
      )

      if (existingAgent) {
        executionTasks.value.push({
          id: `skip-${agent.id}`,
          type: 'skip_agent',
          status: 'completed',
          label: `跳过创建智能体: ${agent.name}`,
          detail: `智能体已存在 (ID: ${existingAgent.id})`,
          agentId: agent.id,
        })
        agent.created = true
      } else if (!agent.created) {
        executionTasks.value.push({
          id: `create-${agent.id}`,
          type: 'create_agent',
          status: 'pending',
          label: `创建智能体: ${agent.name}`,
          detail: `角色: ${agent.role}`,
          agentId: agent.id,
        })
      }
    })

    const agentsNeedIdentity = aiGeneratedAgents.value.filter(
      (agent) => agent.emoji || agent.name
    )
    if (agentsNeedIdentity.length > 0) {
      executionTasks.value.push({
        id: 'set-identity-batch',
        type: 'set_identity',
        status: 'pending',
        label: '批量设置智能体身份',
        detail: `设置 ${agentsNeedIdentity.length} 个智能体的名称和头像`,
      })
    }
  }

  executionTasks.value.push({
    id: 'config-update',
    type: 'config_update',
    status: 'pending',
    label: '更新配置文件',
    detail: '配置 sessions、agentToAgent 和 bindings',
  })

  tasks.value.forEach((task) => {
    task.assignedAgents.forEach((agentId) => {
      executionTasks.value.push({
        id: `send-${task.id}-${agentId}`,
        type: 'task_send',
        status: 'pending',
        label: `发送任务: ${task.title}`,
        detail: `目标: ${agentId}`,
        agentId,
      })
    })
  })
}

// ─── 执行单个 Agent 创建 ─────────────────────────────────────

export async function executeCreateAgent(agentId: string, deps: ExecutionDeps): Promise<void> {
  const { aiGeneratedAgents, workspaceMode, agentStore, wsStore } = deps
  const agent = aiGeneratedAgents.value.find((a) => a.id === agentId)
  if (!agent) throw new Error(`Agent ${agentId} not found`)

  const existingAgent = agentStore.agents.find(
    (a) => a.id === agentId || a.name === agent.name
  )

  if (existingAgent) {
    agent.created = true
    return
  }

  let workspace: string
  if (workspaceMode.value === 'shared' && aiGeneratedAgents.value.length > 0 && aiGeneratedAgents.value[0]) {
    const teamLeader = aiGeneratedAgents.value[0]
    workspace = `~/.openclaw/workspace-${teamLeader.id}`
  } else {
    workspace = `~/.openclaw/workspace-${agent.id}`
  }

  await agentStore.addAgent({
    id: agent.id,
    name: agent.name,
    workspace,
  })

  if (agent.agentsMd) {
    await wsStore.rpc.setAgentFile(agent.id, 'AGENTS.md', agent.agentsMd)
  }
  if (agent.soulMd) {
    await wsStore.rpc.setAgentFile(agent.id, 'SOUL.md', agent.soulMd)
  }
  if (agent.userMd) {
    await wsStore.rpc.setAgentFile(agent.id, 'USER.md', agent.userMd)
  }
  if (agent.identityMd) {
    await wsStore.rpc.setAgentFile(agent.id, 'IDENTITY.md', agent.identityMd)
  }

  agent.created = true
  await agentStore.fetchAgents()
}

// ─── 批量设置身份 ──────────────────────────────────────────

export async function executeSetIdentityBatch(deps: ExecutionDeps): Promise<void> {
  const { aiGeneratedAgents, agentStore } = deps
  const agentsNeedIdentity = aiGeneratedAgents.value.filter(
    (agent) => agent.emoji || agent.name
  )

  if (agentsNeedIdentity.length === 0) return

  const identityParams = agentsNeedIdentity.map((agent) => ({
    agentId: agent.id,
    name: agent.name,
    emoji: agent.emoji,
  }))

  await agentStore.setAgentsIdentityBatch(identityParams)
}

// ─── 更新配置文件 ──────────────────────────────────────────

export async function executeConfigUpdate(deps: ExecutionDeps): Promise<void> {
  const { configStore, allAgentIds, bindings, aiGeneratedAgents } = deps
  await configStore.fetchConfig()
  const currentConfig = configStore.config || {} as Record<string, unknown>

  const agentIds = allAgentIds.value

  const existingBindings = (currentConfig as Record<string, unknown>).bindings as Array<Record<string, unknown>> || []
  const updatedBindings = [...existingBindings]

  for (const binding of bindings.value) {
    const existingIndex = updatedBindings.findIndex(
      (b) => (b as Record<string, unknown>).agentId === binding.agentId
    )

    const newBinding = {
      match: {
        channel: binding.channel,
        accountId: binding.accountId || binding.agentId,
        peer: binding.peerId ? {
          kind: binding.peerKind || 'group',
          id: binding.peerId,
        } : undefined,
      },
      agentId: binding.agentId,
    }

    if (existingIndex >= 0) {
      updatedBindings[existingIndex] = newBinding
    } else {
      updatedBindings.push(newBinding)
    }
  }

  const existingAgentsList = ((currentConfig as Record<string, unknown>).agents as Record<string, unknown>)?.list as Array<Record<string, unknown>> || []
  const updatedAgentsList = [...existingAgentsList]

  if (aiGeneratedAgents.value.length > 0 && aiGeneratedAgents.value[0]) {
    const teamLeader = aiGeneratedAgents.value[0]
    const allAgentIdsList = aiGeneratedAgents.value.map(a => a.id)

    const existingLeaderIndex = updatedAgentsList.findIndex(a => a.id === teamLeader.id)
    const leaderConfig = {
      id: teamLeader.id,
      name: teamLeader.name,
      subagents: {
        allowAgents: allAgentIdsList,
      },
      tools: {
        deny: ['subagents', 'session_status'],
      },
      identity: {
        name: teamLeader.name,
        emoji: teamLeader.emoji || '👨‍💼',
      },
    }

    if (existingLeaderIndex >= 0) {
      updatedAgentsList[existingLeaderIndex] = {
        ...updatedAgentsList[existingLeaderIndex],
        ...leaderConfig,
      }
    } else {
      updatedAgentsList.push(leaderConfig)
    }
  }

  const updatedConfig = {
    ...currentConfig,
    tools: {
      ...((currentConfig as Record<string, unknown>).tools as Record<string, unknown>),
      sessions: {
        visibility: 'all',
      },
      agentToAgent: {
        enabled: true,
        allow: [
          'main',
          ...agentIds.filter((id) => id !== 'main'),
        ],
      },
    },
    bindings: updatedBindings,
    agents: {
      ...((currentConfig as Record<string, unknown>).agents as Record<string, unknown>),
      list: updatedAgentsList,
    },
  }

  await configStore.setConfig(updatedConfig)
}

// ─── 发送任务 ──────────────────────────────────────────────

export async function executeTaskSend(
  taskSendId: string,
  deps: ExecutionDeps
): Promise<void> {
  const match = taskSendId.match(/^send-(task-\d+)-(.+)$/)
  if (!match) throw new Error('Invalid task send ID')

  const [, taskId, agentId] = match
  const task = deps.tasks.value.find((t) => t.id === taskId)
  if (!task) throw new Error(`Task ${taskId} not found`)

  const sessionKey = `agent:${agentId}:main:dm:task-${Date.now()}`
  const taskMessage = `任务: ${task.title}\n\n描述: ${task.description}\n\n请开始执行此任务。`

  await deps.wsStore.rpc.callAgent({
    sessionKey,
    message: taskMessage,
    idempotencyKey: `task-${taskId}-${Date.now()}`,
  })
}

// ─── 串行执行下一个非 task_send 任务 ─────────────────────────

export async function executeNextTask(deps: ExecutionDeps): Promise<void> {
  const { executionTasks, isExecuting, isPreparationComplete, agentStore } = deps
  const pendingTask = executionTasks.value.find((t) => t.status === 'pending' && t.type !== 'task_send')
  if (!pendingTask) {
    isExecuting.value = false
    isPreparationComplete.value = true

    await agentStore.fetchAgents()
    return
  }

  isExecuting.value = true
  pendingTask.status = 'in_progress'

  try {
    switch (pendingTask.type) {
      case 'create_agent':
        await executeCreateAgent(pendingTask.agentId!, deps)
        break
      case 'skip_agent':
        break
      case 'set_identity':
        await executeSetIdentityBatch(deps)
        break
      case 'config_update':
        await executeConfigUpdate(deps)
        break
      case 'task_send':
        await executeTaskSend(pendingTask.id, deps)
        break
    }
    pendingTask.status = 'completed'
  } catch (error) {
    console.error('Task execution failed:', error)
    pendingTask.status = 'failed'
    pendingTask.detail = error instanceof Error ? error.message : String(error)
  }

  await new Promise((resolve) => setTimeout(resolve, 300))
  await executeNextTask(deps)
}

// ─── 执行所有 task_send 任务 ─────────────────────────────────

export async function executeTaskSendTasks(deps: ExecutionDeps): Promise<void> {
  const { executionTasks, isExecuting, isTaskExecutionComplete, agentStore } = deps
  const pendingTaskSend = executionTasks.value.find((t) => t.status === 'pending' && t.type === 'task_send')
  if (!pendingTaskSend) {
    return
  }

  isExecuting.value = true

  for (const task of executionTasks.value.filter(t => t.type === 'task_send' && t.status === 'pending')) {
    task.status = 'in_progress'

    try {
      await executeTaskSend(task.id, deps)
      task.status = 'completed'
    } catch (e: unknown) {
      task.status = 'failed'
      console.error('[Wizard] Task send failed:', task.id, e)
    }
  }

  isExecuting.value = false
  isTaskExecutionComplete.value = true

  await agentStore.fetchAgents()
}
