import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock API
vi.mock('../../api', () => ({
  getTasks: vi.fn(() => Promise.resolve({ data: { items: [], total: 0 } })),
  createTask: vi.fn(() => Promise.resolve({})),
  cancelTask: vi.fn(() => Promise.resolve({})),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      common: {
        status: 'Status', edition: 'Edition', id: 'ID', goal: 'Goal',
        created: 'Created', actions: 'Actions', detail: 'Detail',
        cancel: 'Cancel', create: 'Create', enterprise: 'Enterprise',
        personal: 'Personal', type: 'Type',
      },
      task: {
        newTask: 'New Task', createTask: 'Create Task', cancelTask: 'Cancel',
        taskCreated: 'Task created', failedToCreate: 'Failed to create',
        taskCancelled: 'Task cancelled', failedToCancel: 'Failed to cancel',
        describeGoal: 'Describe the task goal',
      },
    },
  },
})

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/tasks', name: 'TaskList', component: { render: () => h('div') } },
      { path: '/tasks/:id', name: 'TaskDetail', component: { render: () => h('div') } },
    ],
  })
}

import TaskList from '../TaskList.vue'

describe('TaskList', () => {
  let router: ReturnType<typeof createTestRouter>

  const globalConfig = {
    plugins: [i18n, router as any],
    stubs: {
      ElButton: {
        template: '<button data-test="ElButton" @click="$emit(\'click\')"><slot /></button>',
      },
      ElSelect: { template: '<div data-test="ElSelect"><slot /></div>' },
      ElOption: { template: '<div data-test="ElOption"><slot /></div>' },
      ElTable: { template: '<div data-test="ElTable"><slot /></div>' },
      // ElTableColumn must NOT render its #default slot since it receives scoped data from ElTable
      ElTableColumn: {
        template: '<div data-test="ElTableColumn"><slot name="header" /></div>',
      },
      ElTag: { template: '<span data-test="ElTag"><slot /></span>' },
      ElPagination: { template: '<div data-test="ElPagination"><slot /></div>' },
      ElDialog: { template: '<div data-test="ElDialog"><slot /></div>' },
      ElForm: { template: '<div data-test="ElForm"><slot /></div>' },
      ElFormItem: { template: '<div data-test="ElFormItem"><slot /></div>' },
      ElInput: { template: '<input data-test="ElInput" />' },
      RouterLink: true,
    },
    directives: {
      loading: () => {},
    },
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    router = createTestRouter()
    router.push('/tasks')
    await router.isReady()
    globalConfig.plugins = [i18n, router]
  })

  it('renders without errors', async () => {
    const wrapper = mount(TaskList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('has a create task button', async () => {
    const wrapper = mount(TaskList, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const createBtn = buttons.find(b => b.text().includes('New Task'))
    expect(createBtn).toBeTruthy()
  })

  it('renders a table element', async () => {
    const wrapper = mount(TaskList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })
})
