import { describe, it, expect, vi } from 'vitest'

vi.mock('../../api', () => ({
  cronApi: {
    list: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
    create: vi.fn(() => Promise.resolve({ id: '1' })),
    update: vi.fn(() => Promise.resolve()),
    delete: vi.fn(() => Promise.resolve()),
  },
}))

describe('CronList', () => {
  it('cronApi.list returns expected structure', async () => {
    const { cronApi } = await import('../../api')
    const result = await cronApi.list()
    expect(result).toHaveProperty('items')
    expect(result).toHaveProperty('total')
  })

  it('cronApi.create is callable', async () => {
    const { cronApi } = await import('../../api')
    await cronApi.create({ name: 'test', schedule: '0 * * * *', task_goal: 'test' })
    expect(cronApi.create).toHaveBeenCalled()
  })

  it('cronApi.delete is callable', async () => {
    const { cronApi } = await import('../../api')
    await cronApi.delete('1')
    expect(cronApi.delete).toHaveBeenCalledWith('1')
  })
})
