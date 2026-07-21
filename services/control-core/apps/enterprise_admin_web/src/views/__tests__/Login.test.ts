import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock stores/auth
const mockLogin = vi.fn()
vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    login: mockLogin,
    user: null,
  })),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  fallbackLocale: 'en',
  messages: {
    en: {
      app: { title: 'Agent Admin' },
      auth: {
        signInToAccount: 'Sign in to your account',
        username: 'Username',
        password: 'Password',
        enterUsername: 'Enter username',
        enterPassword: 'Enter password',
        login: 'Sign In',
        loginSuccessful: 'Login successful',
        loginFailed: 'Login failed',
        pleaseEnterUsername: 'Please enter username',
        pleaseEnterPassword: 'Please enter password',
        noAccount: "Don't have an account? Create one",
        logout: 'Logout',
      },
    },
  },
})

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'Login', component: { render: () => h('div') } },
      { path: '/register', name: 'Register', component: { render: () => h('div') } },
      { path: '/dashboard', name: 'Dashboard', component: { render: () => h('div') } },
    ],
  })
}

const ElInput = defineComponent({
  name: 'ElInput',
  props: ['modelValue', 'type', 'placeholder'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      'data-test': 'ElInput',
      value: props.modelValue || '',
      type: props.type || 'text',
      placeholder: props.placeholder || '',
      onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value),
    })
  },
})

const ElButton = defineComponent({
  name: 'ElButton',
  props: ['type', 'loading', 'disabled'],
  emits: ['click'],
  setup(props, { slots, emit }) {
    return () => h('button', {
      'data-test': 'ElButton',
      disabled: props.loading || props.disabled,
      onClick: () => emit('click'),
    }, slots.default?.())
  },
})

// ElForm stub with validate method exposed via ref
const ElForm = defineComponent({
  name: 'ElForm',
  emits: ['submit'],
  setup(_, { slots, expose }) {
    const validate = () => Promise.resolve(true)
    expose({ validate })
    return () => h('form', {
      'data-test': 'ElForm',
      onSubmit: (e: Event) => { e.preventDefault() },
    }, slots.default?.())
  },
})

import Login from '../Login.vue'

describe('Login', () => {
  let router: ReturnType<typeof createTestRouter>

  const globalConfig = {
    plugins: [i18n, router as any],
    stubs: {
      ElCard: {
        template: '<div data-test="ElCard"><slot name="header" /><slot /></div>',
      },
      ElForm,
      ElFormItem: {
        template: '<div data-test="ElFormItem"><slot /></div>',
      },
      ElInput,
      ElButton,
      RouterLink: {
        template: '<a data-test="RouterLink"><slot /></a>',
      },
    },
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    router = createTestRouter()
    router.push('/login')
    await router.isReady()
    globalConfig.plugins = [i18n, router]
  })

  it('renders username and password inputs', async () => {
    const wrapper = mount(Login, { global: globalConfig })
    const inputs = wrapper.findAll('[data-test="ElInput"]')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })

  it('renders a login button', async () => {
    const wrapper = mount(Login, { global: globalConfig })
    const buttons = wrapper.findAll('[data-test="ElButton"]')
    expect(buttons.length).toBeGreaterThanOrEqual(1)
    expect(wrapper.text()).toContain('Sign In')
  })

  it('calls auth store login on form submission', async () => {
    mockLogin.mockResolvedValue(undefined)
    const wrapper = mount(Login, { global: globalConfig })

    // Access component's reactive form state
    const vm = wrapper.vm as any
    vm.form.username = 'testuser'
    vm.form.password = 'testpass'
    await wrapper.vm.$nextTick()

    // Click the login button (the one with "Sign In" text)
    const loginBtn = wrapper.findAll('[data-test="ElButton"]').find(b => b.text().includes('Sign In'))
    expect(loginBtn).toBeTruthy()
    await loginBtn!.trigger('click')
    await flushPromises()

    expect(mockLogin).toHaveBeenCalledWith('testuser', 'testpass')
  })

  it('shows error when login fails', async () => {
    mockLogin.mockRejectedValue({ response: { data: { detail: 'Invalid credentials' } } })
    const wrapper = mount(Login, { global: globalConfig })

    const vm = wrapper.vm as any
    vm.form.username = 'baduser'
    vm.form.password = 'badpass'
    await wrapper.vm.$nextTick()

    const loginBtn = wrapper.findAll('[data-test="ElButton"]').find(b => b.text().includes('Sign In'))
    await loginBtn!.trigger('click')
    await flushPromises()

    // After failed login, the error ref should be set
    // The component displays the error in a div
    expect(wrapper.html()).toContain('Invalid credentials')
  })
})
