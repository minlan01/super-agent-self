import { computed, ref, nextTick } from 'vue'
import type { MessageApi } from 'naive-ui'
import type { ComposerTranslation } from 'vue-i18n'
import type { ModelSelection } from '@/api/hermes/types'
import type { CommandItem } from '@/api/hermes/chat-types'
import type { Ref, ComputedRef } from 'vue'

export interface HermesCommandsContext {
  t: ComposerTranslation
  message: MessageApi
  inputText: Ref<string>
  // Stores
  chatStore: {
    messages: { role: string; content: string; id?: string }[]
    sendMessage: (content: string, opts?: { modelSelection?: ModelSelection }) => Promise<void>
    stopGeneration: () => void
    clearMessages: () => void
    currentSessionId: string | null
  }
  modelStore: {
    allSelectableModels: Array<{ modelId: string; label?: string; providerName: string; baseUrl?: string; type: string }>
    models: Array<{ provider?: string }>
  }
  skillStore: {
    fetchSkills: () => Promise<void>
    skills: Array<{ name: string; description?: string; version?: string; enabled: boolean; category?: string }>
  }
  connStore: {
    connect: () => Promise<void>
  }
  // Refs
  selectedModelSelection: Ref<ModelSelection | null>
  selectedSession: ComputedRef<{ id: string; title?: string; model?: string } | null>
  lastTokenUsage: Ref<{ input: number; output: number; total: number } | null>
  // Action callbacks
  handleNewSession: () => void
}

