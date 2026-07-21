/**
 * Global WebSocket connection for real-time notifications.
 * Built on useWebSocket base composable.
 */
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import { useWebSocket } from './useWebSocket'

const unreadCount = ref(0)

// Singleton: one WS connection shared across the app
let started = false

const { status: wsStatus, connect: wsConnect, disconnect: wsDisconnect } = useWebSocket({
  url: () => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const token = localStorage.getItem('agent_admin_token')
    return `${protocol}//${host}/ws/notifications${token ? '?token=' + token : ''}`
  },
  onMessage(data) {
    if (typeof data === 'string') return // pong etc.
    const msg = data as Record<string, unknown>
    if (msg.type === 'notification') {
      unreadCount.value++
      const msgData = msg.data as Record<string, unknown> | undefined
      ElNotification({
        title: (msgData?.title as string) || 'Notification',
        message: (msgData?.message as string) || '',
        type: mapNotificationType(msgData?.type as string | undefined),
        duration: 5000,
      })
    } else if (msg.type === 'unread_count') {
      unreadCount.value = (msg.count as number) ?? 0
    }
  },
})

function mapNotificationType(type: string | undefined): 'success' | 'warning' | 'error' | 'info' {
  switch (type) {
    case 'task_completed': return 'success'
    case 'task_failed': return 'error'
    case 'system_warning': return 'warning'
    default: return 'info'
  }
}

function decrementUnread() {
  if (unreadCount.value > 0) unreadCount.value--
}

function resetUnread() {
  unreadCount.value = 0
}

function setUnread(count: number) {
  unreadCount.value = count
}

export function useNotificationWS() {
  // Auto-start on first use (singleton pattern)
  if (!started) {
    started = true
    wsConnect()
  }

  return {
    unreadCount,
    connected: wsStatus,
    connect: wsConnect,
    disconnect: wsDisconnect,
    decrementUnread,
    resetUnread,
    setUnread,
  }
}
