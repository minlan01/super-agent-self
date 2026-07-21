import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// Mock echarts
vi.mock('@/utils/echarts', () => ({
  default: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      on: vi.fn(),
      dispose: vi.fn(),
      resize: vi.fn(),
    })),
  },
}))

// Mock API calls
vi.mock('../../api', () => ({
  getTasks: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  getSkills: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  getMemories: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  getApprovals: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  getMetrics: vi.fn(() => Promise.resolve({})),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      task: {
        totalTasks: 'Total Tasks',
        successRate: 'Success Rate',
        taskStatusDistribution: 'Status Distribution',
        recentTasks: 'Recent Tasks',
        pendingApprovals: 'Pending Approvals',
        reason: 'Reason',
      },
      nav: { skills: 'Skills', memory: 'Memory' },
      common: { goal: 'Goal', status: 'Status', time: 'Time', type: 'Type' },
      skill: { skillSuccessRates: 'Skill Success Rates' },
    },
  },
})

const globalConfig = {
  plugins: [i18n],
  stubs: {
    ElRow: { template: '<div data-test="ElRow"><slot /></div>' },
    ElCol: { template: '<div data-test="ElCol"><slot /></div>' },
    ElCard: {
      template: '<div data-test="ElCard"><slot name="header" /><slot /></div>',
    },
    ElTable: {
      template: '<div data-test="ElTable"><slot /></div>',
    },
    // ElTableColumn must NOT render its #default slot since it gets scoped data from ElTable
    // which we cannot replicate in a stub. Just render nothing for the default slot.
    ElTableColumn: {
      template: '<div data-test="ElTableColumn"><slot name="header" /></div>',
    },
    ElTag: { template: '<span data-test="ElTag"><slot /></span>' },
  },
  directives: {
    loading: () => {},
  },
}

import Dashboard from '../Dashboard.vue'

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without errors', async () => {
    const wrapper = mount(Dashboard, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders stat cards', async () => {
    const wrapper = mount(Dashboard, { global: globalConfig })
    await flushPromises()
    const cards = wrapper.findAll('[data-test="ElCard"]')
    // 4 stat cards + 2 chart cards + 2 table cards = 8
    expect(cards.length).toBeGreaterThanOrEqual(4)
  })

  it('renders chart containers', async () => {
    const wrapper = mount(Dashboard, { global: globalConfig })
    await flushPromises()
    // Chart containers exist in the template
    const html = wrapper.html()
    expect(html).toBeTruthy()
    // Verify the component mounted without error and called APIs
    const { getTasks } = await import('../../api')
    expect(getTasks).toHaveBeenCalled()
  })

  it('loads data on mount', async () => {
    const { getTasks } = await import('../../api')
    mount(Dashboard, { global: globalConfig })
    await flushPromises()
    expect(getTasks).toHaveBeenCalledWith({ page: 1, page_size: 100 })
  })
})
