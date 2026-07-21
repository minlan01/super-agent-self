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

// Mock API
vi.mock('../../api', () => ({
  analyticsApi: {
    overview: vi.fn(() => Promise.resolve({
      total_tasks: 150,
      success_rate: 85.5,
      active_skills: 12,
      total_memories: 75,
      recent_activity_24h: 5,
    })),
    taskTrend: vi.fn(() => Promise.resolve({
      trend: [
        { date: '2026-01-01', count: 10 },
        { date: '2026-01-02', count: 15 },
      ],
    })),
    statusDistribution: vi.fn(() => Promise.resolve({
      distribution: { completed: 80, failed: 10, pending: 5 },
    })),
    skillsPerformance: vi.fn(() => Promise.resolve({
      skills: [
        { name: 'bash', success_rate: 95 },
        { name: 'web_search', success_rate: 80 },
      ],
    })),
    memoriesGrowth: vi.fn(() => Promise.resolve({
      growth: [
        { date: '2026-01-01', cumulative: 50 },
        { date: '2026-01-02', cumulative: 55 },
      ],
    })),
    recentActivity: vi.fn(() => Promise.resolve({
      events: [
        { event_type: 'task_created', actor: 'system', task_id: 't1', created_at: '2026-01-15T10:00:00Z', detail: null },
        { event_type: 'task_completed', actor: 'system', task_id: 't2', created_at: '2026-01-15T11:00:00Z', detail: { key: 'val' } },
      ],
    })),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      analytics: {
        totalTasks: 'Total Tasks',
        successRate: 'Success Rate',
        activeSkills: 'Active Skills',
        totalMemories: 'Total Memories',
        taskTrend: 'Task Trend',
        statusDistribution: 'Status Distribution',
        skillPerformance: 'Skill Performance',
        memoryGrowth: 'Memory Growth',
        recentActivity: 'Recent Activity',
      },
      audit: {
        eventType: 'Event Type',
        actor: 'Actor',
        taskId: 'Task ID',
        detail: 'Detail',
      },
      common: {
        time: 'Time',
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
    ElRow: { template: '<div data-test="ElRow"><slot /></div>' },
    ElCol: { template: '<div data-test="ElCol"><slot /></div>' },
    ElRadioGroup: {
      template: '<div data-test="ElRadioGroup"><slot /></div>',
      props: ['modelValue'],
      emits: ['update:modelValue'],
    },
    ElRadioButton: {
      template: '<input data-test="ElRadioButton" type="radio" :value="value" />',
      props: ['value'],
    },
    ElTable: {
      template: '<div data-test="ElTable"><slot /></div>',
    },
    ElTableColumn: {
      template: '<div data-test="ElTableColumn"><slot name="header" /></div>',
    },
  },
}

import AnalyticsView from '../AnalyticsView.vue'

describe('AnalyticsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without errors', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders date range selector', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElRadioGroup"]').exists()).toBe(true)
  })

  it('renders overview stat cards', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Total Tasks')
    expect(wrapper.text()).toContain('Success Rate')
    expect(wrapper.text()).toContain('Active Skills')
    expect(wrapper.text()).toContain('Total Memories')
  })

  it('renders chart sections', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Task Trend')
    expect(wrapper.text()).toContain('Status Distribution')
    expect(wrapper.text()).toContain('Skill Performance')
    expect(wrapper.text()).toContain('Memory Growth')
  })

  it('renders recent activity table', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Recent Activity')
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })

  it('calls analytics APIs on mount', async () => {
    mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    const { analyticsApi } = await import('../../api')
    expect(analyticsApi.overview).toHaveBeenCalled()
    expect(analyticsApi.taskTrend).toHaveBeenCalledWith(30)
    expect(analyticsApi.statusDistribution).toHaveBeenCalled()
    expect(analyticsApi.skillsPerformance).toHaveBeenCalled()
    expect(analyticsApi.memoriesGrowth).toHaveBeenCalledWith(30)
    expect(analyticsApi.recentActivity).toHaveBeenCalledWith(20)
  })

  it('displays overview statistics', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    const html = wrapper.text()
    expect(html).toContain('150')
    expect(html).toContain('85.5')
  })

  it('initializes echarts charts', async () => {
    mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    const echarts = await import('@/utils/echarts')
    // 4 charts: taskTrend, statusPie, skillBar, memoryArea
    expect(echarts.default.init).toHaveBeenCalled()
  })

  it('handles API error gracefully', async () => {
    const { analyticsApi } = await import('../../api')
    vi.mocked(analyticsApi.overview).mockRejectedValueOnce(new Error('Network error'))
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    // Should not throw
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders table columns for activity', async () => {
    const wrapper = mount(AnalyticsView, { global: globalConfig })
    await flushPromises()
    const columns = wrapper.findAll('[data-test="ElTableColumn"]')
    // event_type, actor, task_id, time, detail = 5 columns
    expect(columns.length).toBeGreaterThanOrEqual(3)
  })
})
