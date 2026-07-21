import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSkillStore } from '@/stores/skill'
import { useConfigStore } from '@/stores/config'
import type {
  AgentInstance,
  ConfiguredModelOption,
  Skill,
  SlashCommandPreset,
  SlashSuggestionItem,
  SubagentsSubcommand,
  SubagentsSubcommandPreset,
} from '@/api/types'

// ── 内部工具函数 ─────────────────────────────────────────────────────────────

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function splitModelRef(value: string): ConfiguredModelOption | null {
  const text = value.trim()
  const slashIndex = text.indexOf('/')
  if (slashIndex <= 0 || slashIndex >= text.length - 1) return null
  const providerId = text.slice(0, slashIndex).trim()
  const modelId = text.slice(slashIndex + 1).trim()
  if (!providerId || !modelId) return null
  return { modelRef: `${providerId}/${modelId}`, providerId, modelId }
}

function collectConfiguredModelRefs(input: unknown, refs: Set<string>) {
  if (!input) return

  if (typeof input === 'string') {
    const parsed = splitModelRef(input)
    if (parsed) refs.add(parsed.modelRef)
    return
  }

  if (Array.isArray(input)) {
    for (const item of input) {
      collectConfiguredModelRefs(item, refs)
    }
    return
  }

  const row = asRecord(input)
  if (!row) return

  for (const candidate of [row.id, row.model, row.ref, row.primary]) {
    if (typeof candidate === 'string') {
      const parsed = splitModelRef(candidate)
      if (parsed) refs.add(parsed.modelRef)
    }
  }

  for (const [key, value] of Object.entries(row)) {
    const keyParsed = splitModelRef(key)
    if (keyParsed) refs.add(keyParsed.modelRef)
    if (typeof value === 'string') {
      const valueParsed = splitModelRef(value)
      if (valueParsed) refs.add(valueParsed.modelRef)
    }
  }
}

function extractProviderModelIds(input: unknown): string[] {
  if (!input) return []

  if (Array.isArray(input)) {
    const ids: string[] = []
    for (const item of input) {
      if (typeof item === 'string' && item.trim()) {
        ids.push(item.trim())
        continue
      }
      const row = asRecord(item)
      if (!row) continue
      const id =
        (typeof row.id === 'string' && row.id.trim()) ||
        (typeof row.name === 'string' && row.name.trim()) ||
        ''
      if (id) ids.push(id)
    }
    return ids
  }

  const mapRow = asRecord(input)
  if (!mapRow) return []
  const ids: string[] = []
  for (const [key, item] of Object.entries(mapRow)) {
    const normalizedKey = key.trim()
    if (!normalizedKey) continue

    if (typeof item === 'string' && item.trim()) {
      ids.push(item.trim())
      continue
    }

    const row = asRecord(item)
    if (row) {
      const id =
        (typeof row.id === 'string' && row.id.trim()) ||
        (typeof row.name === 'string' && row.name.trim()) ||
        normalizedKey
      ids.push(id)
      continue
    }

    ids.push(normalizedKey)
  }
  return ids
}

function collectConfiguredModelRefsFromProviders(input: unknown, refs: Set<string>) {
  const providers = asRecord(input)
  if (!providers) return

  for (const [providerIdRaw, providerValue] of Object.entries(providers)) {
    const providerId = providerIdRaw.trim()
    if (!providerId) continue
    const provider = asRecord(providerValue)
    if (!provider) continue

    const candidates = [provider.models, provider.modelIds, provider.availableModels, provider.whitelist]
    for (const candidate of candidates) {
      const ids = extractProviderModelIds(candidate)
      for (const id of ids) {
        const parsed = splitModelRef(id)
        if (parsed) {
          refs.add(parsed.modelRef)
        } else if (id.trim()) {
          refs.add(`${providerId}/${id.trim()}`)
        }
      }
    }
  }
}

function filterConfiguredModels(query: string, list: ConfiguredModelOption[]): ConfiguredModelOption[] {
  if (!query) return list
  return list.filter((model) =>
    [model.modelRef, model.providerId, model.modelId].some((field) => field.toLowerCase().includes(query))
  )
}

function normalizeSlashArguments(line: string): string {
  const trimmed = line.trimStart()
  const matched = trimmed.match(/^\/[^\s:]+(?::|\s+)?(.*)$/)
  if (!matched) return ''
  return matched[1]?.trim() || ''
}

