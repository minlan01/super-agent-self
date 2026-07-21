import { defineStore } from 'pinia'
import { authApi } from '../api'
import api from '../api'
import type { AuthResponse } from '../types'

const TOKEN_KEY = 'agent_admin_token'
const USER_KEY = 'agent_admin_user'
const PERMS_KEY = 'agent_admin_perms'

export interface AuthUser {
  id: string
  username: string
  role: string
}

interface SSOProvider {
  provider: string
  display_name: string
  login_url: string
}

function _loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch {
    localStorage.removeItem(key)
    return fallback
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '' as string,
    user: _loadJson<AuthUser | null>(USER_KEY, null),
    permissions: _loadJson<string[]>(PERMS_KEY, []),
    ssoProviders: [] as SSOProvider[],
  }),

  getters: {
    isAuthenticated: (state): boolean => !!state.token,
    isAdmin: (state): boolean => state.user?.role === 'admin',
    hasPermission: (state) => (resource: string, action: string): boolean => {
      if (state.user?.role === 'admin') return true
      const target = `${resource}:${action}`
      return state.permissions.includes(target) || state.permissions.includes(`${resource}:admin`) || state.permissions.includes('system:admin')
    },
  },

  actions: {
    async login(username: string, password: string) {
      const res: AuthResponse = await authApi.login({ username, password })
      this.token = res.data.token
      this.user = res.data.user
      // The backend sets an httpOnly cookie on login response.
      // We still store token + user in localStorage as fallback for
      // environments where cookies are unavailable, and so the axios
      // interceptor can set the Authorization header (backward compat).
      localStorage.setItem(TOKEN_KEY, this.token)
      localStorage.setItem(USER_KEY, JSON.stringify(this.user))
    },

    async logout() {
      // Clear httpOnly cookie on the backend
      try {
        await api.post('/auth/logout')
      } catch {
        // Backend cookie clear is best-effort; proceed with local cleanup.
      }
      this.token = ''
      this.user = null
      this.permissions = []
      this.ssoProviders = []
      // Clear localStorage fallback
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      localStorage.removeItem(PERMS_KEY)
    },

    async validateToken() {
      if (!this.token) return false
      try {
        const res = await authApi.me() as { data?: AuthUser }
        if (res?.data) {
          this.user = res.data
          localStorage.setItem(USER_KEY, JSON.stringify(this.user))
          return true
        }
      } catch {
        this.token = ''
        this.user = null
        this.permissions = []
        localStorage.removeItem(TOKEN_KEY)
        localStorage.removeItem(USER_KEY)
      }
      return false
    },

    async fetchPermissions() {
      try {
        const permResp = await api.get<{ data?: string[] }>(`/rbac/users/${this.user?.id}/permissions`)
        this.permissions = permResp.data?.data || []
        localStorage.setItem(PERMS_KEY, JSON.stringify(this.permissions))
      } catch {
        this.permissions = []
        localStorage.removeItem(PERMS_KEY)
      }
    },

    async fetchSSOProviders() {
      try {
        const resp = await api.get<{ data?: SSOProvider[] }>('/auth/sso/providers')
        this.ssoProviders = resp.data?.data || []
      } catch {
        this.ssoProviders = []
      }
    },

    async handleSsoCallback(code: string) {
      const res = await authApi.exchangeSsoToken(code)
      this.token = res.token
      localStorage.setItem(TOKEN_KEY, this.token)
      // Fetch user info with the new token
      const meRes = await authApi.me() as { data?: AuthUser }
      if (meRes?.data) {
        this.user = meRes.data
        localStorage.setItem(USER_KEY, JSON.stringify(this.user))
      }
    },
  },
})
