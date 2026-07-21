/**
 * WebSocket control channel composable for the more_agents backend.
 * Built on useWebSocket base composable.
 */
import { ref } from 'vue'
import { useWebSocket } from './useWebSocket'

export interface ControlMessage {
  type: string
  payload?: Record<string, unknown>
}

export interface ControlResponse {
  type: string
  success: boolean
  data?: unknown
  error?: string
}

export function useControlWS() {
  const lastResponse = ref<ControlResponse | null>(null)

  const { status, connect, disconnect, send } = useWebSocket({
    url: () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      return `${protocol}//${host}/agent-api/ws/control`
    },
    onMessage(data) {
      // Heartbeat response: raw string 'pong' or JSON { type: 'pong' } — ignore
      if (data === 'pong') return
      if (typeof data === 'object' && data !== null && (data as Record<string, unknown>).type === 'pong') return

      const response = data as ControlResponse
      lastResponse.value = response
    },
  })

  function sendCommand(type: string, payload?: Record<string, unknown>) {
    const message: ControlMessage = { type }
    if (payload) {
      message.payload = payload
    }
    send(message)
  }

  return { status, connect, disconnect, sendCommand, lastResponse }
}