function splitFirstToken(value: string): { first: string; rest: string } {
  const text = value.trim()
  if (!text) return { first: '', rest: '' }
  const parts = text.split(/\s+/)
  const [first = '', ...rest] = parts
  return { first, rest: rest.join(' ') }
}

function normalizeSubagentsSubcommand(value: string): SubagentsSubcommand | '' {
  const lowered = value.trim().toLowerCase()
  if (lowered === 'list') return 'list'
  if (lowered === 'kill') return 'kill'
  if (lowered === 'log') return 'log'
  if (lowered === 'info') return 'info'
  if (lowered === 'send') return 'send'
  if (lowered === 'steer') return 'steer'
  if (lowered === 'spawn') return 'spawn'
  return ''
}

// ── Composable ────────────────────────────────────────────────────────────────

export interface UseSlashCommandsOptions {
  skillStore: ReturnType<typeof useSkillStore>
  configStore: ReturnType<typeof useConfigStore>
  /** ChatPage 专用：可用 agent 列表，用于 /subagents spawn 建议 */
  availableAgents?: ComputedRef<AgentInstance[]>
  /** ChatPage 专用：Enter 智能发送回调。未提供时 Enter 仅填充建议不发送 */
  onSend?: () => Promise<void>
}

export function useSlashCommands(draft: Ref<string>, options: UseSlashCommandsOptions) {
  const { skillStore, configStore, availableAgents, onSend } = options
  const { t } = useI18n()

  // ── 状态 ──────────────────────────────────────────────────────────────────

  const selectedSlashCommandIndex = ref(0)

  const slashFirstLine = computed(() => (draft.value.split('\n')[0] || '').trimStart())
  const slashMode = computed(() => slashFirstLine.value.startsWith('/'))
  const slashHasArgs = computed(() => {
    if (!slashMode.value) return false
    const content = slashFirstLine.value.slice(1)
    return /[\s:]/.test(content)
  })
  const slashCommandKeyword = computed(() => {
    if (!slashMode.value) return ''
    const content = slashFirstLine.value.slice(1)
    const token = content.split(/[\s:]/)[0] || ''
    return token.toLowerCase()
  })

  // ── 模式检测 ──────────────────────────────────────────────────────────────

  const slashNewMode = computed(() => slashMode.value && slashCommandKeyword.value === 'new')
  const slashSkillMode = computed(() => slashMode.value && slashCommandKeyword.value === 'skill')
  const slashModelMode = computed(() =>
    slashMode.value && (slashCommandKeyword.value === 'model' || slashCommandKeyword.value === 'models')
  )
  const slashSubagentsMode = computed(() => slashMode.value && slashCommandKeyword.value === 'subagents')

  // ── 预设 ──────────────────────────────────────────────────────────────────

  const slashCommandPresets = computed<SlashCommandPreset[]>(() => [
    {
      command: '/new',
      usage: '[model]',
      description: t('pages.chat.slash.commands.new.description'),
      category: t('pages.chat.slash.categories.session'),
      expectArgs: true,
    },
    {
      command: '/skill',
      usage: '<name> [input]',
      description: t('pages.chat.slash.commands.skill.description'),
      category: t('pages.chat.slash.categories.modelAndContext'),
      expectArgs: true,
    },
    {
      command: '/model',
      usage: '<name|list|status>',
      aliases: ['/models'],
      description: t('pages.chat.slash.commands.model.description'),
      category: t('pages.chat.slash.categories.modelAndContext'),
      expectArgs: true,
    },
    {
      command: '/status',
      description: t('pages.chat.slash.commands.status.description'),
      category: t('pages.chat.slash.categories.common'),
    },
    {
      command: '/subagents',
      usage: 'list|kill|log|info|send|steer|spawn',
      description: t('pages.chat.slash.commands.subagents.description'),
      category: t('pages.chat.slash.categories.session'),
      expectArgs: true,
    },
  ])

  const subagentsSubcommandPresets = computed<SubagentsSubcommandPreset[]>(() => [
    { subcommand: 'list', description: t('pages.chat.slash.commands.subagents.subcommands.list') },
    { subcommand: 'kill', usage: '<runId>', description: t('pages.chat.slash.commands.subagents.subcommands.kill') },
    { subcommand: 'log', usage: '<runId>', description: t('pages.chat.slash.commands.subagents.subcommands.log') },
    { subcommand: 'info', usage: '<runId>', description: t('pages.chat.slash.commands.subagents.subcommands.info') },
    { subcommand: 'send', usage: '<runId> <message>', description: t('pages.chat.slash.commands.subagents.subcommands.send') },
    { subcommand: 'steer', usage: '<runId> <message>', description: t('pages.chat.slash.commands.subagents.subcommands.steer') },
    { subcommand: 'spawn', usage: '<agentId> <task> [--model <model>] [--thinking <level>]', description: t('pages.chat.slash.commands.subagents.subcommands.spawn') },
  ])

  // ── 技能过滤 ──────────────────────────────────────────────────────────────

  const availableSkills = computed(() =>
    skillStore.skills
      .filter((skill) => {
        if (skill.disabled) return false
        if (skill.eligible === false) return false
        if (!skillStore.isSkillVisibleInChat(skill.name)) return false
        return true
      })
      .sort((a, b) => a.name.localeCompare(b.name))
  )

  // ── 命令建议 ──────────────────────────────────────────────────────────────

  const slashCommandOptions = computed<SlashCommandPreset[]>(() => {
    if (!slashMode.value) return []
    const query = slashCommandKeyword.value
    const presets = slashCommandPresets.value
    if (!query) return presets
    return presets.filter((item) => {
      const primary = item.command.slice(1).toLowerCase()
      if (primary.includes(query)) return true
      return (item.aliases || []).some((alias) => alias.slice(1).toLowerCase().includes(query))
    })
  })

  // ── 技能建议 ──────────────────────────────────────────────────────────────

  const slashSkillNameQuery = computed(() => {
    if (!slashSkillMode.value) return ''
    const args = normalizeSlashArguments(slashFirstLine.value)
    const firstToken = args.split(/\s+/)[0] || ''
    return firstToken.toLowerCase()
  })

  const slashSkillOptions = computed<Skill[]>(() => {
    if (!slashSkillMode.value) return []
    const query = slashSkillNameQuery.value
    if (!query) return availableSkills.value
    return availableSkills.value.filter((skill) =>
      [skill.name, skill.description || ''].some((field) => field.toLowerCase().includes(query))
    )
  })

  // ── Model 收集与建议 ──────────────────────────────────────────────────────

  const configuredModelOptions = computed<ConfiguredModelOption[]>(() => {
    const refs = new Set<string>()
    const defaultsRaw = asRecord(configStore.config?.agents?.defaults)
    const defaultsModelRaw = asRecord(defaultsRaw?.model)
    const allowlistedRefs = new Set<string>()

    collectConfiguredModelRefs(configStore.config?.models?.primary, refs)
    collectConfiguredModelRefs(configStore.config?.models?.fallback, refs)
    collectConfiguredModelRefs(defaultsRaw?.models, refs)
    collectConfiguredModelRefs(defaultsRaw?.models, allowlistedRefs)
    collectConfiguredModelRefs(defaultsModelRaw?.primary, refs)
    collectConfiguredModelRefs(defaultsModelRaw?.fallback, refs)
    collectConfiguredModelRefs(defaultsModelRaw?.fallbacks, refs)
    collectConfiguredModelRefsFromProviders(configStore.config?.models?.providers, refs)

    const finalRefs = new Set<string>()
    if (allowlistedRefs.size > 0) {
      for (const ref of refs) {
        if (allowlistedRefs.has(ref)) {
          finalRefs.add(ref)
        }
      }
      for (const ref of allowlistedRefs) {
        finalRefs.add(ref)
      }
    } else {
      for (const ref of refs) {
        finalRefs.add(ref)
      }
    }

    return Array.from(finalRefs)
      .sort((a, b) => a.localeCompare(b))
      .map((ref) => splitModelRef(ref))
      .filter((item): item is ConfiguredModelOption => !!item)
  })

  const slashModelQuery = computed(() => {
    if (!slashModelMode.value) return ''
    const args = normalizeSlashArguments(slashFirstLine.value)
    const firstToken = args.split(/\s+/)[0] || ''
    return firstToken.toLowerCase()
  })

  const slashModelOptions = computed<ConfiguredModelOption[]>(() => {
    if (!slashModelMode.value) return []
    return filterConfiguredModels(slashModelQuery.value, configuredModelOptions.value)
  })

  const slashNewModelQuery = computed(() => {
    if (!slashNewMode.value) return ''
    const args = normalizeSlashArguments(slashFirstLine.value)
    const firstToken = args.split(/\s+/)[0] || ''
    return firstToken.toLowerCase()
  })

  const slashNewModelOptions = computed<ConfiguredModelOption[]>(() => {
    if (!slashNewMode.value) return []
    return filterConfiguredModels(slashNewModelQuery.value, configuredModelOptions.value)
  })

  // ── Subagents 建议 ────────────────────────────────────────────────────────

  const slashSubagentsArgs = computed(() => {
    if (!slashSubagentsMode.value) return ''
    return normalizeSlashArguments(slashFirstLine.value)
  })

  const slashSubagentsSubcommandQuery = computed(() => {
    const { first } = splitFirstToken(slashSubagentsArgs.value)
    return first.toLowerCase()
  })

  const slashSubagentsSubcommandOptions = computed<SubagentsSubcommandPreset[]>(() => {
    if (!slashSubagentsMode.value) return []
    const query = slashSubagentsSubcommandQuery.value
    const presets = subagentsSubcommandPresets.value
    if (!query) return presets
    return presets.filter((preset) => preset.subcommand.includes(query))
  })

  const slashSubagentsSpawnAgentQuery = computed(() => {
    if (!slashSubagentsMode.value) return ''
    if (normalizeSubagentsSubcommand(slashSubagentsSubcommandQuery.value) !== 'spawn') return ''
    const { rest } = splitFirstToken(slashSubagentsArgs.value)
    const { first } = splitFirstToken(rest)
    return first.toLowerCase()
  })

  const slashSubagentsSpawnAgentOptions = computed<AgentInstance[]>(() => {
    if (!slashSubagentsMode.value) return []
    if (normalizeSubagentsSubcommand(slashSubagentsSubcommandQuery.value) !== 'spawn') return []
    const agents = availableAgents?.value ?? []
    const query = slashSubagentsSpawnAgentQuery.value
    if (!query) return agents
    return agents.filter((agent) => agent.id.toLowerCase().includes(query))
  })

  // ── 汇总建议 ──────────────────────────────────────────────────────────────

  const slashSuggestions = computed<SlashSuggestionItem[]>(() => {
    if (!slashMode.value) return []
    if (slashSubagentsMode.value) {
      if (normalizeSubagentsSubcommand(slashSubagentsSubcommandQuery.value) === 'spawn') {
        return slashSubagentsSpawnAgentOptions.value.map((agent) => ({
          kind: 'subagents-agent',
          key: `subagents-spawn-agent-${agent.id}`,
          agent,
        }))
      }
      return slashSubagentsSubcommandOptions.value.map((preset) => ({
        kind: 'subagents-subcommand',
        key: `subagents-subcommand-${preset.subcommand}`,
        subagentsSubcommand: preset,
      }))
    }
    if (slashNewMode.value) {
      const defaults: SlashSuggestionItem[] = [{ kind: 'new-default', key: 'new-default' }]
      const models: SlashSuggestionItem[] = slashNewModelOptions.value.map(
        (model): SlashSuggestionItem => ({
          kind: 'new-model',
          key: `new-model-${model.modelRef}`,
          model,
        })
      )
      return [...defaults, ...models]
    }
    if (slashSkillMode.value) {
      return slashSkillOptions.value.map((skill) => ({
        kind: 'skill',
        key: `skill-${skill.name}`,
        skill,
      }))
    }
    if (slashModelMode.value) {
      return slashModelOptions.value.map((model) => ({
        kind: 'model',
        key: `model-${model.modelRef}`,
        model,
      }))
    }
    return slashCommandOptions.value.map((preset) => ({
      kind: 'command',
      key: `cmd-${preset.command}`,
      preset,
    }))
  })

  const activeSlashSuggestion = computed(() => {
    if (slashSuggestions.value.length === 0) return null
    const safeIndex = Math.min(
      Math.max(selectedSlashCommandIndex.value, 0),
      slashSuggestions.value.length - 1
    )
    return slashSuggestions.value[safeIndex]
  })

  // ── Apply 函数（ChatPage 风格：split-join 保留多行） ─────────────────────

  function buildSlashCommandLine(command: SlashCommandPreset): string {
    const args = normalizeSlashArguments(slashFirstLine.value)
    if (args) return `${command.command} ${args}`
    if (command.expectArgs) return `${command.command} `
    return command.command
  }

  function applySlashCommand(command: SlashCommandPreset) {
    const lines = draft.value.split('\n')
    lines[0] = buildSlashCommandLine(command)
    draft.value = lines.join('\n')
  }

  function applySlashSkill(skill: Skill) {
    const lines = draft.value.split('\n')
    const args = normalizeSlashArguments(slashFirstLine.value)
    const { rest } = splitFirstToken(args)
    lines[0] = rest ? `/skill ${skill.name} ${rest}` : `/skill ${skill.name} `
    draft.value = lines.join('\n')
  }

  function applySlashModel(model: ConfiguredModelOption) {
    const lines = draft.value.split('\n')
    const args = normalizeSlashArguments(slashFirstLine.value)
    const { rest } = splitFirstToken(args)
    const modelRef = model.modelRef
    lines[0] = rest ? `/model ${modelRef} ${rest}` : `/model ${modelRef}`
    draft.value = lines.join('\n')
  }

  function applySlashNewModel(model: ConfiguredModelOption) {
    const lines = draft.value.split('\n')
    const args = normalizeSlashArguments(slashFirstLine.value)
    const { rest } = splitFirstToken(args)
    const modelRef = model.modelRef
    lines[0] = rest ? `/new ${modelRef} ${rest}` : `/new ${modelRef}`
    draft.value = lines.join('\n')
  }

  function applySlashNewDefault() {
    const lines = draft.value.split('\n')
    lines[0] = '/new'
    draft.value = lines.join('\n')
  }

  function applySlashSubagentsSubcommand(preset: SubagentsSubcommandPreset) {
    const lines = draft.value.split('\n')
    const args = slashSubagentsArgs.value
    const { rest } = splitFirstToken(args)

    const base = `/subagents ${preset.subcommand}`
    if (rest) {
      lines[0] = `${base} ${rest}`
      draft.value = lines.join('\n')
      return
    }

    if (preset.subcommand === 'list') {
      lines[0] = base
    } else {
      lines[0] = `${base} `
    }
    draft.value = lines.join('\n')
  }

  function applySlashSubagentsSpawnAgent(agentId: string) {
    const id = agentId.trim()
    if (!id) return

    const lines = draft.value.split('\n')
    const args = slashSubagentsArgs.value
    const { first: subcommand, rest } = splitFirstToken(args)
    const normalized = normalizeSubagentsSubcommand(subcommand)
    if (normalized !== 'spawn') return

    const { rest: restAfterAgent } = splitFirstToken(rest)
    lines[0] = restAfterAgent
      ? `/subagents spawn ${id} ${restAfterAgent}`
      : `/subagents spawn ${id} `
    draft.value = lines.join('\n')
  }

  function applySlashSuggestion(item: SlashSuggestionItem) {
    if (item.kind === 'subagents-subcommand' && item.subagentsSubcommand) {
      applySlashSubagentsSubcommand(item.subagentsSubcommand)
      return
    }
    if (item.kind === 'subagents-agent' && item.agent) {
      applySlashSubagentsSpawnAgent(item.agent.id)
      return
    }
    if (item.kind === 'skill' && item.skill) {
      applySlashSkill(item.skill)
      return
    }
    if (item.kind === 'model' && item.model) {
      applySlashModel(item.model)
      return
    }
    if (item.kind === 'new-model' && item.model) {
      applySlashNewModel(item.model)
      return
    }
    if (item.kind === 'new-default') {
      applySlashNewDefault()
      return
    }
    if (item.kind === 'command' && item.preset) {
      applySlashCommand(item.preset)
    }
  }

  function moveSlashSuggestionSelection(step: number) {
    const size = slashSuggestions.value.length
    if (!size) return
    selectedSlashCommandIndex.value = (selectedSlashCommandIndex.value + step + size) % size
  }

  function resetSlashIndex() {
    selectedSlashCommandIndex.value = 0
  }

  // ── 键盘处理 ──────────────────────────────────────────────────────────────

  /**
   * 处理 slash 模式的键盘事件。
   * @returns true 表示事件已被处理，调用方应 return；false 表示未处理，继续正常发送逻辑
   */
  async function handleSlashKeydown(e: KeyboardEvent): Promise<boolean> {
    if (!slashMode.value || slashSuggestions.value.length === 0) return false

    const isEnter = e.key === 'Enter'
    const canSend = !e.shiftKey && !e.isComposing

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveSlashSuggestionSelection(1)
      return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveSlashSuggestionSelection(-1)
      return true
    }
    if (e.key === 'Tab') {
      e.preventDefault()
      const item = activeSlashSuggestion.value
      if (item) applySlashSuggestion(item)
      return true
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      draft.value = draft.value.replace(/^\s*\/+/, '')
      return true
    }
    if (isEnter && canSend) {
      e.preventDefault()
      const item = activeSlashSuggestion.value
      if (!item) return true

      // 有 onSend 回调 → 智能发送（ChatPage 风格）
      if (onSend) {
        if (item.kind === 'skill' && item.skill) {
          const args = normalizeSlashArguments(slashFirstLine.value)
          const { first } = splitFirstToken(args)
          if (first && first.toLowerCase() === item.skill.name.toLowerCase()) {
            await onSend()
            return true
          }
          applySlashSkill(item.skill)
          return true
        }
        if (item.kind === 'model' && item.model) {
          const args = normalizeSlashArguments(slashFirstLine.value)
          const { first } = splitFirstToken(args)
          const modelRef = item.model.modelRef.toLowerCase()
          if (first && first.toLowerCase() === modelRef) {
            await onSend()
            return true
          }
          applySlashModel(item.model)
          return true
        }
        if (item.kind === 'new-model' && item.model) {
          const args = normalizeSlashArguments(slashFirstLine.value)
          const { first } = splitFirstToken(args)
          const modelRef = item.model.modelRef.toLowerCase()
          if (first && first.toLowerCase() === modelRef) {
            await onSend()
            return true
          }
          applySlashNewModel(item.model)
          return true
        }
        if (item.kind === 'new-default') {
          const args = normalizeSlashArguments(slashFirstLine.value)
          if (!args) {
            await onSend()
            return true
          }
          applySlashNewDefault()
          return true
        }
        if (item.kind === 'subagents-subcommand' && item.subagentsSubcommand) {
          const args = normalizeSlashArguments(slashFirstLine.value)
          const { first } = splitFirstToken(args)
          if (first && first.toLowerCase() === item.subagentsSubcommand.subcommand) {
            await onSend()
            return true
          }
          applySlashSubagentsSubcommand(item.subagentsSubcommand)
          return true
        }
        if (item.kind === 'subagents-agent' && item.agent) {
          const args = normalizeSlashArguments(slashFirstLine.value)
          const { first: sub, rest } = splitFirstToken(args)
          if (normalizeSubagentsSubcommand(sub) !== 'spawn') {
            applySlashSubagentsSpawnAgent(item.agent.id)
            return true
          }
          const { first: agentId } = splitFirstToken(rest)
          if (agentId && agentId.toLowerCase() === item.agent.id.toLowerCase()) {
            await onSend()
            return true
          }
          applySlashSubagentsSpawnAgent(item.agent.id)
          return true
        }
        if (item.kind === 'command' && item.preset) {
          if (!slashHasArgs.value) {
            const exact = slashFirstLine.value.trim() === item.preset.command
            if (exact) {
              await onSend()
              return true
            }
            applySlashCommand(item.preset)
            return true
          }
          await onSend()
          return true
        }
        return true
      }

      // 无 onSend 回调 → 仅填充建议（AgentChatPanel 风格）
      if (item.kind === 'command' && item.preset) {
        applySlashCommand(item.preset)
      } else {
        applySlashSuggestion(item)
      }
      return true
    }

    return false
  }

  // ── Watch ─────────────────────────────────────────────────────────────────

  watch(
    slashSuggestions,
    (list) => {
      if (!list.length) {
        selectedSlashCommandIndex.value = 0
        return
      }
      if (selectedSlashCommandIndex.value >= list.length) {
        selectedSlashCommandIndex.value = 0
      }
    },
    { immediate: true }
  )

  watch(slashMode, (value) => {
    if (value) {
      selectedSlashCommandIndex.value = 0
    }
  })

  watch(slashCommandKeyword, () => {
    selectedSlashCommandIndex.value = 0
  })

  return {
    // 状态
    selectedSlashCommandIndex,

    // 基础解析
    slashFirstLine,
    slashMode,
    slashCommandKeyword,
    slashHasArgs,

    // 模式检测
    slashNewMode,
    slashSkillMode,
    slashModelMode,
    slashSubagentsMode,

    // 建议列表
    slashCommandOptions,
    slashSkillOptions,
    slashModelOptions,
    slashNewModelOptions,
    slashSubagentsSubcommandOptions,
    slashSuggestions,
    activeSlashSuggestion,

    // 动作
    applySlashSuggestion,
    handleSlashKeydown,
    resetSlashIndex,

    // ChatPage 专用
    slashSubagentsArgs,
    slashSubagentsSpawnAgentOptions,
    normalizeSubagentsSubcommand,
  }
}
