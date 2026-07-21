import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock ElMessage before any imports
vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    warning: vi.fn(),
    success: vi.fn(),
  },
}))

// Mock localStorage
const store: Record<string, string> = {}
vi.stubGlobal('localStorage', {
  getItem: vi.fn((key: string) => store[key] ?? null),
  setItem: vi.fn((key: string, val: string) => { store[key] = val }),
  removeItem: vi.fn((key: string) => { delete store[key] }),
  clear: vi.fn(() => { Object.keys(store).forEach(k => delete store[k]) }),
})

describe('API module', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.keys(store).forEach(k => delete store[k])
  })

  it('should have correct base URL', async () => {
    const mod = await import('../index')
    const api = mod.default
    expect(api.defaults.baseURL).toBe('/api/v1')
  })

  it('should add Authorization header via request interceptor when token exists', async () => {
    store['agent_admin_token'] = 'test-token-123'

    const mod = await import('../index')
    const api = mod.default

    // Access the request interceptor
    const config = { headers: {} as Record<string, string> }
    const interceptor = api.interceptors.request.handlers[0]
    const result = interceptor.fulfilled(config)
    expect(result.headers.Authorization).toBe('Bearer test-token-123')
  })

  it('should export notificationApi with expected methods', async () => {
    const mod = await import('../index')
    expect(mod.notificationApi).toBeDefined()
    expect(typeof mod.notificationApi.list).toBe('function')
    expect(typeof mod.notificationApi.unreadCount).toBe('function')
    expect(typeof mod.notificationApi.markRead).toBe('function')
    expect(typeof mod.notificationApi.markAllRead).toBe('function')
    expect(typeof mod.notificationApi.clear).toBe('function')
  })
})
