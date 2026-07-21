import { describe, it, expect, beforeEach } from 'vitest'
import { createRouter, createMemoryHistory, type RouteRecordRaw, type Router } from 'vue-router'

/**
 * Recreates the exact guard logic from router/index.ts:
 *
 *   router.beforeEach((to) => {
 *     const token = localStorage.getItem('agent_admin_token')
 *     if (!to.meta.public && !token && to.path !== '/login') {
 *       return { path: '/login' }
 *     }
 *     if (to.path === '/login' && token) {
 *       return { path: '/dashboard' }
 *     }
 *   })
 *
 * We do NOT import the real router to avoid side effects.
 * Instead we create a minimal router with matching routes and the same guard.
 */
function createTestRouter(): Router {
  const routes: RouteRecordRaw[] = [
    {
      path: '/login',
      name: 'Login',
      meta: { public: true },
      component: { template: '<div>login</div>' },
    },
    {
      path: '/register',
      name: 'Register',
      meta: { public: true },
      component: { template: '<div>register</div>' },
    },
    {
      path: '/',
      redirect: '/dashboard',
      component: { template: '<div>layout<router-view /></div>' },
      children: [
        { path: 'dashboard', name: 'Dashboard', component: { template: '<div>dashboard</div>' } },
        { path: 'tasks', name: 'TaskList', component: { template: '<div>tasks</div>' } },
        { path: 'tasks/:id', name: 'TaskDetail', component: { template: '<div>task-detail</div>' }, props: true },
        { path: 'audit', name: 'AuditLog', component: { template: '<div>audit</div>' } },
        { path: 'memory', name: 'MemoryList', component: { template: '<div>memory</div>' } },
        { path: 'skills', name: 'SkillList', component: { template: '<div>skills</div>' } },
        { path: 'skills/:id', name: 'SkillDetail', component: { template: '<div>skill-detail</div>' }, props: true },
        { path: 'cron', name: 'CronList', component: { template: '<div>cron</div>' } },
        { path: 'approvals', name: 'ApprovalList', component: { template: '<div>approvals</div>' } },
        { path: 'chat', name: 'ChatView', component: { template: '<div>chat</div>' } },
        { path: 'conversations', name: 'ConversationList', component: { template: '<div>conversations</div>' } },
        { path: 'export', name: 'ExportView', component: { template: '<div>export</div>' } },
        { path: 'health', name: 'HealthView', component: { template: '<div>health</div>' } },
        { path: 'analytics', name: 'AnalyticsView', component: { template: '<div>analytics</div>' } },
        { path: 'task-dag', name: 'TaskDAG', component: { template: '<div>task-dag</div>' } },
        { path: 'templates', name: 'TemplateList', component: { template: '<div>templates</div>' } },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: { template: '<div>404</div>' },
    },
  ]

  const router = createRouter({
    history: createMemoryHistory(),
    routes,
  })

  // Apply the exact same guard logic as the production router
  router.beforeEach((to) => {
    const token = localStorage.getItem('agent_admin_token')
    if (!to.meta.public && !token && to.path !== '/login') {
      return { path: '/login' }
    }
    if (to.path === '/login' && token) {
      return { path: '/dashboard' }
    }
  })

  return router
}

/**
 * Helper: push a path and wait for navigation to settle.
 * Returns the final resolved route.
 */
async function navigateTo(router: Router, path: string) {
  await router.push(path)
  return router.currentRoute.value
}

describe('Router Guards', () => {
  let router: Router

  beforeEach(() => {
    localStorage.clear()
    router = createTestRouter()
  })

  // ─── Unauthenticated access ────────────────────────────────────────

  describe('unauthenticated access', () => {
    it('redirects /dashboard to /login when no token', async () => {
      const route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/login')
    })

    it('redirects /tasks to /login when no token', async () => {
      const route = await navigateTo(router, '/tasks')
      expect(route.path).toBe('/login')
    })

    it('redirects /skills to /login when no token', async () => {
      const route = await navigateTo(router, '/skills')
      expect(route.path).toBe('/login')
    })

    it('redirects /audit to /login when no token', async () => {
      const route = await navigateTo(router, '/audit')
      expect(route.path).toBe('/login')
    })

    it('redirects /memory to /login when no token', async () => {
      const route = await navigateTo(router, '/memory')
      expect(route.path).toBe('/login')
    })

    it('redirects /cron to /login when no token', async () => {
      const route = await navigateTo(router, '/cron')
      expect(route.path).toBe('/login')
    })

    it('redirects /chat to /login when no token', async () => {
      const route = await navigateTo(router, '/chat')
      expect(route.path).toBe('/login')
    })

    it('redirects /conversations to /login when no token', async () => {
      const route = await navigateTo(router, '/conversations')
      expect(route.path).toBe('/login')
    })

    it('redirects /analytics to /login when no token', async () => {
      const route = await navigateTo(router, '/analytics')
      expect(route.path).toBe('/login')
    })

    it('redirects /task-dag to /login when no token', async () => {
      const route = await navigateTo(router, '/task-dag')
      expect(route.path).toBe('/login')
    })

    it('redirects /templates to /login when no token', async () => {
      const route = await navigateTo(router, '/templates')
      expect(route.path).toBe('/login')
    })

    it('redirects /health to /login when no token', async () => {
      const route = await navigateTo(router, '/health')
      expect(route.path).toBe('/login')
    })

    it('redirects /export to /login when no token', async () => {
      const route = await navigateTo(router, '/export')
      expect(route.path).toBe('/login')
    })

    it('redirects /approvals to /login when no token', async () => {
      const route = await navigateTo(router, '/approvals')
      expect(route.path).toBe('/login')
    })
  })

  // ─── Authenticated access ──────────────────────────────────────────

  describe('authenticated access', () => {
    beforeEach(() => {
      localStorage.setItem('agent_admin_token', 'valid-test-token')
    })

    it('allows access to /dashboard with token', async () => {
      const route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/dashboard')
    })

    it('allows access to /tasks with token', async () => {
      const route = await navigateTo(router, '/tasks')
      expect(route.path).toBe('/tasks')
    })

    it('allows access to /skills with token', async () => {
      const route = await navigateTo(router, '/skills')
      expect(route.path).toBe('/skills')
    })

    it('allows access to /tasks/123 with token', async () => {
      const route = await navigateTo(router, '/tasks/123')
      expect(route.path).toBe('/tasks/123')
    })

    it('allows access to /skills/42 with token', async () => {
      const route = await navigateTo(router, '/skills/42')
      expect(route.path).toBe('/skills/42')
    })

    it('allows access to /audit with token', async () => {
      const route = await navigateTo(router, '/audit')
      expect(route.path).toBe('/audit')
    })

    it('allows access to /cron with token', async () => {
      const route = await navigateTo(router, '/cron')
      expect(route.path).toBe('/cron')
    })

    it('allows access to /chat with token', async () => {
      const route = await navigateTo(router, '/chat')
      expect(route.path).toBe('/chat')
    })

    it('redirects /login to /dashboard when already authenticated', async () => {
      const route = await navigateTo(router, '/login')
      expect(route.path).toBe('/dashboard')
    })
  })

  // ─── Public routes ─────────────────────────────────────────────────

  describe('public routes', () => {
    it('allows access to /login without token', async () => {
      const route = await navigateTo(router, '/login')
      expect(route.path).toBe('/login')
    })

    it('allows access to /register without token', async () => {
      const route = await navigateTo(router, '/register')
      expect(route.path).toBe('/register')
    })

    it('allows access to /register with token (no redirect for register)', async () => {
      localStorage.setItem('agent_admin_token', 'some-token')
      const route = await navigateTo(router, '/register')
      // The guard only redirects /login when authenticated, not /register
      expect(route.path).toBe('/register')
    })
  })

  // ─── Root path redirect ────────────────────────────────────────────

  describe('root path redirect', () => {
    it('redirects / to /login when no token (via /dashboard redirect chain)', async () => {
      const route = await navigateTo(router, '/')
      // / redirects to /dashboard (route config), then guard redirects to /login
      expect(route.path).toBe('/login')
    })

    it('redirects / to /dashboard when authenticated', async () => {
      localStorage.setItem('agent_admin_token', 'token')
      const route = await navigateTo(router, '/')
      expect(route.path).toBe('/dashboard')
    })
  })

  // ─── Edge cases ────────────────────────────────────────────────────

  describe('edge cases', () => {
    it('treats empty string token as unauthenticated', async () => {
      localStorage.setItem('agent_admin_token', '')
      const route = await navigateTo(router, '/dashboard')
      // Empty string is falsy, so guard should redirect to /login
      expect(route.path).toBe('/login')
    })

    it('treats whitespace-only token as authenticated (non-empty string)', async () => {
      localStorage.setItem('agent_admin_token', '   ')
      const route = await navigateTo(router, '/dashboard')
      // '   ' is truthy — the guard does not trim, so access is granted
      expect(route.path).toBe('/dashboard')
    })

    it('allows access with any non-empty token (no client-side validation)', async () => {
      localStorage.setItem('agent_admin_token', 'fake-token-12345')
      const route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/dashboard')
    })

    it('redirects 404 catch-all to /login when no token', async () => {
      const route = await navigateTo(router, '/nonexistent-page')
      expect(route.path).toBe('/login')
    })

    it('allows 404 catch-all route with token', async () => {
      localStorage.setItem('agent_admin_token', 'token')
      const route = await navigateTo(router, '/nonexistent-page')
      expect(route.path).toBe('/nonexistent-page')
    })
  })

  // ─── Token lifecycle ───────────────────────────────────────────────

  describe('token lifecycle', () => {
    it('loses access after token is removed from localStorage', async () => {
      // First, verify access with token
      localStorage.setItem('agent_admin_token', 'token')
      let route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/dashboard')

      // Remove token and create a fresh router to test
      localStorage.removeItem('agent_admin_token')
      router = createTestRouter()
      route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/login')
    })

    it('gains access after token is set in localStorage', async () => {
      // First, verify redirect without token
      let route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/login')

      // Set token and create a fresh router
      localStorage.setItem('agent_admin_token', 'new-token')
      router = createTestRouter()
      route = await navigateTo(router, '/dashboard')
      expect(route.path).toBe('/dashboard')
    })

    it('login page becomes inaccessible after setting token', async () => {
      // Without token, /login is accessible
      let route = await navigateTo(router, '/login')
      expect(route.path).toBe('/login')

      // After setting token, /login redirects to /dashboard
      localStorage.setItem('agent_admin_token', 'token')
      router = createTestRouter()
      route = await navigateTo(router, '/login')
      expect(route.path).toBe('/dashboard')
    })
  })
})
