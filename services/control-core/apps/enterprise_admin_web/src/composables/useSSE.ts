/**
 * Server-Sent Events composable — handles connect/disconnect/reconnect lifecycle.
 * Uses the native EventSource API with exponential backoff reconnection.
 */
import { ref, onUnmounted } from 'vue'
import { createBackoffTimer } from './useExponentialBackoff'

export interface SSEOptions {
  /** Factory that returns the SSE URL (called on each connect attempt). */
  url: () => string
  /** Called for each incoming message. */
  onMessage: (event: MessageEvent) => void
  /** Filter specific event types. Empty / undefined = listen to all messages. */
  eventTypes?: string[]
  /** Whether to send cookies with cross-origin requests. Default false. */
  withCredentials?: boolean
  /** Backoff config overrides. */
  backoff?: { baseDelay?: number; maxDelay?: number; maxRetries?: number }
  /** Whether to auto-connect on mount (when called inside setup). Default false. */
  autoConnect?: boolean
}

export function useSSE(opts: SSEOptions) {
  const status = ref<'connecting' | 'connected' | 'disconnected'>('disconnected')
  let es: EventSource | null = null
  let disposed = false
  const backoffTimer = createBackoffTimer({
    baseDelay: opts.backoff?.baseDelay ?? 1000,
    maxDelay: opts.backoff?.maxDelay ?? 30000,
    maxRetries: opts.backoff?.maxRetries ?? 10,
  })

  function connect() {
    if (disposed) return
    if (es && (es.readyState === EventSource.OPEN || es.readyState === EventSource.CONNECTING)) {
      return
    }

    status.value = 'connecting'

    try {
      es = new EventSource(opts.url(), { withCredentials: opts.withCredentials ?? false })
    } catch {
      scheduleReconnect()
      return
    }

    es.onopen = () => {
      status.value = 'connected'
      backoffTimer.reset()
    }

    if (opts.eventTypes && opts.eventTypes.length > 0) {
      // Listen only to specified event types
      for (const type of opts.eventTypes) {
        es.addEventListener(type, opts.onMessage as EventListener)
      }
    } else {
      // Listen to all messages via onmessage
      es.onmessage = opts.onMessage
    }

    es.onerror = () => {
      status.value = 'disconnected'
      cleanupEventSource()
      scheduleReconnect()
    }
  }

  function disconnect() {
    disposed = true
    backoffTimer.cancel()
    cleanupEventSource()
    status.value = 'disconnected'
  }

  function cleanupEventSource() {
    if (es) {
      es.onopen = null
      es.onmessage = null
      es.onerror = null
      es.close()
      es = null
    }
  }

  function scheduleReconnect() {
    if (disposed) return
    const scheduled = backoffTimer.schedule(() => connect())
    if (!scheduled) {
      console.warn('[SSE] Max reconnect retries reached')
    }
  }

  if (opts.autoConnect) {
    connect()
    onUnmounted(disconnect)
  }

  return { status, connect, disconnect }
}
