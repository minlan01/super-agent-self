import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// Use vi.hoisted to make mocks available in hoisted vi.mock factories
const { mockElMessage } = vi.hoisted(() => ({
  mockElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

vi.mock('element-plus', () => ({
  ElMessage: mockElMessage,
}))

const { mockTasksExport, mockMemoriesExport, mockAuditExport } = vi.hoisted(() => ({
  mockTasksExport: vi.fn(() => Promise.resolve({ items: [] })),
  mockMemoriesExport: vi.fn(() => Promise.resolve({ items: [] })),
  mockAuditExport: vi.fn(() => Promise.resolve({ items: [] })),
}))

vi.mock('../../api', () => ({
  exportApi: {
    tasks: mockTasksExport,
    memories: mockMemoriesExport,
    audit: mockAuditExport,
  },
}))

// Mock URL.createObjectURL and revokeObjectURL (not the full document)
const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:mock-url')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
})

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      export: {
        tasks: 'Tasks',
        memories: 'Memories',
        auditLog: 'Audit Log',
        exportJson: 'Export JSON',
        exportCsv: 'Export CSV',
        exportSuccess: '{key} exported as {format}',
        exportFailed: 'Failed to export {key}',
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
      template: '<button data-test="ElButton" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
      props: ['type', 'loading', 'disabled'],
      emits: ['click'],
    },
    ElRow: { template: '<div data-test="ElRow"><slot /></div>' },
    ElCol: { template: '<div data-test="ElCol"><slot /></div>' },
  },
}

import ExportView from '../ExportView.vue'

describe('ExportView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without errors', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('renders three export sections', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const cards = wrapper.findAll('[data-test="ElCard"]')
    expect(cards.length).toBe(3)
  })

  it('renders section headers', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Tasks')
    expect(wrapper.text()).toContain('Memories')
    expect(wrapper.text()).toContain('Audit Log')
  })

  it('renders JSON and CSV buttons for each section', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    // 3 sections x 2 buttons = 6 buttons
    expect(buttons.length).toBe(6)
    const jsonButtons = buttons.filter(b => b.text().includes('JSON'))
    const csvButtons = buttons.filter(b => b.text().includes('CSV'))
    expect(jsonButtons.length).toBe(3)
    expect(csvButtons.length).toBe(3)
  })

  it('calls export API when JSON button clicked', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const firstJsonBtn = buttons.find(b => b.text().includes('JSON'))
    expect(firstJsonBtn).toBeTruthy()
    await firstJsonBtn!.trigger('click')
    await flushPromises()
    expect(mockTasksExport).toHaveBeenCalledWith('json')
  })

  it('calls export API when CSV button clicked', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const firstCsvBtn = buttons.find(b => b.text().includes('CSV'))
    expect(firstCsvBtn).toBeTruthy()
    await firstCsvBtn!.trigger('click')
    await flushPromises()
    expect(mockTasksExport).toHaveBeenCalledWith('csv')
  })

  it('calls memories export API for memories section', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    // Memories section is second, so JSON button is at index 2
    const memJsonBtn = buttons[2]
    await memJsonBtn.trigger('click')
    await flushPromises()
    expect(mockMemoriesExport).toHaveBeenCalledWith('json')
  })

  it('calls audit export API for audit section', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    // Audit section is third, so JSON button is at index 4
    const auditJsonBtn = buttons[4]
    await auditJsonBtn.trigger('click')
    await flushPromises()
    expect(mockAuditExport).toHaveBeenCalledWith('json')
  })

  it('shows success message after export', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    await buttons[0].trigger('click')
    await flushPromises()
    expect(mockElMessage.success).toHaveBeenCalled()
  })

  it('shows error message on export failure', async () => {
    mockTasksExport.mockRejectedValueOnce(new Error('Network error'))
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    await buttons[0].trigger('click')
    await flushPromises()
    expect(mockElMessage.error).toHaveBeenCalled()
  })

  it('creates blob URL on export', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    await buttons[0].trigger('click')
    await flushPromises()
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('revokes blob URL after download', async () => {
    const wrapper = mount(ExportView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    await buttons[0].trigger('click')
    await flushPromises()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })
})
