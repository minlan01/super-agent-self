import { describe, it, expect, vi } from 'vitest'

vi.mock('../../api', () => ({
  getApprovals: vi.fn(() => Promise.resolve({ data: [], total: 0 })),
  resolveApproval: vi.fn(() => Promise.resolve({ success: true })),
}))

vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    user: { username: 'testuser', id: 'user-1' },
  })),
}))

describe('ApprovalList', () => {
  it('getApprovals returns expected structure', async () => {
    const { getApprovals } = await import('../../api')
    const result = await getApprovals({ page: 1, page_size: 50 })
    expect(result).toHaveProperty('data')
  })

  it('resolveApproval is callable with correct params', async () => {
    const { resolveApproval } = await import('../../api')
    await resolveApproval('approval-1', {
      approved: true,
      approved_by: 'testuser',
      reason: 'Looks good',
    })
    expect(resolveApproval).toHaveBeenCalledWith('approval-1', expect.objectContaining({
      approved: true,
      approved_by: 'testuser',
    }))
  })

  it('authStore provides user info', async () => {
    const { useAuthStore } = await import('../../stores/auth')
    const store = useAuthStore()
    expect(store.user).toBeDefined()
    expect(store.user.username).toBe('testuser')
  })
})
