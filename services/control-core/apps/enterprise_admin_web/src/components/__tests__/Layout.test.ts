import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock Pinia store
vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    user: { username: 'admin' },
    logout: vi.fn(),
  })),
}))

vi.mock('../../api/index', () => ({
  notificationApi: {
    unreadCount: vi.fn(() => Promise.resolve({ count: 0 })),
  },
}))

// Mock theme module - must provide a ref-like object
vi.mock('../../theme', () => {
  const themeRef = ref('dark')
  return {
    useTheme: () => ({
      theme: themeRef,
      toggleTheme: () => { themeRef.value = themeRef.value === 'light' ? 'dark' : 'light' },
    }),
  }
})

// Stub child components that are complex
vi.mock('../../views/NotificationPanel.vue', () => ({
  default: defineComponent({ render: () => h('div', { 'data-test': 'NotificationPanel' }) }),
}))
vi.mock('../GlobalSearch.vue', () => ({
  default: defineComponent({ render: () => h('div', { 'data-test': 'GlobalSearch' }) }),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      app: { title: 'Agent Admin' },
      nav: {
        dashboard: 'Dashboard', tasks: 'Tasks', taskDag: 'Task DAG',
        audit: 'Audit Log', memory: 'Memory', skills: 'Skills',
        approvals: 'Approvals', cron: 'Cron Jobs', chat: 'Chat',
        conversations: 'Conversations', export: 'Export', health: 'Health',
        analytics: 'Analytics', templates: 'Templates',
        agents: 'Agents', scenarios: 'Scenarios', monitoring: 'Monitoring',
      },
      page: {
        dashboard: 'Dashboard', taskManagement: 'Task Management',
        auditLog: 'Audit Log', memoryManagement: 'Memory Management',
        skillManagement: 'Skill Management', approvalCenter: 'Approval Center',
        cronJobs: 'Cron Jobs', chat: 'Chat', conversations: 'Conversations',
        exportData: 'Export Data', systemHealth: 'System Health',
        analytics: 'Analytics', taskDag: 'Task Dependency Graph',
        taskDetail: 'Task Detail', templates: 'Task Templates',
      },
      auth: { logout: 'Logout' },
      theme: { light: 'Light', dark: 'Dark' },
    },
  },
})

// Generic stub factory for Element Plus components
function elStub(name: string) {
  return defineComponent({
    name,
    setup(_, { slots }) {
      return () => h('div', { 'data-test': name }, slots.default?.())
    },
  })
}

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/dashboard', name: 'Dashboard', component: { render: () => h('div') } },
      { path: '/login', name: 'Login', component: { render: () => h('div') } },
    ],
  })
}

import Layout from '../Layout.vue'

describe('Layout', () => {
  let router: ReturnType<typeof createTestRouter>

  const globalPlugins = {
    plugins: [i18n, router as any],
    stubs: {
      ElContainer: elStub('ElContainer'),
      ElAside: elStub('ElAside'),
      ElHeader: elStub('ElHeader'),
      ElMain: elStub('ElMain'),
      ElMenu: { template: '<div data-test="ElMenu"><slot /></div>' },
      ElMenuItem: { template: '<div data-test="ElMenuItem"><slot /></div>' },
      ElButton: { template: '<button data-test="ElButton"><slot /></button>' },
      ElIcon: { template: '<span data-test="ElIcon"><slot /></span>' },
      ElBadge: { template: '<span data-test="ElBadge"><slot /></span>' },
      ElTooltip: { template: '<span data-test="ElTooltip"><slot /></span>' },
      NotificationPanel: true,
      GlobalSearch: true,
      // Icon components - just render nothing
      DataAnalysis: true, List: true, Document: true, Collection: true,
      MagicStick: true, Select: true, Timer: true, ChatDotRound: true,
      ChatLineSquare: true, Download: true, Monitor: true, TrendCharts: true,
      Bell: true, Sunny: true, Moon: true, DocumentCopy: true, Share: true,
      Lock: true, User: true, VideoPlay: true, DataLine: true,
      RouterView: true,
    },
  }

  beforeEach(async () => {
    router = createTestRouter()
    router.push('/dashboard')
    await router.isReady()
    globalPlugins.plugins = [i18n, router]
  })

  it('renders without errors', async () => {
    const wrapper = mount(Layout, { global: globalPlugins })
    expect(wrapper.find('[data-test="ElContainer"]').exists()).toBe(true)
  })

  it('renders sidebar navigation links', async () => {
    const wrapper = mount(Layout, { global: globalPlugins })
    const menuItems = wrapper.findAll('[data-test="ElMenuItem"]')
    // Dashboard, Chat, Tasks, TaskDAG, Audit, Memory, Skills, Approvals, Cron, Conversations, Export, Health, Analytics, Templates, RBAC, Agents, Scenarios, Monitoring = 18
    expect(menuItems.length).toBe(18)
  })

  it('has a theme toggle button', async () => {
    const wrapper = mount(Layout, { global: globalPlugins })
    // The tooltip wraps the theme toggle button
    const tooltips = wrapper.findAll('[data-test="ElTooltip"]')
    expect(tooltips.length).toBeGreaterThan(0)
  })

  it('has a language toggle button', async () => {
    const wrapper = mount(Layout, { global: globalPlugins })
    // Language toggle shows "EN" or "中文"
    const html = wrapper.html()
    expect(html.includes('EN') || html.includes('中文')).toBe(true)
  })

  it('has a notification bell', async () => {
    const wrapper = mount(Layout, { global: globalPlugins })
    expect(wrapper.find('[data-test="ElBadge"]').exists()).toBe(true)
  })
})
