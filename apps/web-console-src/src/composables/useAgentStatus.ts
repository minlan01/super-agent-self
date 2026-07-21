import { computed, type ComputedRef, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '@/stores/chat'
import type { RenderMessage } from '@/api/types'

export function useAgentStatus(
  visibleMessageEntries: ComputedRef<RenderMessage[]>,
  nowMs: Ref<number>,
) {
  const { t } = useI18n()
  const chatStore = useChatStore()

  const currentAgentId = computed(() => {
    const sessionKey = chatStore.sessionKey
    if (!sessionKey) return 'default'
    const match = sessionKey.match(/^agent:([^:]+):/)
    if (match && match[1]) {
      return match[1]
    }
    return 'default'
  })

  const currentAgentStatus = computed(() => {
    return chatStore.getOrCreateAgentStatus(currentAgentId.value)
  })

  const currentToolProgress = computed(() => {
    return chatStore.toolProgress.get(currentAgentId.value) || null
  })

  const agentBusy = computed(() => {
    const phase = currentAgentStatus.value.phase
    return (
      phase === 'sending' ||
      phase === 'waiting' ||
      phase === 'thinking' ||
      phase === 'tool' ||
      phase === 'replying' ||
      phase === 'aborting'
    )
  })

  const agentBusyToolName = computed(() => {
    if (!agentBusy.value) return ''

    const toolProgress = currentToolProgress.value
    if (toolProgress && toolProgress.phase !== 'result' && toolProgress.name.trim()) {
      return toolProgress.name.trim()
    }

    const phase = currentAgentStatus.value.phase
    if (phase === 'replying' || phase === 'aborting') return ''

    const runId = currentAgentStatus.value.runId
    const list = visibleMessageEntries.value
    let startIndex = 0
    if (runId) {
      const idx = list.findIndex((entry) => entry.item.id === runId)
      if (idx >= 0) startIndex = idx + 1
    }

    for (let i = list.length - 1; i >= startIndex; i -= 1) {
      const entry = list[i]
      if (!entry) continue
      const item = entry.item
      if (item.role !== 'assistant') continue
      const structured = entry.structured
      if (!structured) return ''

      if (structured.toolCalls.length === 0) return ''
      if (structured.toolResults.length >= structured.toolCalls.length) {
        return ''
      }

      const lastToolCall = structured.toolCalls[structured.toolCalls.length - 1]
      if (!lastToolCall?.name) return ''
      const normalized = lastToolCall.name.trim()
      return normalized
    }

    return ''
  })

  const agentStatusTagType = computed<'default' | 'success' | 'warning' | 'info' | 'error'>(() => {
    if (agentBusyToolName.value) return 'warning'
    const phase = currentAgentStatus.value.phase
    if (phase === 'replying' || phase === 'sending' || phase === 'waiting' || phase === 'thinking') return 'info'
    if (phase === 'tool' || phase === 'aborting' || phase === 'aborted') return 'warning'
    if (phase === 'done') return 'success'
    if (phase === 'error') return 'error'
    return 'default'
  })

  const agentStatusText = computed(() => {
    if (agentBusyToolName.value) return t('pages.chat.agentStatus.toolCall', { name: agentBusyToolName.value })
    const status = currentAgentStatus.value
    if (status.phase === 'sending') return t('pages.chat.agentStatus.sending')
    if (status.phase === 'waiting') return t('pages.chat.agentStatus.waiting')
    if (status.phase === 'thinking') return status.detail ? status.detail : t('pages.chat.agentStatus.thinking')
    if (status.phase === 'tool') {
      return status.detail
        ? t('pages.chat.agentStatus.toolCall', { name: status.detail })
        : t('pages.chat.agentStatus.toolRunning')
    }
    if (status.phase === 'replying') return t('pages.chat.agentStatus.replying')
    if (status.phase === 'aborting') return t('pages.chat.agentStatus.aborting')
    if (status.phase === 'done') return t('pages.chat.agentStatus.done')
    if (status.phase === 'aborted') return t('pages.chat.agentStatus.aborted')
    if (status.phase === 'error') {
      return status.detail
        ? t('pages.chat.agentStatus.errorWithDetail', { detail: status.detail })
        : t('pages.chat.agentStatus.error')
    }
    return t('pages.chat.agentStatus.idle')
  })

  const hasAgentDetails = computed(() => {
    if (agentBusy.value) return true
    const agentSteps = chatStore.agentSteps.get(currentAgentId.value)
    if (agentSteps && agentSteps.length > 0) return true
    if (currentToolProgress.value) return true
    return false
  })

  const toolElapsedMs = computed(() => {
    const progress = currentToolProgress.value
    if (!progress) return 0
    const endAt = progress.phase === 'result' ? progress.updatedAtMs : nowMs.value
    return endAt - progress.startedAtMs
  })

  return {
    currentAgentId,
    currentAgentStatus,
    currentToolProgress,
    agentBusy,
    agentBusyToolName,
    agentStatusTagType,
    agentStatusText,
    hasAgentDetails,
    toolElapsedMs,
  }
}
