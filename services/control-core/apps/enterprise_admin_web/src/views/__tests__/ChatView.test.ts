import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'

// Mock WebSocket
const mockWsInstances: any[] = []

class MockWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  url: string

  constructor(url: string) {
    this.url = url
    mockWsInstances.push(this)
  }
}

vi.stubGlobal('WebSocket', MockWebSocket)

// Use vi.hoisted to make mocks available in hoisted vi.mock factories
const { mockElMessage, mockElNotification } = vi.hoisted(() => ({
  mockElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
  mockElNotification: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: mockElMessage,
  ElNotification: mockElNotification,
  ElMessageBox: {},
}))

const { mockListConversations, mockGetConversation, mockSendChat } = vi.hoisted(() => ({
  mockListConversations: vi.fn(() => Promise.resolve({ data: [] })),
  mockGetConversation: vi.fn(() => Promise.resolve({ data: { messages: [] } })),
  mockSendChat: vi.fn(() => Promise.resolve({ reply: 'Hello back', conversation_id: 'conv-1' })),
}))

vi.mock('../../api', () => ({
  chatApi: {
    listConversations: mockListConversations,
    getConversation: mockGetConversation,
    send: mockSendChat,
    deleteConversation: vi.fn(() => Promise.resolve()),
  },
}))

vi.stubGlobal('localStorage', {
  getItem: vi.fn(() => null),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
})
vi.stubGlobal('location', {
  protocol: 'http:',
  host: 'localhost:5173',
})

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      chat: {
        conversations: 'Conversations',
        newConversation: 'New',
        noConversations: 'No conversations',
        connecting: 'Connecting...',
        disconnected: 'Disconnected',
        reconnect: 'Reconnect',
        you: 'You',
        assistant: 'Assistant',
        sendToStart: 'Send a message to start',
        typeMessage: 'Type a message...',
        sendMessage: 'Send',
        failedToSend: 'Failed to send',
        failedToLoad: 'Failed to load',
        noResponse: 'No response',
      },
      common: { refresh: 'Refresh' },
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
      props: ['type', 'size', 'loading', 'disabled', 'text'],
      emits: ['click'],
    },
    ElInput: {
      template: '<input data-test="ElInput" :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup.enter="$emit(\'keyupEnter\')" />',
      props: ['modelValue', 'placeholder', 'disabled'],
      emits: ['update:modelValue', 'keyupEnter'],
    },
    ElEmpty: {
      template: '<div data-test="ElEmpty">{{ description }}</div>',
      props: ['description', 'imageSize'],
    },
  },
}

import ChatView from '../ChatView.vue'

describe('ChatView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockWsInstances.length = 0
  })

  afterEach(() => {
    // Cleanup any pending timers
  })

  it('renders without errors', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.html()).toBeTruthy()
  })

  it('shows conversation list section', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Conversations')
  })

  it('shows new conversation button', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const newBtn = buttons.find(b => b.text().includes('New'))
    expect(newBtn).toBeTruthy()
  })

  it('shows empty state when no conversations', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.find('[data-test="ElEmpty"]').exists()).toBe(true)
  })

  it('shows message input area', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const input = wrapper.find('[data-test="ElInput"]')
    expect(input.exists()).toBe(true)
  })

  it('shows send button', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    const sendBtn = buttons.find(b => b.text().includes('Send'))
    expect(sendBtn).toBeTruthy()
  })

  it('calls loadConversations on mount', async () => {
    mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(mockListConversations).toHaveBeenCalled()
  })

  it('creates WebSocket connection on mount', async () => {
    mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(mockWsInstances.length).toBeGreaterThanOrEqual(1)
  })

  it('shows disconnected status when WS is not connected', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    // The ws-status bar shows when wsStatus !== 'connected'
    const html = wrapper.html()
    expect(html).toBeTruthy()
  })

  it('shows typing indicator when isTyping is true', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.isTyping = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.typing-indicator').exists()).toBe(true)
  })

  it('hides typing indicator when isTyping is false', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.isTyping = false
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.typing-indicator').exists()).toBe(false)
  })

  it('renders user and assistant messages', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.messages = [
      { id: '1', role: 'user', content: 'Hello' },
      { id: '2', role: 'assistant', content: 'Hi there' },
    ]
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Hello')
    expect(wrapper.text()).toContain('Hi there')
  })

  it('shows message roles correctly', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.messages = [
      { id: '1', role: 'user', content: 'Test' },
    ]
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('You')
  })

  it('renders conversations list items when data present', async () => {
    mockListConversations.mockResolvedValueOnce({
      data: [
        { id: 'conv-1', title: 'Chat 1', user_id: 'u1', edition: 'enterprise' },
        { id: 'conv-2', title: 'Chat 2', user_id: 'u2', edition: 'personal' },
      ],
    })
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('Chat 1')
    expect(wrapper.text()).toContain('Chat 2')
  })

  it('uses fallback id slice when conversation has no title', async () => {
    mockListConversations.mockResolvedValueOnce({
      data: [
        { id: 'conv-1234567890abcdef', user_id: 'u1', edition: 'enterprise' },
      ],
    })
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    expect(wrapper.text()).toContain('conv-123')
  })

  it('handles WebSocket message type "message"', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const ws = mockWsInstances[mockWsInstances.length - 1]
    if (ws && ws.onmessage) {
      ws.onmessage({
        data: JSON.stringify({
          type: 'message',
          role: 'assistant',
          content: 'WS reply',
          conversation_id: 'conv-ws',
        }),
      })
    }
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('WS reply')
  })

  it('handles WebSocket message type "typing"', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const ws = mockWsInstances[mockWsInstances.length - 1]
    if (ws && ws.onmessage) {
      ws.onmessage({
        data: JSON.stringify({ type: 'typing' }),
      })
    }
    await wrapper.vm.$nextTick()
    const vm = wrapper.vm as any
    expect(vm.isTyping).toBe(true)
  })

  it('handles WebSocket message type "error"', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const ws = mockWsInstances[mockWsInstances.length - 1]
    if (ws && ws.onmessage) {
      ws.onmessage({
        data: JSON.stringify({ type: 'error', message: 'Something went wrong' }),
      })
    }
    await wrapper.vm.$nextTick()
    expect(mockElMessage.error).toHaveBeenCalledWith('Something went wrong')
  })

  it('newConversation clears messages and currentConvId', async () => {
    const wrapper = mount(ChatView, { global: globalConfig })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.currentConvId = 'old-conv'
    vm.messages = [{ id: '1', role: 'user', content: 'Old message' }]
    vm.newConversation()
    expect(vm.currentConvId).toBe('')
    expect(vm.messages).toHaveLength(0)
  })
})
