import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock echarts
vi.mock('@/utils/echarts', () => ({
  default: {
    init: vi.fn(() => ({
      setOption: vi.fn(),
      on: vi.fn(),
      dispose: vi.fn(),
      resize: vi.fn(),
      getOption: vi.fn(() => ({ series: [{ zoom: 1 }] })),
    })),
  },
}))

// Mock element-plus icons
vi.mock('@element-plus/icons-vue', () => ({
  ZoomIn: { render: () => null },
  ZoomOut: { render: () => null },
  Refresh: { render: () => null },
}))

// Mock API
vi.mock('../../api', () => ({
  dagApi: {
    getGraph: vi.fn(() => Promise.resolve({ success: true, data: { nodes: [], edges: [] } })),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      dag: {
        zoomIn: 'Zoom In',
        zoomOut: 'Zoom Out',
        reset: 'Reset',
        refresh: 'Refresh',
        filterStatus: 'Filter by Status',
        noData: 'No task dependencies found',
        nodes: 'Nodes',
        edges: 'Edges',
      },
    },
  },
})

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/task-dag', name: 'TaskDAG', component: { render: () => h('div') } },
      { path: '/tasks/:id', name: 'TaskDetail', component: { render: () => h('div') }, props: true },
    ],
  })
}

import TaskDAGView from '../TaskDAGView.vue'

describe('TaskDAGView', () => {
  let router: ReturnType<typeof createTestRouter>

  const globalConfig = {
    plugins: [i18n, router as any],
    stubs: {
      ElButton: {
        template: '<button data-test="ElButton" @click="$emit(\'click\')"><slot /></button>',
      },
      ElCard: { template: '<div data-test="ElCard"><slot /></div>' },
      ElEmpty: { template: '<div data-test="ElEmpty"><slot /></div>' },
      ElSelect: { template: '<div data-test="ElSelect"><slot /></div>' },
      ElOption: { template: '<div data-test="ElOption"><slot /></div>' },
    },
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    router = createTestRouter()
    router.push('/task-dag')
    await router.isReady()
    globalConfig.plugins = [i18n, router]
  })

  it('renders without errors', async () => {
    const wrapper = mount(TaskDAGView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('has toolbar buttons (zoom in, zoom out, reset, refresh)', async () => {
    const wrapper = mount(TaskDAGView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    // zoom in, zoom out, reset, refresh = at least 4
    expect(buttons.length).toBeGreaterThanOrEqual(4)
    const buttonTexts = buttons.map(b => b.text())
    expect(buttonTexts.some(t => t.includes('Zoom In') || t.includes('Zoom Out') || t.includes('Reset') || t.includes('Refresh'))).toBe(true)
  })

  it('shows empty state when no data', async () => {
    const wrapper = mount(TaskDAGView, { global: globalConfig })
    await flushPromises()
    const empty = wrapper.find('[data-test="ElEmpty"]')
    expect(empty.exists()).toBe(true)
  })
})
