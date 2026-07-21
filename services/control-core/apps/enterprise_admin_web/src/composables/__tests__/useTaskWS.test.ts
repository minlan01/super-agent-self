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

vi.stubGlobal('WebSocket', MockWebSocket)
vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
})
vi.stubGlobal('location', {
  protocol: 'http:',
  host: 'localhost:5173',
})

describe('useTaskWS', () => {
  let useTaskWS: typeof import('../useTaskWS').useTaskWS

  beforeEach(async () => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    mockWsInstances.length = 0
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Import fresh for each test to avoid shared state
  async function getComposable(taskId = 'task-123') {
    vi.resetModules()
    const mod = await import('../useTaskWS')
    return mod.useTaskWS(taskId)
  }

  it('returns expected API shape', async () => {
    const ws = await getComposable()
    expect(ws).toHaveProperty('connected')
    expect(ws).toHaveProperty('lastEvent')
    expect(ws).toHaveProperty('events')
    expect(ws).toHaveProperty('stepCount')
    expect(ws).toHaveProperty('taskStatus')
    expect(ws).toHaveProperty('connect')
    expect(ws).toHaveProperty('disconnect')
    expect(typeof ws.connect).toBe('function')
    expect(typeof ws.disconnect).toBe('function')
  })

  it('initial state is disconnected with empty events', async () => {
    const ws = await getComposable()
    expect(ws.connected.value).toBe(false)
    expect(ws.lastEvent.value).toBeNull()
    expect(ws.events.value).toEqual([])
    expect(ws.stepCount.value).toBe(0)
    expect(ws.taskStatus.value).toBe('')
  })

  it('connect creates WebSocket with task ID in URL', async () => {
    const ws = await getComposable('task-abc')
    ws.connect()
    expect(mockWsInstances.length).toBe(1)
    expect(mockWsInstances[0].url).toContain('/ws/tasks/task-abc')
  })

  it('connect includes token when available', async () => {
    vi.mocked(localStorage.getItem).mockReturnValue('my-jwt')
    const ws = await getComposable('task-1')
    ws.connect()
    expect(mockWsInstances[0].url).toContain('?token=my-jwt')
  })

  it('sets connected to true on open', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    expect(ws.connected.value).toBe(true)
  })

  it('sets connected to false on close', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()
    expect(ws.connected.value).toBe(false)
  })

  it('sets connected to false on error', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onerror!()
    expect(ws.connected.value).toBe(false)
  })

  it('parses step_completed event and increments stepCount', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'step_completed', step_id: 's1', tool: 'bash' }),
    })
    expect(ws.stepCount.value).toBe(1)
    expect(ws.lastEvent.value).toEqual({ event: 'step_completed', step_id: 's1', tool: 'bash' })
    expect(ws.events.value).toHaveLength(1)
  })

  it('parses step_failed event and increments stepCount', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'step_failed', step_id: 's2', tool: 'web_search' }),
    })
    expect(ws.stepCount.value).toBe(1)
  })

  it('parses step_rejected event and increments stepCount', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'step_rejected', step_id: 's3', tool: 'file_write' }),
    })
    expect(ws.stepCount.value).toBe(1)
  })

  it('sets taskStatus to completed on task_completed event', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'task_completed', steps_completed: 5 }),
    })
    expect(ws.taskStatus.value).toBe('completed')
  })

  it('sets taskStatus to failed on task_failed event', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'task_failed', steps_completed: 2 }),
    })
    expect(ws.taskStatus.value).toBe('failed')
  })

  it('accumulates multiple events', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'step_completed', step_id: 's1', tool: 'a' }),
    })
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'step_completed', step_id: 's2', tool: 'b' }),
    })
    mockWsInstances[0].onmessage!({
      data: JSON.stringify({ event: 'task_completed', steps_completed: 2 }),
    })
    expect(ws.events.value).toHaveLength(3)
    expect(ws.stepCount.value).toBe(2)
  })

  it('ignores pong text messages', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({ data: 'pong' })
    expect(ws.events.value).toHaveLength(0)
  })

  it('ignores non-JSON messages', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onmessage!({ data: 'not-json' })
    expect(ws.events.value).toHaveLength(0)
  })

  it('starts heartbeat on open and sends ping', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    vi.advanceTimersByTime(30000)
    expect(mockWsInstances[0].send).toHaveBeenCalledWith('ping')
  })

  it('stops heartbeat on close', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()
    const sendCount = mockWsInstances[0].send.mock.calls.length
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances[0].send.mock.calls.length).toBe(sendCount)
  })

  it('disconnect closes WebSocket and sets connected false', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    ws.disconnect()
    expect(mockWsInstances[0].close).toHaveBeenCalled()
    expect(mockWsInstances[0].onclose).toBeNull()
    expect(ws.connected.value).toBe(false)
  })

  it('disconnect clears heartbeat', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    ws.disconnect()
    const sendCount = mockWsInstances[0].send.mock.calls.length
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances[0].send.mock.calls.length).toBe(sendCount)
  })

  it('uses wss protocol when page is https', async () => {
    vi.stubGlobal('location', { protocol: 'https:', host: 'secure.example.com' })
    const ws = await getComposable('task-secure')
    ws.connect()
    expect(mockWsInstances[mockWsInstances.length - 1].url).toContain('wss://secure.example.com/ws/tasks/task-secure')
    vi.stubGlobal('location', { protocol: 'http:', host: 'localhost:5173' })
  })

  it('handles WebSocket constructor error gracefully', async () => {
    const OriginalWS = globalThis.WebSocket
    globalThis.WebSocket = class {
      constructor() { throw new Error('WS error') }
    } as any

    const ws = await getComposable()
    ws.connect()
    // Should not throw
    expect(ws.connected.value).toBe(false)

    globalThis.WebSocket = OriginalWS
  })

  // --- Exponential backoff reconnection tests ---

  it('onclose triggers reconnect with exponential backoff', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()

    // First reconnect delay: base 1000 + jitter up to 500 => max ~1500ms
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)
  })

  it('onerror does not trigger reconnect directly', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onerror!()

    // onerror alone should NOT create a new WebSocket
    // Only onclose triggers reconnect
    vi.advanceTimersByTime(5000)
    // Still only 1 instance — onerror does not reconnect
    expect(mockWsInstances.length).toBe(1)
  })

  it('successful connect resets backoff delay', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()

    // First reconnect
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)

    // Successful open resets backoff
    mockWsInstances[1].onopen!()
    mockWsInstances[1].onclose!()

    // Second reconnect should use base delay again (not doubled)
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(3)
  })

  it('disconnect resets backoff and prevents reconnect', async () => {
    const ws = await getComposable()
    ws.connect()
    mockWsInstances[0].onopen!()
    mockWsInstances[0].onclose!()

    // Disconnect before reconnect timer fires
    ws.disconnect()

    // Advance well past any possible delay — no new WS should be created
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances.length).toBe(1)
  })

  it('stops reconnecting after max retries reached', async () => {
    const ws = await getComposable()
    ws.connect()

    // Simulate repeated close→reconnect cycles up to maxRetries (default 10)
    for (let i = 0; i < 12; i++) {
      const idx = mockWsInstances.length - 1
      if (mockWsInstances[idx]) {
        mockWsInstances[idx].onclose!()
      }
      // Advance enough for any backoff delay (up to 30s)
      vi.advanceTimersByTime(30000)
    }

    const countAfterMax = mockWsInstances.length
    // Advance more — should not create new instances
    vi.advanceTimersByTime(60000)
    expect(mockWsInstances.length).toBe(countAfterMax)
  })

  it('backoff delay increases on repeated close without successful open', async () => {
    const ws = await getComposable()
    ws.connect()
    // Don't call onopen — simulate failed connection attempts
    mockWsInstances[0].onclose!()

    // First reconnect: max ~1500ms
    vi.advanceTimersByTime(1500)
    expect(mockWsInstances.length).toBe(2)

    // Second close triggers higher backoff
    mockWsInstances[1].onclose!()
    // Second reconnect: 1000*2^1 = 2000 + jitter => max ~2500ms
    vi.advanceTimersByTime(2500)
    expect(mockWsInstances.length).toBe(3)
  })
})
