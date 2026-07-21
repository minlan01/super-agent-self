import { computed, ref, type ComputedRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWebSocketStore } from '@/stores/websocket'
import type { Session, SessionsUsageSession, SessionTokenUsage } from '@/api/types'

function normalizeTokenValue(raw: unknown): number {
  if (raw === undefined || raw === null) return 0
  if (typeof raw === 'number') return Math.max(0, raw)
  if (typeof raw === 'string') {
    const n = Number(raw)
    return Number.isFinite(n) ? Math.max(0, n) : 0
  }
  return 0
}

export function useTokenUsage(
  selectedSession: ComputedRef<Session | null>,
  normalizedSessionKey: ComputedRef<string>,
) {
  const { t, locale } = useI18n()
  const wsStore = useWebSocketStore()

  const sessionTokenUsage = ref<SessionTokenUsage | null>(null)
  const sessionTokenUsageLoading = ref(false)
  let sessionTokenUsageRequestId = 0

  function createSessionTokenUsage(params: {
    input: unknown
    output: unknown
    cacheRead?: unknown
    cacheWrite?: unknown
    total?: unknown
  }): SessionTokenUsage {
    const inputValue = normalizeTokenValue(params.input)
    const outputValue = normalizeTokenValue(params.output)
    const cacheReadValue = normalizeTokenValue(params.cacheRead)
    const cacheWriteValue = normalizeTokenValue(params.cacheWrite)
    const totalFromParts = inputValue + outputValue + cacheReadValue + cacheWriteValue
    const totalValue = params.total === undefined
      ? totalFromParts
      : normalizeTokenValue(params.total)

    return {
      input: inputValue,
      output: outputValue,
      cacheRead: cacheReadValue,
      cacheWrite: cacheWriteValue,
      total: totalValue,
    }
  }

  const sessionTokenUsageFromList = computed<SessionTokenUsage | null>(() => {
    const tokenUsage = selectedSession.value?.tokenUsage
    if (!tokenUsage) return null
    return createSessionTokenUsage({
      input: tokenUsage.totalInput,
      output: tokenUsage.totalOutput,
      total: tokenUsage.totalInput + tokenUsage.totalOutput,
    })
  })

  const currentSessionTokenUsage = computed<SessionTokenUsage | null>(() =>
    sessionTokenUsage.value || sessionTokenUsageFromList.value
  )

  function formatTokenCount(value: number): string {
    return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(Math.max(0, value))
  }

  const sessionTokenMetricTags = computed(() => {
    const usage = currentSessionTokenUsage.value
    if (!usage) return []

    return [
      { key: 'total', label: t('pages.chat.tokens.total'), value: formatTokenCount(usage.total), highlight: true },
      { key: 'input', label: t('pages.chat.tokens.input'), value: formatTokenCount(usage.input), highlight: false },
      { key: 'output', label: t('pages.chat.tokens.output'), value: formatTokenCount(usage.output), highlight: false },
      { key: 'cacheRead', label: t('pages.chat.tokens.cacheRead'), value: formatTokenCount(usage.cacheRead), highlight: false },
      { key: 'cacheWrite', label: t('pages.chat.tokens.cacheWrite'), value: formatTokenCount(usage.cacheWrite), highlight: false },
    ]
  })

  const sessionTokenStatusText = computed(() =>
    sessionTokenUsageLoading.value
      ? t('pages.chat.tokens.loading')
      : t('pages.chat.tokens.unavailable')
  )

  function resolveUsageSession(sessions: SessionsUsageSession[], key: string): SessionsUsageSession | null {
    if (sessions.length === 0) return null
    const normalized = key.trim()
    const found = sessions.find((item) => item.key === normalized)
    return found || null
  }

  async function fetchSessionTokenUsage(rawKey: string) {
    const key = rawKey.trim()
    sessionTokenUsageRequestId += 1
    const requestId = sessionTokenUsageRequestId

    if (!key) {
      sessionTokenUsage.value = null
      sessionTokenUsageLoading.value = false
      return
    }

    sessionTokenUsage.value = null
    sessionTokenUsageLoading.value = true

    try {
      const usageResult = await wsStore.rpc.getSessionsUsage({
        key,
        limit: 1,
      })
      if (requestId !== sessionTokenUsageRequestId) return

      const usageSession = resolveUsageSession(usageResult.sessions || [], key)
      if (!usageSession?.usage) {
        sessionTokenUsage.value = null
        return
      }

      sessionTokenUsage.value = createSessionTokenUsage({
        input: usageSession.usage.input,
        output: usageSession.usage.output,
        cacheRead: usageSession.usage.cacheRead,
        cacheWrite: usageSession.usage.cacheWrite,
        total: usageSession.usage.totalTokens,
      })
    } catch (error) {
      if (requestId !== sessionTokenUsageRequestId) return
      sessionTokenUsage.value = null
      console.warn('[useTokenUsage] 获取会话 token 用量失败:', error)
    } finally {
      if (requestId === sessionTokenUsageRequestId) {
        sessionTokenUsageLoading.value = false
      }
    }
  }

  function cancelTokenUsageRequests() {
    sessionTokenUsageRequestId += 1
  }

  return {
    sessionTokenUsage,
    sessionTokenUsageLoading,
    sessionTokenUsageFromList,
    currentSessionTokenUsage,
    sessionTokenMetricTags,
    sessionTokenStatusText,
    formatTokenCount,
    fetchSessionTokenUsage,
    cancelTokenUsageRequests,
  }
}
