import axios from 'axios'
import { ElMessage } from 'element-plus'
import i18n from '../i18n'
import type {
  PaginatedResponse, Task, TaskStep, Skill, Memory, AuditEvent, AuthResponse,
  Approval, CronJob, ChatResponse, ConversationDetail, ConversationListResponse,
  HealthMetrics, ReadinessCheck, NotificationListResponse, UnreadCountResponse,
  AnalyticsOverview, TaskTrendPoint, SkillsPerformanceItem, MemoriesGrowthPoint,
  RecentActivityItem, TaskDAGGraph, Template, SearchResponse,
  RealtimeMetrics, CostSummary, CostTrendPoint, SkillBenchmarkItem, AnomalyAlert,
  RoleWithPermissions, Permission, UserWithRoles,
} from '../types'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  withCredentials: true,
})

// ── Request deduplication ─────────────────────────────────────────────────
// Prevents duplicate in-flight GET requests to the same URL+params.

const pendingRequests = new Map<string, Promise<unknown>>()

function dedupKey(method: string, url: string, params?: Record<string, unknown>): string {
  return `${method}:${url}:${JSON.stringify(params ?? {})}`
}

function dedupedGet<T>(url: string, config?: Record<string, unknown>): Promise<T> {
  const key = dedupKey('GET', url, config?.params as Record<string, unknown>)
  const existing = pendingRequests.get(key)
  if (existing) return existing as Promise<T>

  const promise = api.get(url, config).finally(() => {
    pendingRequests.delete(key)
  }) as Promise<T>
  pendingRequests.set(key, promise)
  return promise
}

// ── Interceptors ──────────────────────────────────────────────────────────

