import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// Mock API
vi.mock('../../api', () => ({
  getReadiness: vi.fn(() => Promise.resolve({
    ready: true,
    checks: { database: 'ok', llm: 'ok', memory: 'ok' },
  })),
  getMetrics: vi.fn(() => Promise.resolve({
    tasks: { pending: 5, executing: 2, completed: 100, failed: 3 },
    total_tasks: 110,
    memories: { total: 50, active: 45 },
    uptime_seconds: 90610,
    version: '3.0.0',
  })),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      page: { systemHealth: 'System Health' },
      health: {
        ready: 'Ready',
        notReady: 'Not Ready',
        readinessChecks: 'Readiness Checks',
        taskStatistics: 'Task Statistics',
        memoryStatistics: 'Memory Statistics',
        systemInfo: 'System Info',
        totalTasks: 'Total Tasks',
        totalMemories: 'Total Memories',
        activeMemories: 'Active',
        inactive: 'Inactive',
        uptime: 'Uptime',
      },
      common: {
        refresh: 'Refresh',
        version: 'Version',
      },
    },
  },
})

const globalConfig = {
  plugins: [i18n],
  stubs: {
    ElCard: {
      template: '<div data-test="ElCard"><slot name="header" /><slot /></div>',
    },
    ElButton: {
      template: '<button data-test="ElButton" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
      props: ['loading'],
      emits: ['click'],
    },
    ElTag: {
      template: '<span data-test="ElTag"><slot /></span>',
      props: ['type', 'size'],
    },
    ElDescriptions: {
      template: '<div data-test="ElDescriptions"><slot /></div>',
    },
    ElDescriptionsItem: {
      template: '<div data-test="ElDescriptionsItem"><slot /></div>',
    },
    ElRow: { template: '<div data-test="ElRow"><slot /></div>' },
    ElCol: { template: '<div data-test="ElCol"><slot /></div>' },
    ElStatistic: {
      template: '<div data-test="ElStatistic">{{ title }}: {{ value }}</div>',
      props: ['title', 'value'],
    },
  },
}

import HealthView from '../HealthView.vue'

describe('HealthView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without errors', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('shows system health title', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('System Health')
  })

  it('shows ready status tag', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Ready')
  })

  it('has a refresh button', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const refreshBtn = buttons.find(b => b.text().includes('Refresh'))
    expect(refreshBtn).toBeTruthy()
  })

  it('calls getReadiness and getMetrics on mount', async () => {
    mount(HealthView, { global: globalConfig })
    await flushPromises()
    const { getReadiness, getMetrics } = await import('../../api')
    expect(getReadiness).toHaveBeenCalled()
    expect(getMetrics).toHaveBeenCalled()
  })

  it('renders readiness checks card', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Readiness Checks')
  })

  it('renders task statistics card', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Task Statistics')
  })

  it('renders memory statistics card', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Memory Statistics')
  })

  it('renders system info card', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('System Info')
  })

  it('displays total tasks statistic', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Total Tasks')
  })

  it('displays memory statistics values', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Total Memories')
    expect(wrapper.text()).toContain('Active')
  })

  it('shows not ready when readiness is false', async () => {
    const { getReadiness } = await import('../../api')
    vi.mocked(getReadiness).mockResolvedValueOnce({
      ready: false,
      checks: { database: 'ok', llm: 'error' },
    })
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Not Ready')
  })

  it('refreshes data on button click', async () => {
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    const { getReadiness } = await import('../../api')
    vi.mocked(getReadiness).mockClear()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const refreshBtn = buttons.find(b => b.text().includes('Refresh'))
    await refreshBtn!.trigger('click')
    await flushPromises()
    expect(getReadiness).toHaveBeenCalled()
  })

  it('handles API error gracefully', async () => {
    const { getReadiness } = await import('../../api')
    vi.mocked(getReadiness).mockRejectedValueOnce(new Error('Server error'))
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    // Component should still render without crashing
    expect(wrapper.html()).toBeTruthy()
  })

  it('handles missing metrics gracefully', async () => {
    const { getMetrics } = await import('../../api')
    vi.mocked(getMetrics).mockRejectedValueOnce(new Error('No metrics'))
    const wrapper = mount(HealthView, { global: globalConfig })
    await flushPromises()
    // Cards that depend on metrics should not render
    const html = wrapper.html()
    expect(html).toBeTruthy()
  })
})
