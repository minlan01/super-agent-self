/**
 * Chat WebSocket composable — wraps useWebSocket for the chat channel.
 * Handles connect/disconnect/reconnect/heartbeat lifecycle with exponential backoff.
 * Consumers provide an onMessage callback to handle chat-specific message types.
 */
import { useWebSocket } from './useWebSocket'

export interface ChatWSMessage {
  type: string
  [key: string]: unknown
}

export interface ChatWSOptions {
  /** Called for each non-heartbeat message received on the chat channel. */
  onMessage: (data: ChatWSMessage) => void
}

export function useChatWS(opts: ChatWSOptions) {
  const { status, connect, disconnect, send } = useWebSocket({
    url: () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const token = localStorage.getItem('agent_admin_token')
      const base = `${protocol}//${window.location.host}/ws/chat`
      return token ? `${base}?token=${token}` : base
    },
    onMessage(data) {
      // Heartbeat response: raw string 'pong' or JSON { type: 'pong' } — ignore
      if (data === 'pong') return
      if (typeof data === 'object' && data !== null && (data as Record<string, unknown>).type === 'pong') return

      opts.onMessage(data as ChatWSMessage)
    },
  })

  function sendChatMessage(message: string, conversationId?: string) {
    send({
      type: 'chat',
      message,
      ...(conversationId ? { conversation_id: conversationId } : {}),
    })
  }

  return { status, connect, disconnect, send, sendChatMessage }
}