api.interceptors.request.use((config) => {
  // Token is primarily sent via httpOnly cookie (withCredentials: true).
  // Authorization header is kept as backward-compatible fallback for
  // API clients that don't support cookies.
  const token = localStorage.getItem('agent_admin_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.response?.data?.message || error.message

    if (status === 401) {
      // Clear localStorage tokens; the httpOnly cookie is cleared by the
      // backend on logout. Redirect to login page.
      localStorage.removeItem('agent_admin_token')
      localStorage.removeItem('agent_admin_user')
      localStorage.removeItem('agent_admin_perms')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    } else if (status === 403) {
      ElMessage.error(`${i18n.global.t('errors.permissionDenied')}: ${detail}`)
    } else if (status === 404) {
      ElMessage.error(`${i18n.global.t('errors.notFound')}: ${detail}`)
    } else if (status === 422) {
      const errors = error.response?.data?.detail
      if (Array.isArray(errors)) {
        const msg = errors.map((e: any) => e.msg || String(e)).join('; ')
        ElMessage.warning(`${i18n.global.t('errors.validation')}: ${msg}`)
      } else {
        ElMessage.warning(`${i18n.global.t('errors.validation')}: ${detail}`)
      }
    } else if (status === 400) {
      ElMessage.warning(`${i18n.global.t('errors.badRequest')}: ${detail}`)
    } else if (status && status >= 500) {
      ElMessage.error(`${i18n.global.t('errors.serverError')}: ${detail}`)
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error(i18n.global.t('errors.requestTimeout'))
    } else {
      console.error('API Error:', detail)
    }

    return Promise.reject(error)
  }
)

// ── Typed helpers ────────────────────────────────────────────────────────────

function typedGet<T>(url: string, config?: Record<string, unknown>): Promise<T> {
  return dedupedGet<T>(url, config)
}

function typedPost<T>(url: string, data?: unknown, config?: Record<string, unknown>): Promise<T> {
  return api.post(url, data, config) as Promise<T>
}

function typedPut<T>(url: string, data?: unknown, config?: Record<string, unknown>): Promise<T> {
  return api.put(url, data, config) as Promise<T>
}

function typedDelete<T>(url: string, config?: Record<string, unknown>): Promise<T> {
  return api.delete(url, config) as Promise<T>
}

// ── Tasks ──────────────────────────────────────────────────────────────────

export const getTasks = (params?: Record<string, unknown>) => typedGet<PaginatedResponse<Task>>('/tasks', { params })
export const getTask = (id: string) => typedGet<{ data: Task }>(`/tasks/${id}`)
export const createTask = (data: { goal: string; edition?: string }) => typedPost<Task>('/tasks', data)
export const cancelTask = (id: string) => typedPost<Task>(`/tasks/${id}/cancel`)
export const getTaskSteps = (id: string) => typedGet<TaskStep[]>(`/tasks/${id}/steps`)
export const getTaskAudit = (id: string) => typedGet<{ data: AuditEvent[] }>(`/tasks/${id}/audit`)

// ── Memory ─────────────────────────────────────────────────────────────────

export const getMemories = (params?: Record<string, unknown>) => typedGet<{ data: Memory[]; total: number }>('/memory', { params })
export const searchMemories = (params?: Record<string, unknown>) => typedGet<{ data: Memory[]; total: number }>('/memory/search', { params })
export const getMemory = (id: string) => typedGet<{ data: Memory }>(`/memory/${id}`)
export const disableMemory = (id: string) => typedPost<void>(`/memory/${id}/disable`)
export const deleteMemory = (id: string) => typedDelete<void>(`/memory/${id}`)

// ── Skills ─────────────────────────────────────────────────────────────────

export const getSkills = (params?: Record<string, unknown>) => typedGet<{ data: Skill[]; total: number }>('/skills', { params })
export const getSkill = (id: string) => typedGet<{ data: Skill }>(`/skills/${id}`)
export const approveSkill = (id: string) => typedPost<void>(`/skills/${id}/approve`)
export const disableSkill = (id: string) => typedPost<void>(`/skills/${id}/disable`)
export const rollbackSkill = (id: string) => typedPost<void>(`/skills/${id}/rollback`)

// ── Audit ──────────────────────────────────────────────────────────────────

export const getAuditEvents = (params?: Record<string, unknown>) => typedGet<{ data: AuditEvent[] }>('/audit', { params })

// ── Cron ───────────────────────────────────────────────────────────────────

export const cronApi = {
  list: (params?: Record<string, unknown>) => typedGet<CronJob[]>('/cron', { params }),
  create: (data: Record<string, unknown>) => typedPost<CronJob>('/cron', data),
  update: (id: string, data: Record<string, unknown>) => typedPut<CronJob>(`/cron/${id}`, data),
  delete: (id: string) => typedDelete<void>(`/cron/${id}`),
}

// ── Approvals ──────────────────────────────────────────────────────────────

export const getApprovals = (params?: Record<string, unknown>) => typedGet<PaginatedResponse<Approval>>('/approvals', { params })
export const getApproval = (id: string) => typedGet<{ data: Approval }>(`/approvals/${id}`)
export const resolveApproval = (id: string, data: { approved: boolean; approved_by: string; reason?: string }) =>
  typedPost<Approval>(`/approvals/${id}/resolve`, data)
export const batchResolveApprovals = (data: { items: { approval_id: string; approved: boolean; approved_by: string; reason?: string }[] }) =>
  typedPost<{ resolved: number; results: any[] }>('/approvals/batch-resolve', data)

// ── Chat ──────────────────────────────────────────────────────────────────

export const chatApi = {
  send: (data: { message: string; user_id?: string; conversation_id?: string }) =>
    typedPost<ChatResponse>('/chat', data),
  listConversations: (params?: Record<string, unknown>) =>
    typedGet<ConversationListResponse>('/conversations', { params }),
  getConversation: (id: string) =>
    typedGet<ConversationDetail>(`/conversations/${id}`),
  deleteConversation: (id: string) =>
    typedDelete<void>(`/conversations/${id}`),
}

// ── Export (returns Blob for CSV, keep raw api.get for responseType support) ─

export const exportApi = {
  tasks: (format: string) =>
    api.get('/export/tasks', { params: { format }, responseType: format === 'csv' ? 'blob' : 'json' }),
  memories: (format: string) =>
    api.get('/export/memories', { params: { format }, responseType: format === 'csv' ? 'blob' : 'json' }),
  audit: (format: string) =>
    api.get('/export/audit', { params: { format }, responseType: format === 'csv' ? 'blob' : 'json' }),
}

// ── Health ─────────────────────────────────────────────────────────────────

export const getHealth = () => axios.get('/health').then((r) => r.data as HealthMetrics)
export const getReadiness = () => typedGet<ReadinessCheck>('/health/ready')
export const getMetrics = () => typedGet<HealthMetrics>('/health/metrics')

// ── Auth ──────────────────────────────────────────────────────────────────

export const authApi = {
  login: (data: { username: string; password: string }) =>
    typedPost<AuthResponse>('/auth/login', data),
  register: (data: Record<string, unknown>) =>
    typedPost<AuthResponse>('/auth/register', data),
  me: () => typedGet<AuthResponse['data']>('/auth/me'),
  exchangeSsoToken: (code: string) =>
    typedPost<{ token: string }>('/auth/sso/token', { code }),
}

// ── Analytics ────────────────────────────────────────────────────────────

export const analyticsApi = {
  overview: () => typedGet<AnalyticsOverview>('/analytics/overview'),
  taskTrend: (days: number) => typedGet<{ trend: TaskTrendPoint[] }>('/analytics/tasks/trend', { params: { days } }),
  statusDistribution: () => typedGet<{ distribution: Record<string, number> }>('/analytics/tasks/status-distribution'),
  skillsPerformance: () => typedGet<{ skills: SkillsPerformanceItem[] }>('/analytics/skills/performance'),
  memoriesGrowth: (days: number) => typedGet<{ growth: MemoriesGrowthPoint[] }>('/analytics/memories/growth', { params: { days } }),
  recentActivity: (limit: number) => typedGet<{ events: RecentActivityItem[] }>('/analytics/activity/recent', { params: { limit } }),
  realtimeMetrics: () => typedGet<RealtimeMetrics>('/analytics/execution/realtime'),
  costSummary: (days: number) => typedGet<CostSummary>('/analytics/costs/summary', { params: { days } }),
  costTrend: (days: number) => typedGet<{ days: number; trend: CostTrendPoint[] }>('/analytics/costs/trend', { params: { days } }),
  skillBenchmark: (topN?: number) => typedGet<{ skills: SkillBenchmarkItem[] }>('/analytics/skills/benchmark', { params: topN ? { top_n: topN } : {} }),
  anomalies: () => typedGet<{ alerts: AnomalyAlert[]; checked_at: string }>('/analytics/anomalies'),
}

// ── Notifications ────────────────────────────────────────────────────────

export const notificationApi = {
  list: (limit?: number) => typedGet<NotificationListResponse>('/notifications', { params: limit ? { limit } : {} }),
  unreadCount: () => typedGet<UnreadCountResponse>('/notifications/unread'),
  markRead: (id: string) => typedPost<void>(`/notifications/${id}/read`),
  markAllRead: () => typedPost<void>('/notifications/read-all'),
  clear: () => typedDelete<void>('/notifications'),
}

// ── Search ──────────────────────────────────────────────────────────────

export const searchApi = {
  query: (params: { q: string; types?: string; limit?: number }) =>
    typedGet<SearchResponse>('/search', { params }),
}

// ── Task Templates ────────────────────────────────────────────────────────

export const templateApi = {
  list: (params?: Record<string, unknown>) => typedGet<{ data: Template[]; total: number }>('/templates', { params }),
  get: (id: string) => typedGet<{ data: Template }>(`/templates/${id}`),
  create: (data: Record<string, unknown>) => typedPost<Template>('/templates', data),
  update: (id: string, data: Record<string, unknown>) => typedPut<Template>(`/templates/${id}`, data),
  delete: (id: string) => typedDelete<void>(`/templates/${id}`),
  apply: (id: string, data: { params: Record<string, string>; user_id?: string }) =>
    typedPost<Task>(`/templates/${id}/apply`, data),
}

// ── Task DAG ────────────────────────────────────────────────────────────────

export const dagApi = {
  getGraph: () => typedGet<TaskDAGGraph>('/tasks/dag'),
}

// ── Plugins ────────────────────────────────────────────────────────────

export const pluginApi = {
  list: () => typedGet<{ plugins: Array<{ name: string; status: string; version: string; description: string }> }>('/plugins/list'),
  discover: () => typedGet<{ plugins: string[] }>('/plugins/discover'),
  activate: (name: string) => typedPost<{ success: boolean; message: string }>(`/plugins/${name}/activate`),
  deactivate: (name: string) => typedPost<{ success: boolean; message: string }>(`/plugins/${name}/deactivate`),
  reload: (name: string) => typedPost<{ success: boolean; message: string }>(`/plugins/${name}/reload`),
}

// ── Agents ────────────────────────────────────────────────────────────

export const agentApi = {
  status: () => typedGet<{ agents: Array<{ id: string; status: string; last_active: string }> }>('/agents/status'),
  messages: (agentId: string) => typedGet<{ messages: Array<{ from: string; to: string; content: string; timestamp: string }> }>(`/agents/${agentId}/messages`),
  proposeConsensus: (data: { question: string; options: string[] }) =>
    typedPost<{ proposal_id: string; status: string }>('/agents/consensus/propose', data),
  castVote: (data: { proposal_id: string; choice: string }) =>
    typedPost<{ success: boolean }>('/agents/consensus/vote', data),
  consensusResult: (proposalId: string) =>
    typedGet<{ proposal_id: string; status: string; result: Record<string, unknown> }>(`/agents/consensus/${proposalId}`),
}

// ── Desktop ────────────────────────────────────────────────────────────

interface DesktopListFilesResp { success: boolean; data: { path: string; entries: Array<{ name: string; type: string; size: number | null }> } }
interface DesktopReadFileResp { success: boolean; data: { path: string; content: string; size: number } }
interface DesktopWriteFileResp { success: boolean; data: { path: string; written: number } }
interface DesktopListWindowsResp { success: boolean; data: Array<Record<string, unknown>> }
interface DesktopScreenshotResp { success: boolean; data: Record<string, unknown> }

export const desktopApi = {
  listFiles: (path?: string) => typedPost<DesktopListFilesResp>('/desktop/files', { action: 'list', path: path || '.' }),
  readFile: (path: string) => typedPost<DesktopReadFileResp>('/desktop/files', { action: 'read', path }),
  writeFile: (path: string, content: string) => typedPost<DesktopWriteFileResp>('/desktop/files', { action: 'write', path, content }),
  listWindows: () => typedPost<DesktopListWindowsResp>('/desktop/windows', { action: 'list' }),
  screenshot: () => typedGet<DesktopScreenshotResp>('/desktop/screenshot'),
}

// ── Vision ────────────────────────────────────────────────────────────

export const visionApi = {
  analyze: (imageBase64: string, prompt?: string) =>
    typedPost<{ success: boolean; data: { description: string } }>('/vision/analyze', { image: imageBase64, prompt: prompt || 'Describe this image in detail.' }),
  ocr: (imageBase64: string) =>
    typedPost<{ success: boolean; data: { text: string; confidence: number } }>('/vision/ocr', { image: imageBase64 }),
}

// ── RBAC ────────────────────────────────────────────────────────────────

export const rbacApi = {
  roles: (params?: Record<string, unknown>) => typedGet<RoleWithPermissions[]>('/rbac/roles', { params }),
  permissions: () => typedGet<Permission[]>('/rbac/permissions'),
  users: () => typedGet<UserWithRoles[]>('/rbac/users'),
  createRole: (data: Record<string, unknown>) => typedPost<RoleWithPermissions>('/rbac/roles', data),
  updateRole: (id: string, data: Record<string, unknown>) => typedPut<RoleWithPermissions>(`/rbac/roles/${id}`, data),
  deleteRole: (id: string) => typedDelete<void>(`/rbac/roles/${id}`),
  assignRoles: (data: { user_id: string; role_ids: string[] }) => typedPost<void>('/rbac/users/assign', data),
  revokeRoles: (data: { user_id: string; role_ids: string[] }) => typedPost<void>('/rbac/users/revoke', data),
}

// ── Voice ────────────────────────────────────────────────────────────

export const voiceApi = {
  stt: async (file: File): Promise<{ success: boolean; data: { transcript: string } }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post('/voice/stt', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },
  ttsAudio: (text: string, voice = 'default') =>
    `${api.defaults.baseURL}/voice/tts/audio?text=${encodeURIComponent(text)}&voice=${voice}`,
  command: (transcript: string) =>
    api.post('/voice/command', { transcript }).then(r => r.data),
}

export default api
