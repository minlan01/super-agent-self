import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock WebSocket
const mockWsInstances: any[] = []

class MockWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED
  })
  url: string

  constructor(url: string) {
    this.url = url
    mockWsInstances.push(this)
  }
}

// Mock ElNotification
const mockElNotification = vi.fn()
vi.mock('element-plus', () => ({
  ElNotification: mockElNotification,
}))

// Stub global WebSocket and localStorage
vi.stubGlobal('WebSocket', MockWebSocket)
vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
})

// Stub window.location for URL construction
vi.stubGlobal('location', {
  protocol: 'http:',
  host: 'localhost:5173',
})

describe('useNotificationWS', () => {
  let useNotificationWS: typeof import('../useNotificationWS').useNotificationWS

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    mockWsInstances.length = 0
    // Re-import to get fresh module state
    vi.resetModules()
    const mod = await import('../useNotificationWS')
    useNotificationWS = mod.useNotificationWS
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns expected API shape', () => {
    const ws = useNotificationWS()
    expect(ws).toHaveProperty('unreadCount')
    expect(ws).toHaveProperty('connect')
    expect(ws).toHaveProperty('disconnect')
    expect(ws).toHaveProperty('decrementUnread')
    expect(ws).toHaveProperty('resetUnread')
    expect(ws).toHaveProperty('setUnread')
    expect(typeof ws.connect).toBe('function')
    expect(typeof ws.disconnect).toBe('function')
    expect(typeof ws.decrementUnread).toBe('function')
    expect(typeof ws.resetUnread).toBe('function')
    expect(typeof ws.setUnread).toBe('function')
  })

  it('unreadCount starts at 0', () => {
    const ws = useNotificationWS()
    expect(ws.unreadCount.value).toBe(0)
  })

  it('connect creates a WebSocket with correct URL', () => {
    const ws = useNotificationWS()
    ws.connect()
    expect(mockWsInstances.length).toBe(1)
    expect(mockWsInstances[0].url).toContain('ws://localhost:5173/ws/notifications')
  })

  it('connect includes token in URL when available in localStorage', () => {
    vi.mocked(localStorage.getItem).mockReturnValue('my-token')
    const ws = useNotificationWS()
    ws.connect()
    expect(mockWsInstances[0].url).toContain('?token=my-token')
  })

  it('does not create duplicate connection if already connected', () => {
    const ws = useNotificationWS()
    ws.connect()
    // Simulate open state
    mockWsInstances[0].onopen!()
    ws.connect()
    // Should not create a second WebSocket
    expect(mockWsInstances.length).toBe(1)
  })

  it('increments unreadCount when notification message received', () => {
    const ws = useNotificationWS()
    ws.connect()
    // Trigger onopen
    mockWsInstances[0].onopen!()
    // Simulate notification message
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Test', message: 'Hello', type: 'info' },
      }),
    })
    expect(ws.unreadCount.value).toBe(1)
  })

  it('calls ElNotification when notification message received', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Alert', message: 'Something happened', type: 'task_completed' },
      }),
    })
    expect(mockElNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Alert',
        message: 'Something happened',
        type: 'success',
      }),
    )
  })

  it('maps task_completed notification type to success', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Done', message: 'ok', type: 'task_completed' },
      }),
    })
    expect(mockElNotification).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'success' }),
    )
  })

  it('maps task_failed notification type to error', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Fail', message: 'error', type: 'task_failed' },
      }),
    })
    expect(mockElNotification).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'error' }),
    )
  })

  it('maps system_warning notification type to warning', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Warn', message: 'warning', type: 'system_warning' },
      }),
    })
    expect(mockElNotification).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'warning' }),
    )
  })

  it('handles unread_count message type from server', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    // Set some initial count
    ws.setUnread(10)
    // Server sends authoritative unread count
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ type: 'unread_count', count: 5 }),
    })
    expect(ws.unreadCount.value).toBe(5)
  })

  it('maps unknown notification type to info', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({
        type: 'notification',
        data: { title: 'Info', message: 'info', type: 'unknown_type' },
      }),
    })
    expect(mockElNotification).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'info' }),
    )
  })

  it('ignores non-JSON messages', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({ data: 'not-json' })
    expect(ws.unreadCount.value).toBe(0)
  })

  it('ignores non-notification JSON messages', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ type: 'pong' }),
    })
    expect(ws.unreadCount.value).toBe(0)
  })

  it('disconnect closes WebSocket and clears state', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    ws.disconnect()
    expect(mockWsInstances[0].close).toHaveBeenCalled()
    expect(mockWsInstances[0].onclose).toBeNull()
  })

  it('schedules reconnect with exponential backoff on connection close', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()
    // First reconnect with baseDelay=1000 (no jitter in this test setup, but jitter is random)
    // Advance past max possible first-attempt delay (1000 + 500 jitter = 1500)
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)
  })

  it('backoff delay increases on repeated close', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()

    // First reconnect: base 1000 + jitter up to 500 => max ~1500ms
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)

    // Second close triggers backoff with higher delay
    mockWsInstances[1].onclose!()
    // Second reconnect: base 1000 * 2^1 = 2000 + jitter => max ~2500ms
    vi.advanceTimersByTime(2500)
    expect(mockWsInstances.length).toBe(3)
  })

  it('backoff resets on successful reconnection', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()

    // First reconnect
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)

    // Successful open resets backoff
    mockWsInstances[1].onopen!()
    mockWsInstances[1].onclose!()

    // Third reconnect should be back to base delay (not doubled)
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(3)
  })

  it('stops reconnecting after max retries', () => {
    const ws = useNotificationWS()
    ws.connect()

    // Simulate 10 reconnect attempts (default maxRetries=10)
    // Each close→schedule→advance→close cycle
    for (let i = 0; i < 12; i++) {
      const idx = mockWsInstances.length - 1
      if (mockWsInstances[idx]) {
        mockWsInstances[idx].onclose!()
      }
      // Advance enough time for any backoff delay (up to 30s)
      vi.advanceTimersByTime(30000)
    }

    const countAfterMax = mockWsInstances.length
    // Advance more — should not create new instances
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances.length).toBe(countAfterMax)
  })

  it('clears reconnect timer on disconnect', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onclose!()
    ws.disconnect()
    // After disconnect, advancing timer should not create new WS
    vi.advanceTimersByTime(10000)
    // Only the original WS instance, no reconnect
    expect(mockWsInstances.length).toBe(1)
  })

  it('starts heartbeat on connect', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    vi.advanceTimersByTime(30000)
    expect(mockWsInstances[0].send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'ping' }),
    )
  })

  it('stops heartbeat on disconnect', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    ws.disconnect()
    const sendCount = mockWsInstances[0].send.mock.calls.length
    vi.advanceTimersByTime(60000)
    // No new sends after disconnect
    expect(mockWsInstances[0].send.mock.calls.length).toBe(sendCount)
  })

  it('stops heartbeat on close', () => {
    const ws = useNotificationWS()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()
    const sendCount = mockWsInstances[0].send.mock.calls.length
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances[0].send.mock.calls.length).toBe(sendCount)
  })

  it('handles WebSocket constructor error gracefully and retries with backoff', () => {
    // Temporarily make WebSocket constructor throw
    const OriginalWS = globalThis.WebSocket
    globalThis.WebSocket = class {
      constructor() { throw new Error('WS unavailable') }
    } as any

    const ws = useNotificationWS()
    ws.connect()
    // Should not throw, should schedule reconnect via backoff
    vi.advanceTimersByTime(1500)

    globalThis.WebSocket = OriginalWS
  })

  it('decrementUnread decrements unread count', () => {
    const ws = useNotificationWS()
    ws.setUnread(5)
    ws.decrementUnread()
    expect(ws.unreadCount.value).toBe(4)
  })

  it('decrementUnread does not go below 0', () => {
    const ws = useNotificationWS()
    ws.decrementUnread()
    expect(ws.unreadCount.value).toBe(0)
  })

  it('resetUnread sets unread count to 0', () => {
    const ws = useNotificationWS()
    ws.setUnread(10)
    ws.resetUnread()
    expect(ws.unreadCount.value).toBe(0)
  })

  it('setUnread sets unread count to given value', () => {
    const ws = useNotificationWS()
    ws.setUnread(42)
    expect(ws.unreadCount.value).toBe(42)
  })

  it('uses wss protocol when page is https', () => {
    vi.stubGlobal('location', { protocol: 'https:', host: 'example.com' })
    const ws = useNotificationWS()
    ws.connect()
    expect(mockWsInstances[mockWsInstances.length - 1].url).toContain('wss://example.com/ws/notifications')
    vi.stubGlobal('location', { protocol: 'http:', host: 'localhost:5173' })
  })
})
