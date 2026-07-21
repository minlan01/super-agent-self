import axios from 'axios'
import { ElMessage } from 'element-plus'
import i18n from '../i18n'
import type { Agent, AgentCapability, Scenario, MonitoringOverview, PaginatedResponse } from '../types'

// ── Agent Control API client (more_agents backend, port 8900) ────────────

const agentApi = axios.create({
  baseURL: '/agent-api',
  timeout: 30000,
})

// Shared auth interceptor
agentApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('agent_admin_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Shared error interceptor (no 401 redirect — agent backend has no auth yet)
agentApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail || error.response?.data?.message || error.message

    if (status === 404) {
      ElMessage.error(`${i18n.global.t('errors.notFound')}: ${detail}`)
    } else if (status === 400) {
      ElMessage.warning(`${i18n.global.t('errors.badRequest')}: ${detail}`)
    } else if (status && status >= 500) {
      ElMessage.error(`${i18n.global.t('errors.serverError')}: ${detail}`)
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error(i18n.global.t('errors.requestTimeout'))
    } else {
      console.error('Agent API Error:', detail)
    }

    return Promise.reject(error)
  }
)

// ── Typed helpers ────────────────────────────────────────────────────────

function typedGet<T>(url: string, config?: Record<string, unknown>): Promise<T> {
  return agentApi.get(url, config) as Promise<T>
}

function typedPost<T>(url: string, data?: unknown): Promise<T> {
  return agentApi.post(url, data) as Promise<T>
}

function typedPatch<T>(url: string, data?: unknown): Promise<T> {
  return agentApi.patch(url, data) as Promise<T>
}

function typedDelete<T>(url: string): Promise<T> {
  return agentApi.delete(url) as Promise<T>
}

// ── Agents ───────────────────────────────────────────────────────────────

export const agentsApi = {
  list: (params?: Record<string, unknown>) =>
    typedGet<PaginatedResponse<Agent>>('/agents', { params }),
  get: (id: string) =>
    typedGet<Agent>(`/agents/${id}`),
  create: (data: {
    agent_id: string
    name: string
    agent_type?: string
    skill_tags?: string[]
    max_concurrent_tasks?: number
    description?: string
    emoji?: string
    theme_color?: string
  }) => typedPost<Agent>('/agents', data),
  update: (id: string, data: Record<string, unknown>) =>
    typedPatch<Agent>(`/agents/${id}`, data),
  delete: (id: string) =>
    typedDelete<void>(`/agents/${id}`),
  getTasks: (id: string) =>
    typedGet<{ items: unknown[] }>(`/agents/${id}/tasks`),
  pause: (id: string) =>
    typedPost<{ status: string }>(`/agents/${id}/pause`),
  resume: (id: string) =>
    typedPost<{ status: string }>(`/agents/${id}/resume`),
  shutdown: (id: string) =>
    typedPost<{ status: string }>(`/agents/${id}/shutdown`),
}

// ── Agent Tasks ──────────────────────────────────────────────────────────

export interface AgentTask {
  id: string
  title: string
  description: string
  state: 'pending' | 'queued' | 'assigned' | 'running' | 'completed' | 'failed' | 'retrying' | 'cancelled'
  priority: number
  agent_id: string | null
  progress: number
  created_at: string
  updated_at: string
}

export const agentTasksApi = {
  list: (params?: Record<string, unknown>) =>
    typedGet<PaginatedResponse<AgentTask>>('/tasks', { params }),
  get: (id: string) =>
    typedGet<AgentTask>(`/tasks/${id}`),
  create: (data: { title: string; description?: string; priority?: number; agent_id?: string }) =>
    typedPost<AgentTask>('/tasks', data),
  delete: (id: string) =>
    typedDelete<void>(`/tasks/${id}`),
  pause: (id: string) =>
    typedPost<{ state: string }>(`/tasks/${id}/pause`),
  resume: (id: string) =>
    typedPost<{ state: string }>(`/tasks/${id}/resume`),
  cancel: (id: string) =>
    typedPost<{ state: string }>(`/tasks/${id}/cancel`),
  retry: (id: string) =>
    typedPost<AgentTask>(`/tasks/${id}/retry`),
  reassign: (id: string, target_agent_id: string) =>
    typedPost<AgentTask>(`/tasks/${id}/reassign`, { target_agent_id }),
  getLogs: (id: string) =>
    typedGet<{ items: unknown[] }>(`/tasks/${id}/logs`),
  reportProgress: (id: string, data: { step: string; progress: number; detail?: string }) =>
    typedPost<{ status: string }>(`/tasks/${id}/progress`, data),
}

// ── Scenarios ────────────────────────────────────────────────────────────

export const scenariosApi = {
  list: (params?: Record<string, unknown>) =>
    typedGet<PaginatedResponse<Scenario>>('/scenarios', { params }),
  get: (id: string) =>
    typedGet<Scenario>(`/scenarios/${id}`),
  create: (data: {
    name: string
    description?: string
    agent_selection_mode?: string
    coordinator_id?: string
    members?: { agent_id: string; role?: string }[]
    tasks?: { title: string; description?: string; assigned_agents?: string[]; priority?: string }[]
  }) => typedPost<Scenario>('/scenarios', data),
  activate: (id: string) =>
    typedPost<Scenario>(`/scenarios/${id}/activate`),
  complete: (id: string) =>
    typedPost<Scenario>(`/scenarios/${id}/complete`),
  addTask: (id: string, data: { title: string; description?: string; assigned_agents?: string[] }) =>
    typedPost<unknown>(`/scenarios/${id}/tasks`, data),
  executeTask: (scenarioId: string, taskId: string) =>
    typedPost<unknown>(`/scenarios/${scenarioId}/tasks/${taskId}/execute`),
}

// ── Monitoring ───────────────────────────────────────────────────────────

export const monitoringApi = {
  overview: () =>
    typedGet<MonitoringOverview>('/monitoring/overview'),
  heartbeat: (agentId: string) =>
    typedGet<{ agent_id: string; last_heartbeat: string; status: string }>(`/monitoring/agents/${agentId}/heartbeat`),
  errors: (params?: Record<string, unknown>) =>
    typedGet<PaginatedResponse<{ id: number; level: string; message: string; agent_id: string | null; created_at: string }>>('/monitoring/errors', { params }),
  metrics: () =>
    typedGet<{ success_rate: number; agent_utilization: number; avg_task_duration: number }>('/monitoring/metrics'),
}

// ── SSE Event Stream ─────────────────────────────────────────────────────

export function createEventSourceURL(types?: string[]): string {
  let url = '/agent-api/stream/events'
  if (types?.length) {
    url += `?types=${types.join(',')}`
  }
  return url
}

export default agentApi