export function useHermesCommands(ctx: HermesCommandsContext) {
  const { t, message, inputText, chatStore, modelStore, skillStore, connStore } = ctx

  const commands = computed<CommandItem[]>(() => {
    const list: CommandItem[] = [
      // Session
      {
        key: '/new', label: '/new', category: 'Session',
        description: t('pages.hermesChat.cmdNew'), argsHint: '', hasArgs: false,
        action: ctx.handleNewSession,
      },
      {
        key: '/retry', label: '/retry', category: 'Session',
        description: t('pages.hermesChat.cmdRetry'), argsHint: '', hasArgs: false,
        action: () => {
          const lastUserMsg = [...chatStore.messages].reverse().find(m => m.role === 'user')
          if (lastUserMsg) {
            chatStore.sendMessage(lastUserMsg.content, {
              modelSelection: ctx.selectedModelSelection.value || undefined
            }).catch(() => {})
          }
        },
      },
      {
        key: '/undo', label: '/undo', category: 'Session',
        description: t('pages.hermesChat.cmdUndo'), argsHint: '', hasArgs: false,
        action: () => {
          const msgs = chatStore.messages
          while (msgs.length > 0) {
            const last = msgs[msgs.length - 1]!
            msgs.pop()
            if (last.role === 'user') break
          }
          chatStore.messages = [...msgs]
        },
      },
      {
        key: '/title', label: '/title', category: 'Session',
        description: t('pages.hermesChat.cmdTitle'), argsHint: '[name]', hasArgs: true,
        action: (args) => {
          if (args && args.trim()) {
            message.info(t('pages.hermesChat.cmdTitleSet', { title: args.trim() }))
          }
        },
      },
      {
        key: '/compress', label: '/compress', category: 'Session',
        description: t('pages.hermesChat.cmdCompress'), argsHint: '[focus topic]', hasArgs: true,
        action: (_args) => {
          message.info(t('pages.hermesChat.cmdCompressHint'))
        },
      },
      {
        key: '/stop', label: '/stop', category: 'Session',
        description: t('pages.hermesChat.cmdStop'), argsHint: '', hasArgs: false,
        action: () => {
          chatStore.stopGeneration()
          message.success(t('pages.hermesChat.cmdStopped'))
        },
      },
      {
        key: '/status', label: '/status', category: 'Session',
        description: t('pages.hermesChat.cmdStatus'), argsHint: '', hasArgs: false,
        action: () => {
          const session = ctx.selectedSession.value
          if (session) {
            message.info(
              `${t('pages.hermesChat.cmdStatusSession')}: ${session.title || session.id}\n` +
              `${t('pages.hermesChat.cmdStatusModel')}: ${session.model || '-'}\n` +
              `${t('pages.hermesChat.cmdStatusMessages')}: ${chatStore.messages.length}`,
            )
          }
        },
      },
      {
        key: '/clear', label: '/clear', category: 'Session',
        description: t('pages.hermesChat.cmdClear'), argsHint: '', hasArgs: false,
        action: () => {
          chatStore.clearMessages()
          ctx.lastTokenUsage.value = null
        },
      },

      // Configuration
      {
        key: '/model', label: '/model', category: 'Configuration',
        description: t('pages.hermesChat.cmdModel'), argsHint: '[model]', hasArgs: true,
        action: (args) => {
          if (args && args.trim()) {
            const target = args.trim()
            const found = modelStore.allSelectableModels.find(m => m.modelId === target || m.label === target)
            if (found) {
              ctx.selectedModelSelection.value = {
                modelId: found.modelId,
                providerName: found.providerName,
                baseUrl: found.baseUrl,
                type: found.type as 'configured' | 'custom',
              }
              message.success(t('pages.hermesChat.cmdModelSwitched', { model: found.label || found.modelId }))
            } else {
              message.warning(t('pages.hermesChat.cmdModelNotFound', { model: target }))
            }
          }
        },
      },
      {
        key: '/provider', label: '/provider', category: 'Configuration',
        description: t('pages.hermesChat.cmdProvider'), argsHint: '', hasArgs: false,
        action: () => {
          const providers = [...new Set(modelStore.models.map(m => m.provider || 'custom'))]
          message.info(`${t('pages.hermesChat.cmdProviderList')}: ${providers.join(', ')}`)
        },
      },
      {
        key: '/yolo', label: '/yolo', category: 'Configuration',
        description: t('pages.hermesChat.cmdYolo'), argsHint: '', hasArgs: false,
        action: () => {
          message.info(t('pages.hermesChat.cmdYoloHint'))
        },
      },

      // Tools & Skills
      {
        key: '/reload', label: '/reload', category: 'Tools & Skills',
        description: t('pages.hermesChat.cmdReload'), argsHint: '', hasArgs: false,
        action: () => {
          connStore.connect().then(() => {
            message.success(t('pages.hermesChat.cmdReloadSuccess'))
          }).catch(() => {
            message.error(t('pages.hermesChat.cmdReloadFailed'))
          })
        },
      },
      {
        key: '/reload-mcp', label: '/reload-mcp', category: 'Tools & Skills',
        description: t('pages.hermesChat.cmdReloadMcp'), argsHint: '', hasArgs: false,
        action: () => {
          message.info(t('pages.hermesChat.cmdReloadMcpHint'))
        },
      },
      {
        key: '/skills', label: '/skills', category: 'Tools & Skills',
        description: t('pages.hermesChat.cmdSkills'), argsHint: '[search|list]', hasArgs: true,
        action: (args) => {
          skillStore.fetchSkills().then(() => {
            const skills = skillStore.skills
            if (args && args.trim()) {
              const keyword = args.trim().toLowerCase()
              const matched = skills.filter(s =>
                s.name.toLowerCase().includes(keyword) ||
                (s.description || '').toLowerCase().includes(keyword) ||
                (s.category || '').toLowerCase().includes(keyword),
              )
              if (matched.length === 0) {
                message.warning(t('pages.hermesChat.cmdSkillsNoMatch', { keyword: args.trim() }))
              } else {
                const list = matched.slice(0, 20).map(s =>
                  `  ${s.enabled ? '✅' : '⬜'} ${s.name}${s.version ? ` v${s.version}` : ''} — ${s.description || s.category || ''}`,
                ).join('\n')
                message.info(`【${t('pages.hermesChat.cmdSkillsMatched')}】(${matched.length})\n${list}`, { duration: 10000 })
              }
            } else {
              const enabled = skills.filter(s => s.enabled).length
              const disabled = skills.length - enabled
              const categories = [...new Set(skills.map(s => s.category || 'other'))]
              const list = skills.slice(0, 30).map(s =>
                `  ${s.enabled ? '✅' : '⬜'} ${s.name}${s.version ? ` v${s.version}` : ''} — ${s.description || s.category || ''}`,
              ).join('\n')
              const summary = `${t('pages.hermesChat.cmdSkillsTotal')}: ${skills.length} (${t('pages.hermesChat.cmdSkillsEnabled')}: ${enabled}, ${t('pages.hermesChat.cmdSkillsDisabled')}: ${disabled})\n${t('pages.hermesChat.cmdSkillsCategories')}: ${categories.join(', ')}`
              message.info(`${summary}\n\n${list}${skills.length > 30 ? '\n  ...' : ''}`, { duration: 12000 })
            }
          }).catch(() => {
            message.error(t('pages.hermesChat.cmdSkillsFailed'))
          })
        },
      },

      // Info
      {
        key: '/commands', label: '/commands', category: 'Info',
        description: t('pages.hermesChat.cmdCommands'), argsHint: '[page]', hasArgs: true,
        action: (_args) => {
          const categories = [...new Set(commands.value.map(c => c.category))]
          const grouped = categories.map(cat => {
            const cmds = commands.value.filter(c => c.category === cat)
            const lines = cmds.map(c => {
              const hint = c.argsHint ? ` ${c.argsHint}` : ''
              return `  ${c.key}${hint.padEnd(20 - c.key.length - hint.length)} ${c.description}`
            }).join('\n')
            return `【${cat}】\n${lines}`
          }).join('\n\n')
          message.info(`${t('pages.hermesChat.cmdCommandsHeader')} (${commands.value.length})\n\n${grouped}`, { duration: 12000 })
        },
      },
      {
        key: '/help', label: '/help', category: 'Info',
        description: t('pages.hermesChat.cmdHelp'), argsHint: '', hasArgs: false,
        action: () => {
          const categories = [...new Set(commands.value.map(c => c.category))]
          const grouped = categories.map(cat => {
            const cmds = commands.value.filter(c => c.category === cat).map(c => `  ${c.key.padEnd(16)} ${c.description}`).join('\n')
            return `【${cat}】\n${cmds}`
          }).join('\n\n')
          message.info(grouped, { duration: 8000 })
        },
      },
      {
        key: '/usage', label: '/usage', category: 'Info',
        description: t('pages.hermesChat.cmdUsage'), argsHint: '', hasArgs: false,
        action: () => {
          if (ctx.lastTokenUsage.value) {
            message.info(
              `${t('pages.hermesChat.tokenInput')}: ${ctx.lastTokenUsage.value.input}\n` +
              `${t('pages.hermesChat.tokenOutput')}: ${ctx.lastTokenUsage.value.output}\n` +
              `${t('pages.hermesChat.tokenTotal')}: ${ctx.lastTokenUsage.value.total}`,
            )
          } else {
            message.info(t('pages.hermesChat.cmdUsageEmpty'))
          }
        },
      },
    ]
    return list
  })

  // ---- Command Panel State ----

  const showCommandPanel = ref(false)
  const commandFilter = ref('')
  const selectedCommandIndex = ref(0)

  const filteredCommands = computed(() => {
    if (!commandFilter.value) return commands.value
    const filter = commandFilter.value.toLowerCase()
    return commands.value.filter(
      (cmd) =>
        cmd.key.toLowerCase().includes(filter) ||
        cmd.description.toLowerCase().includes(filter),
    )
  })

  function handleInputUpdate(value: string) {
    inputText.value = value
    showCommandPanel.value = false
    commandFilter.value = ''
  }

  function handleCommandSelect(cmd: CommandItem) {
    if (cmd.hasArgs) {
      inputText.value = cmd.key + ' '
      showCommandPanel.value = false
      commandFilter.value = ''
      nextTick(() => {
        const textarea = document.querySelector('.chat-input-area textarea') as HTMLTextAreaElement
        if (textarea) {
          textarea.focus()
          textarea.setSelectionRange(textarea.value.length, textarea.value.length)
        }
      })
    } else {
      showCommandPanel.value = false
      commandFilter.value = ''
      inputText.value = ''
      cmd.action()
    }
  }

  function handleCommandKeydown(e: KeyboardEvent) {
    if (!showCommandPanel.value || filteredCommands.value.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      selectedCommandIndex.value =
        (selectedCommandIndex.value + 1) % filteredCommands.value.length
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      selectedCommandIndex.value =
        (selectedCommandIndex.value - 1 + filteredCommands.value.length) %
        filteredCommands.value.length
    } else if (e.key === 'Tab') {
      e.preventDefault()
      const cmd = filteredCommands.value[selectedCommandIndex.value]
      if (cmd) {
        inputText.value = cmd.key + ' '
        showCommandPanel.value = false
        commandFilter.value = ''
      }
    } else if (e.key === 'Enter') {
      if (filteredCommands.value.length === 1) {
        e.preventDefault()
        handleCommandSelect(filteredCommands.value[0]!)
      }
    } else if (e.key === 'Escape') {
      e.preventDefault()
      showCommandPanel.value = false
      commandFilter.value = ''
    }
  }

  return {
    commands,
    filteredCommands,
    showCommandPanel,
    commandFilter,
    selectedCommandIndex,
    handleInputUpdate,
    handleCommandSelect,
    handleCommandKeydown,
  }
}
