import { createRouter, createWebHistory } from 'vue-router'
import { routes } from './routes'
import { useAuthStore } from '@/stores/auth'
import { getActiveLocale } from '@/i18n/text'

const APP_TITLE = import.meta.env.VITE_APP_TITLE || 'OpenClaw Web'

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  let authEnabled = false
  try {
    authEnabled = await authStore.checkAuthConfig()
  } catch (error) {
    console.error('[Router] checkAuthConfig failed:', error)
    // 认证配置检查失败时，假设认证已禁用，允许访问
    authEnabled = false
  }

  if (!authEnabled) {
    if (to.name === 'Login') {
      next({ name: 'Dashboard' })
      return
    }
    next()
    return
  }

  if (to.meta.public) {
    if (to.name === 'Login' && authStore.isAuthenticated) {
      try {
        const valid = await authStore.checkAuth()
        if (valid) {
          const redirect = typeof to.query.redirect === 'string' ? to.query.redirect : '/'
          next(redirect)
          return
        }
      } catch (error) {
        console.error('[Router] checkAuth failed:', error)
      }
    }
    next()
    return
  }

  if (!authStore.isAuthenticated) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  try {
    const valid = await authStore.checkAuth()
    if (!valid) {
      next({ name: 'Login', query: { redirect: to.fullPath } })
      return
    }
  } catch (error) {
    console.error('[Router] checkAuth failed:', error)
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  next()
})

// Set page title on every navigation
router.afterEach((to) => {
  const titleKey = to.meta.titleKey as string | undefined
  if (titleKey) {
    getActiveLocale()
    // Simple title resolution: use the route name as fallback
    const pageName = String(to.name || titleKey)
    document.title = `${pageName} — ${APP_TITLE}`
  } else {
    document.title = APP_TITLE
  }
})

export default router
