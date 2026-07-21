/**
 * Per-task WebSocket connection for real-time task progress.
 * Built on useWebSocket base composable.
 */
import { ref, computed } from 'vue'
import { useWebSocket } from './useWebSocket'

interface StepEvent {
  event: string
  step_id: string
  tool: string
  success?: boolean
  reason?: string
}

interface TaskEvent {
  event: string
  steps_completed?: number
}

export type TaskWSEvent = StepEvent | TaskEvent

export function useTaskWS(taskId: string) {
  const lastEvent = ref<TaskWSEvent | null>(null)
  const events = ref<TaskWSEvent[]>([])
  const stepCount = ref(0)
  const taskStatus = ref<string>('')  // '', 'completed', 'failed'

  const { status: wsStatus, connect: wsConnect, disconnect: wsDisconnect } = useWebSocket({
    url: () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const token = localStorage.getItem('agent_admin_token')
      return `${protocol}//${host}/ws/tasks/${taskId}${token ? '?token=' + token : ''}`
    },
    heartbeatPayload: 'ping',
    onMessage(data) {
      // Heartbeat response: raw string 'pong' — ignore
      if (data === 'pong') return
      // Non-JSON strings — ignore
      if (typeof data === 'string') return

      const event = data as TaskWSEvent
      lastEvent.value = event
      events.value.push(event)
      // Cap events array to prevent unbounded memory growth
      if (events.value.length > 200) {
        events.value = events.value.slice(-100)
      }

      if (
        event.event === 'step_completed' ||
        event.event === 'step_failed' ||
        event.event === 'step_rejected'
      ) {
        stepCount.value++
      }
      if (event.event === 'task_completed') {
        taskStatus.value = 'completed'
      }
      if (event.event === 'task_failed') {
        taskStatus.value = 'failed'
      }
    },
  })

  // Bridge: derive connected from base composable's status
  const connected = computed(() => wsStatus.value === 'connected')

  return {
    connected,
    lastEvent,
    events,
    stepCount,
    taskStatus,
    connect: wsConnect,
    disconnect: wsDisconnect,
  }
}
