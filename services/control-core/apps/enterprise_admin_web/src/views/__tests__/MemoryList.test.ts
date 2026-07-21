import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// Mock ElMessage and ElMessageBox
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(() => Promise.resolve()) },
}))

// Mock API
vi.mock('../../api', () => ({
  getMemories: vi.fn(() => Promise.resolve({
    data: [
      {
        id: 'mem-1',
        title: 'Test Memory',
        memory_type: 'execution_experience',
        summary: 'A test memory',
        importance_score: 0.85,
        confidence_score: 0.92,
        is_active: true,
        created_at: '2026-01-15T10:00:00Z',
      },
      {
        id: 'mem-2',
        title: 'Inactive Memory',
        memory_type: 'domain_knowledge',
        summary: 'An inactive memory',
        importance_score: 0.5,
        confidence_score: 0.7,
        is_active: false,
        created_at: '2026-01-14T08:00:00Z',
      },
    ],
  })),
  searchMemories: vi.fn(() => Promise.resolve({
    data: [
      {
        id: 'mem-3',
        title: 'Search Result',
        memory_type: 'workflow_pattern',
        summary: 'Found by search',
        importance_score: 0.6,
        confidence_score: 0.8,
        is_active: true,
        created_at: '2026-01-16T12:00:00Z',
      },
    ],
  })),
  disableMemory: vi.fn(() => Promise.resolve()),
  deleteMemory: vi.fn(() => Promise.resolve()),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      memory: {
        searchMemories: 'Search memories',
        title: 'Title',
        summary: 'Summary',
        importance: 'Importance',
        confidence: 'Confidence',
        active: 'Active',
        disableConfirm: 'Disable this memory?',
        disabled: 'Memory disabled',
        deleteConfirm: 'Delete this memory?',
        deleted: 'Memory deleted',
      },
      common: {
        type: 'Type',
        created: 'Created',
        actions: 'Actions',
        search: 'Search',
        yes: 'Yes',
        no: 'No',
        delete: 'Delete',
        confirm: 'Confirm',
        cancel: 'Cancel',
      },
      skill: {
        disable: 'Disable',
      },
    },
  },
})

const globalConfig = {
  plugins: [i18n],
  stubs: {
    ElInput: {
      template: '<input data-test="ElInput" :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup.enter="$emit(\'keyupEnter\')" />',
      props: ['modelValue', 'placeholder', 'clearable'],
      emits: ['update:modelValue', 'keyupEnter'],
    },
    ElSelect: {
      template: '<div data-test="ElSelect"><slot /></div>',
    },
    ElOption: {
      template: '<div data-test="ElOption"><slot /></div>',
      props: ['label', 'value'],
    },
    ElButton: {
      template: '<button data-test="ElButton" @click="$emit(\'click\')"><slot /></button>',
      emits: ['click'],
    },
    ElTable: {
      template: '<div data-test="ElTable"><slot /></div>',
    },
    ElTableColumn: {
      template: '<div data-test="ElTableColumn"><slot name="header" /></div>',
    },
    ElTag: {
      template: '<span data-test="ElTag"><slot /></span>',
      props: ['type', 'size'],
    },
    ElProgress: {
      template: '<div data-test="ElProgress"></div>',
      props: ['percentage', 'strokeWidth'],
    },
  },
  directives: {
    loading: () => {},
  },
}

import MemoryList from '../MemoryList.vue'

describe('MemoryList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without errors', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('calls getMemories on mount', async () => {
    mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const { getMemories } = await import('../../api')
    expect(getMemories).toHaveBeenCalledWith({ page: 1, page_size: 50 })
  })

  it('renders search input', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const inputs = wrapper.findAll('[data-test="ElInput"]')
    expect(inputs.length).toBeGreaterThanOrEqual(1)
  })

  it('renders type select dropdown', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElSelect"]').exists()).toBe(true)
  })

  it('renders memory type options', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const options = wrapper.findAll('[data-test="ElOption"]')
    expect(options.length).toBe(5) // 5 memory types
  })

  it('renders search button', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const searchBtn = buttons.find(b => b.text().includes('Search'))
    expect(searchBtn).toBeTruthy()
  })

  it('renders table', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })

  it('renders table columns', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const columns = wrapper.findAll('[data-test="ElTableColumn"]')
    // title, type, summary, importance, confidence, active, created, actions = 8 columns
    expect(columns.length).toBeGreaterThanOrEqual(5)
  })

  it('calls searchMemories when search is triggered', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const { searchMemories } = await import('../../api')
    vi.mocked(searchMemories).mockClear()

    // Set keyword via component's ref
    const vm = wrapper.vm as any
    vm.keyword = 'test keyword'
    await wrapper.vm.$nextTick()

    // Trigger search
    vm.search()
    await flushPromises()

    expect(searchMemories).toHaveBeenCalledWith(
      expect.objectContaining({ keyword: 'test keyword', limit: 50 }),
    )
  })

  it('includes memory_type in loadMemories params when selected', async () => {
    const { getMemories } = await import('../../api')
    vi.mocked(getMemories).mockClear()
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.memoryType = 'execution_experience'
    vm.loadMemories()
    await flushPromises()

    expect(getMemories).toHaveBeenCalledWith(
      expect.objectContaining({ memory_type: 'execution_experience' }),
    )
  })

  it('handles empty memory list', async () => {
    const { getMemories } = await import('../../api')
    vi.mocked(getMemories).mockResolvedValueOnce({ data: [] })
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })

  it('sets loading to false after fetch completes', async () => {
    const wrapper = mount(MemoryList, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.loading).toBe(false)
  })
})
