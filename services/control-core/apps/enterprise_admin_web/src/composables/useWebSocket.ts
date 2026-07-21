/**
 * Base WebSocket composable — handles connect/disconnect/reconnect/heartbeat lifecycle.
 * Consumers provide a URL factory and an onMessage handler; this handles the rest.
 */
import { ref, onUnmounted, getCurrentInstance } from 'vue'
import { createBackoffTimer } from './useExponentialBackoff'

export interface WebSocketOptions {
  /** Factory that returns the WS URL (called on each connect attempt). */
  url: () => string
  /** Called for each incoming message (parsed JSON or raw string). */
  onMessage: (data: unknown) => void
  /** Heartbeat interval in ms. 0 = disabled. Default 30000. */
  heartbeatInterval?: number
  /** Heartbeat payload. Default: `{ type: 'ping' }`. */
  heartbeatPayload?: string
  /** Backoff config overrides. */
  backoff?: { baseDelay?: number; maxDelay?: number; maxRetries?: number }
  /** Whether to auto-connect on mount (when called inside setup). Default false. */
  autoConnect?: boolean
  /** Called when reconnect attempts are exhausted. */
  onExhausted?: () => void
}

export function useWebSocket(opts: WebSocketOptions) {
  const status = ref<'connecting' | 'connected' | 'disconnected'>('disconnected')
  let ws: WebSocket | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  const backoffTimer = createBackoffTimer({
    baseDelay: opts.backoff?.baseDelay ?? 1000,
    maxDelay: opts.backoff?.maxDelay ?? 30000,
    maxRetries: opts.backoff?.maxRetries ?? 10,
  })
  const heartbeatInterval = opts.heartbeatInterval ?? 30000
  const heartbeatPayload = opts.heartbeatPayload ?? JSON.stringify({ type: 'ping' })

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    status.value = 'connecting'

    try {
      ws = new WebSocket(opts.url())
    } catch {
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      status.value = 'connected'
      backoffTimer.reset()
      startHeartbeat()
    }

    ws.onmessage = (event: MessageEvent) => {
      let data: unknown
      try {
        data = JSON.parse(event.data)
      } catch {
        data = event.data // raw string (e.g. 'pong')
      }
      opts.onMessage(data)
    }

    ws.onclose = () => {
      status.value = 'disconnected'
      ws = null // Clear dead reference so reconnect can proceed
      stopHeartbeat()
      scheduleReconnect()
    }

    ws.onerror = () => {
      status.value = 'disconnected'
      // onclose fires after onerror, so reconnect is handled there
    }
  }

  function disconnect() {
    backoffTimer.reset()
    stopHeartbeat()
    if (ws) {
      ws.onclose = null // prevent reconnect on intentional close
      ws.close()
      ws = null
    }
    status.value = 'disconnected'
  }

  function send(data: unknown) {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  function scheduleReconnect() {
    const scheduled = backoffTimer.schedule(() => connect())
    if (!scheduled) {
      console.warn('[WebSocket] Max reconnect retries reached')
      opts.onExhausted?.()
    }
  }

  function startHeartbeat() {
    stopHeartbeat()
    if (heartbeatInterval <= 0) return
    heartbeatTimer = setInterval(() => {
      send(heartbeatPayload)
    }, heartbeatInterval)
  }

  function stopHeartbeat() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
  }

  if (opts.autoConnect) {
    connect()
  }
  // Only auto-cleanup when called inside a component setup (not module-level singletons)
  if (getCurrentInstance()) {
    onUnmounted(disconnect)
  }

  return { status, connect, disconnect, send }
}
