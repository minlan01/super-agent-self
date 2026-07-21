/**
 * myself-agent API 客户端适配器
 *
 * myself-agent 响应格式: { success: boolean, data?: T, message?: string }
 * 前端通过 Vite 代理访问: /myself-agent/* → localhost:8000/api/v1/*
 */

const BASE = '/myself-agent'

// ── 通用类型 ────────────────────────────────────────────────────────────────

export interface MyselfResponse<T = unknown> {
  success: boolean
  data?: T
  message?: string
}

export interface MyselfTask {
  id: string
  title: string
  description?: string
  status: string
  priority?: number
  created_at?: string
  updated_at?: string
  completed_at?: string
  template_id?: string
  tags?: string[]
  [key: string]: unknown
}

export interface MyselfSkill {
  id: string
  name: string
  description?: string
  category?: string
  version?: string
  enabled?: boolean
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export interface MyselfMemory {
  id: string
  key: string
  value: unknown
  is_active?: boolean
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export interface MyselfCronJob {
  id: string
  name: string
  schedule: string
  enabled: boolean
  last_run?: string
  next_run?: string
  task_template_id?: string
  [key: string]: unknown
}

export interface MyselfConversation {
  id: string
  title?: string
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export interface MyselfAuditEntry {
  id: string
  action: string
  entity_type?: string
  entity_id?: string
  timestamp?: string
  [key: string]: unknown
}

export interface MyselfNotification {
  id: string
  title: string
  body?: string
  read: boolean
  created_at?: string
}

export interface MyselfTemplate {
  id: string
  name: string
  description?: string
  category?: string
  [key: string]: unknown
}

export interface MyselfHealthStatus {
  ready?: boolean
  checks?: Record<string, string>
  version?: string
  edition?: string
}

export interface MyselfMetrics {
  tasks?: Record<string, number>
  total_tasks?: number
  memories?: { total: number; active: number }
  uptime_seconds?: number
  version?: string
}

export interface MyselfAnalyticsOverview {
  [key: string]: unknown
}

// ── 通用请求函数 ────────────────────────────────────────────────────────────

async function request<T>(url: string, options?: RequestInit): Promise<MyselfResponse<T>> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  return resp.json()
}

async function get<T>(path: string): Promise<MyselfResponse<T>> {
  return request<T>(`${BASE}${path}`)
}

async function post<T>(path: string, body?: unknown): Promise<MyselfResponse<T>> {
  return request<T>(`${BASE}${path}`, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

async function put<T>(path: string, body?: unknown): Promise<MyselfResponse<T>> {
  return request<T>(`${BASE}${path}`, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
}

async function del<T>(path: string): Promise<MyselfResponse<T>> {
  return request<T>(`${BASE}${path}`, { method: 'DELETE' })
}

// ── Health ───────────────────────────────────────────────────────────────────

export const myselfHealth = {
  /** 顶层健康检查 GET /health (直接路径) */
  check: () => get<MyselfHealthStatus>('/health'),
  /** 深度就绪探测 GET /health/ready */
  ready: () => get<MyselfHealthStatus>('/health/ready'),
  /** 平台指标 GET /health/metrics */
  metrics: () => get<MyselfMetrics>('/health/metrics'),
}

// ── Tasks ────────────────────────────────────────────────────────────────────

export const myselfTasks = {
  list: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return get<MyselfTask[]>(`/tasks${qs}`)
  },
  get: (id: string) => get<MyselfTask>(`/tasks/${id}`),
  create: (data: Partial<MyselfTask>) => post<MyselfTask>('/tasks', data),
  update: (id: string, data: Partial<MyselfTask>) => put<MyselfTask>(`/tasks/${id}`, data),
  cancel: (id: string) => post<MyselfTask>(`/tasks/${id}/cancel`),
  /** 任务依赖关系 */
  dependencies: (id: string) => get<unknown>(`/tasks/${id}/dependencies`),
}

// ── Memory ───────────────────────────────────────────────────────────────────

export const myselfMemory = {
  list: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return get<MyselfMemory[]>(`/memory${qs}`)
  },
  get: (key: string) => get<MyselfMemory>(`/memory/${encodeURIComponent(key)}`),
  set: (data: { key: string; value: unknown }) => post<MyselfMemory>('/memory', data),
  delete: (key: string) => del<MyselfMemory>(`/memory/${encodeURIComponent(key)}`),
}

// ── Skills ───────────────────────────────────────────────────────────────────

export const myselfSkills = {
  list: () => get<MyselfSkill[]>('/skills'),
  get: (id: string) => get<MyselfSkill>(`/skills/${id}`),
  execute: (id: string, params?: unknown) => post<unknown>(`/skills/${id}/execute`, params),
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export const myselfChat = {
  send: (data: { message: string; conversation_id?: string; context?: unknown }) =>
    post<unknown>('/chat', data),
}

// ── Conversations ────────────────────────────────────────────────────────────

export const myselfConversations = {
  list: () => get<MyselfConversation[]>('/conversations'),
  get: (id: string) => get<MyselfConversation>(`/conversations/${id}`),
  delete: (id: string) => del(`/conversations/${id}`),
}

// ── Cron ─────────────────────────────────────────────────────────────────────

export const myselfCron = {
  list: () => get<MyselfCronJob[]>('/cron'),
  get: (id: string) => get<MyselfCronJob>(`/cron/${id}`),
  create: (data: Partial<MyselfCronJob>) => post<MyselfCronJob>('/cron', data),
  update: (id: string, data: Partial<MyselfCronJob>) => put<MyselfCronJob>(`/cron/${id}`, data),
  delete: (id: string) => del(`/cron/${id}`),
  toggle: (id: string, enabled: boolean) => post(`/cron/${id}/toggle`, { enabled }),
}

// ── Analytics ────────────────────────────────────────────────────────────────

export const myselfAnalytics = {
  overview: () => get<MyselfAnalyticsOverview>('/analytics'),
}

// ── Audit ────────────────────────────────────────────────────────────────────

export const myselfAudit = {
  list: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : ''
    return get<MyselfAuditEntry[]>(`/audit${qs}`)
  },
}

// ── Templates ────────────────────────────────────────────────────────────────

export const myselfTemplates = {
  list: () => get<MyselfTemplate[]>('/templates'),
  get: (id: string) => get<MyselfTemplate>(`/templates/${id}`),
}

// ── Search ───────────────────────────────────────────────────────────────────

export const myselfSearch = {
  query: (q: string, scope?: string) => {
    const params = new URLSearchParams({ q })
    if (scope) params.set('scope', scope)
    return get<unknown[]>(`/search?${params.toString()}`)
  },
}

// ── Notifications ────────────────────────────────────────────────────────────

export const myselfNotifications = {
  list: () => get<MyselfNotification[]>('/notifications'),
  markRead: (id: string) => post(`/notifications/${id}/read`),
  markAllRead: () => post('/notifications/read-all'),
}

// ── Marketplace ──────────────────────────────────────────────────────────────

export const myselfMarketplace = {
  list: () => get<unknown[]>('/marketplace'),
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export const myselfAuth = {
  login: (credentials: { username: string; password: string }) => post<{ token: string }>('/auth/login', credentials),
}

// ── 聚合连接检查 ────────────────────────────────────────────────────────────

export async function checkMyselfConnection(): Promise<{ connected: boolean; version?: string; error?: string }> {
  try {
    const { success, data } = await myselfHealth.check()
    if (success && data) {
      return { connected: true, version: (data as MyselfHealthStatus).version }
    }
    return { connected: false, error: 'Health check returned non-success' }
  } catch (err) {
    return { connected: false, error: String(err) }
  }
}
