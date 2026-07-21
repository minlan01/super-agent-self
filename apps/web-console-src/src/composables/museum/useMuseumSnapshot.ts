import { ref, readonly } from 'vue'
import { useOfficeStore } from '@/stores/office'
import { useAgentStore } from '@/stores/agent'
import { useSessionStore } from '@/stores/session'
import { useChatStore } from '@/stores/chat'
import { useWebSocketStore } from '@/stores/websocket'

export function useMuseumSnapshot() {
  const officeStore = useOfficeStore()
  const agentStore = useAgentStore()
  const sessionStore = useSessionStore()
  const chatStore = useChatStore()
  const wsStore = useWebSocketStore()

  const isInitialized = ref(false)
  const isCharactersInitialized = ref(false)
  const eventCleanups: Array<() => void> = []

  async function initialize() {
    await officeStore.loadOfficeData()
    await sessionStore.fetchSessions()
  }

  async function refresh() {
    await Promise.all([
      officeStore.loadOfficeData(),
      sessionStore.fetchSessions(),
      agentStore.fetchAgents(),
    ])
  }

  function setupWebSocketAgentEvents() {
    eventCleanups.push(
      wsStore.subscribe('event', (evt: unknown) => {
        const data = evt as { event?: string; payload?: unknown }
        const eventName = data.event || ''
        if (
          eventName === 'chat' ||
          eventName.startsWith('chat.') ||
          eventName === 'agent' ||
          eventName.startsWith('agent.')
        ) {
          chatStore.handleAgentStatusEvent(eventName, data.payload)
        }
      })
    )
  }

  function startTimeInterval(currentTime: ReturnType<typeof ref<number>>) {
    const timeInterval = setInterval(() => {
      currentTime.value = Date.now()
    }, 1000)
    eventCleanups.push(() => clearInterval(timeInterval))
  }

  function resetCharacters() {
    isCharactersInitialized.value = false
  }

  function markCharactersInitialized() {
    isCharactersInitialized.value = true
  }

  function cleanup() {
    eventCleanups.forEach((cleanup) => cleanup())
    eventCleanups.length = 0
  }

  return {
    isInitialized,
    isCharactersInitialized,
    initialize,
    refresh,
    setupWebSocketAgentEvents,
    startTimeInterval,
    resetCharacters,
    markCharactersInitialized,
    cleanup,
  }
}
