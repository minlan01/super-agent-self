import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'
import { defineComponent, h } from 'vue'

// Mock ElMessage and ElMessageBox
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(() => Promise.resolve()) },
}))

// Mock API
vi.mock('../../api', () => ({
  chatApi: {
    listConversations: vi.fn(() => Promise.resolve({
      data: [
        { id: 'conv-1', user_id: 'user-1', title: 'Test Chat', edition: 'enterprise', created_at: '2026-01-15T10:00:00Z' },
        { id: 'conv-2', user_id: 'user-2', title: 'Personal Chat', edition: 'personal', created_at: '2026-01-16T14:30:00Z' },
      ],
    })),
    deleteConversation: vi.fn(() => Promise.resolve()),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      chat: {
        conversations: 'Conversations',
        totalConversations: '{count} conversations',
        newConversation: 'New',
        noConversations: 'No conversations',
      },
      common: {
        id: 'ID',
        name: 'Name',
        edition: 'Edition',
        created: 'Created',
        actions: 'Actions',
        view: 'View',
        delete: 'Delete',
        refresh: 'Refresh',
        confirm: 'Confirm',
        cancel: 'Cancel',
      },
      conversation: {
        userId: 'User ID',
        deleteConfirm: 'Delete {title}?',
        deleted: 'Deleted',
        deleteFailed: 'Delete failed',
      },
    },
  },
})

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/conversations', component: { render: () => h('div') } },
      { path: '/chat', component: { render: () => h('div') } },
    ],
  })
}

import ConversationList from '../ConversationList.vue'

describe('ConversationList', () => {
  let router: ReturnType<typeof createTestRouter>

  const globalConfig: any = {
    plugins: [i18n],
    stubs: {
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
      ElTag: { template: '<span data-test="ElTag"><slot /></span>' },
      RouterLink: true,
    },
    directives: {
      loading: () => {},
    },
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    router = createTestRouter()
    router.push('/conversations')
    await router.isReady()
    globalConfig.plugins = [i18n, router]
  })

  it('renders without errors', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('calls loadConversations on mount', async () => {
    mount(ConversationList, { global: globalConfig })
    await flushPromises()
    const { chatApi } = await import('../../api')
    expect(chatApi.listConversations).toHaveBeenCalled()
  })

  it('shows conversation count', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('conversations')
  })

  it('renders a table', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })

  it('has a refresh button', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const refreshBtn = buttons.find(b => b.text().includes('Refresh'))
    expect(refreshBtn).toBeTruthy()
  })

  it('reloads data when refresh is clicked', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    const { chatApi } = await import('../../api')
    vi.mocked(chatApi.listConversations).mockClear()

    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const refreshBtn = buttons.find(b => b.text().includes('Refresh'))
    await refreshBtn!.trigger('click')
    await flushPromises()
    expect(chatApi.listConversations).toHaveBeenCalled()
  })

  it('renders table columns', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    const columns = wrapper.findAll('[data-test="ElTableColumn"]')
    // ID, User ID, Name, Edition, Created, Actions = 6 columns
    expect(columns.length).toBeGreaterThanOrEqual(4)
  })

  it('handles empty conversations list', async () => {
    const { chatApi } = await import('../../api')
    vi.mocked(chatApi.listConversations).mockResolvedValueOnce({ data: [] })
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElTable"]').exists()).toBe(true)
  })

  it('sets loading to false after fetch completes', async () => {
    const wrapper = mount(ConversationList, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.loading).toBe(false)
  })
})
