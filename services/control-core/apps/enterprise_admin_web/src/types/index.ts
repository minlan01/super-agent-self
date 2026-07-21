/** Shared TypeScript interfaces for API responses. */

// ── Task ──────────────────────────────────────────────────────────────────

export interface Task {
  id: string
  user_id: string
  edition: string
  goal: string
  status: TaskStatus
  risk_level: RiskLevel | null
  result: string | null
  error: string | null
  created_at: string
  updated_at: string
  steps: TaskStep[]
}

export type TaskStatus = 'pending' | 'planning' | 'awaiting_approval' | 'executing' | 'completed' | 'failed' | 'cancelled'

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export interface TaskStep {
  id: string
  task_id: string
  step_order: number
  tool_name: string
  args: Record<string, unknown> | null
  risk_level: RiskLevel
  requires_approval: boolean
  status: StepStatus
  capability_token_hash: string | null
  result: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export type StepStatus = 'pending' | 'policy_check' | 'approved' | 'rejected' | 'executing' | 'completed' | 'failed' | 'skipped'

// ── Audit ─────────────────────────────────────────────────────────────────

export interface AuditEvent {
  id: string
  task_id: string | null
  step_id: string | null
  edition: string | null
  event_type: AuditEventType
  actor: string
  detail: Record<string, unknown> | null
  created_at: string
}

export type AuditEventType =
  | 'task_created' | 'plan_generated' | 'policy_check' | 'policy_approved' | 'policy_rejected'
  | 'step_executing' | 'step_completed' | 'step_failed' | 'task_completed' | 'task_failed'
  | 'task_cancelled' | 'memory_written' | 'skill_extracted' | 'skill_approved'
  | 'approval_requested' | 'approval_granted' | 'approval_rejected'
  | 'role_created' | 'role_updated' | 'role_deleted'
  | 'permission_granted' | 'permission_revoked'
  | 'role_assigned' | 'role_revoked'
  | 'sso_login' | 'sso_user_created'

// ── Memory ────────────────────────────────────────────────────────────────

export interface Memory {
  id: string
  user_id: string
  edition: string
  memory_type: MemoryType
  title: string
  summary: string
  content: Record<string, unknown> | null
  content_hash: string | null
  importance_score: number
  confidence_score: number
  source_task_id: string | null
  is_active: boolean
  expires_at: string | null
  created_at: string
  updated_at: string
}

export type MemoryType =
  | 'execution_experience' | 'workflow_pattern' | 'domain_knowledge' | 'error_solution'
  | 'user_preference' | 'personal_project' | 'file_knowledge' | 'reminder' | 'daily_context'

// ── Skill ─────────────────────────────────────────────────────────────────

export interface Skill {
  id: string
  edition: string
  name: string
  version: number
  status: SkillStatus
  definition: Record<string, unknown>
  description: string | null
  success_rate: number
  total_runs: number
  source_task_id: string | null
  created_at: string
  updated_at: string
}

export type SkillStatus = 'candidate' | 'stable' | 'disabled' | 'deprecated'

export interface SkillRun {
  id: string
  skill_id: string
  task_id: string
  success: boolean
  execution_time: number | null
  estimated_cost_usd: number | null
  metrics: Record<string, unknown> | null
  error: string | null
  created_at: string
}

// ── Approval ──────────────────────────────────────────────────────────────

export interface Approval {
  id: string
  edition: string
  approval_type: ApprovalType
  target_id: string
  status: ApprovalStatus
  requested_by: string
  approved_by: string | null
  reason: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export type ApprovalType = 'skill' | 'high_risk_step'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

// ── Pagination ────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  total: number
  items: T[]
  page: number
  page_size: number
}

// ── Chat & Conversations ──────────────────────────────────────────────────

export interface ChatRequest {
  message: string
  user_id?: string
  conversation_id?: string
}

export interface ChatResponse {
  reply: string
  task_id?: string
  action: string
  conversation_id: string
}

export interface Conversation {
  id: string
  user_id: string
  title?: string
  edition: string
  created_at?: string
}

export interface ConversationMessage {
  id: string
  role: string
  content: string
  created_at?: string
}

export interface ConversationDetail {
  conversation: Conversation
  messages: ConversationMessage[]
}

export interface ConversationListResponse {
  success: boolean
  data: Conversation[]
  count: number
}

// ── Auth ──────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string
  password: string
}

export interface AuthResponse {
  success: boolean
  data: {
    token: string
    user: { id: string; username: string; role: string }
  }
}

// ── Health & Metrics ──────────────────────────────────────────────────────

export interface HealthMetrics {
  tasks: Record<string, number>
  total_tasks: number
  memories: { total: number; active: number }
  uptime_seconds: number
  version: string
}

export interface ReadinessCheck {
  ready: boolean
  checks: Record<string, string>
}

// ── Notifications ────────────────────────────────────────────────────────

export type NotificationType = 'task_completed' | 'task_failed' | 'approval_requested' | 'system_warning' | 'info'

export interface Notification {
  id: string
  type: NotificationType
  title: string
  message: string
  data: Record<string, unknown> | null
  created_at: string
  read: boolean
}

export interface NotificationListResponse {
  success: boolean
  data: Notification[]
  count: number
  unread_count: number
}

export interface UnreadCountResponse {
  success: boolean
  count: number
}

// ── Agent (more_agents backend) ──────────────────────────────────────────

export type AgentState = 'idle' | 'assigned' | 'running' | 'completed' | 'failed' | 'offline'
export type AgentPhase = 'idle' | 'sending' | 'waiting' | 'thinking' | 'tool' | 'replying' | 'done' | 'aborted' | 'error'
export type AgentType = 'general' | 'codegen' | 'data_analysis' | 'domain'

export interface AgentCapability {
  id: number
  name: string
  description: string
  skill_tags: string[]
}

export interface Agent {
  id: number
  agent_id: string
  name: string
  agent_type: AgentType
  state: AgentState
  phase: AgentPhase
  skill_tags: string[]
  max_concurrent_tasks: number
  priority_weight: number
  current_task_count: number
  success_count: number
  failure_count: number
  last_heartbeat: string | null
  description: string | null
  emoji: string | null
  theme_color: string | null
  workspace: string | null
  subagent_allow: string[] | null
  subagent_deny: string[] | null
  config: Record<string, unknown> | null
  capabilities: AgentCapability[]
  created_at: string
  updated_at: string
}

// ── Scenario (more_agents backend) ──────────────────────────────────────

export type ScenarioStatus = 'draft' | 'active' | 'completed' | 'archived'

export interface ScenarioMember {
  id: number
  agent_id: string
  role: string
  channel: string | null
}

export interface ScenarioTask {
  id: number
  task_id: string
  title: string
  description: string
  status: string
  assigned_agents: string[]
  priority: string
  session_key: string | null
  created_at: string
}

export interface ScenarioLog {
  id: number
  level: string
  message: string
  agent_id: string | null
  task_id: string | null
  created_at: string
}

export interface Scenario {
  id: number
  scenario_id: string
  name: string
  description: string
  status: ScenarioStatus
  agent_selection_mode: string
  coordinator_id: string | null
  members: ScenarioMember[]
  tasks: ScenarioTask[]
  logs: ScenarioLog[]
  created_at: string
  updated_at: string
}

// ── Monitoring (more_agents backend) ────────────────────────────────────

export interface MonitoringOverview {
  total_agents: number
  active_agents: number
  idle_agents: number
  offline_agents: number
  total_tasks: number
  pending_tasks: number
  running_tasks: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
}

// ── Cron ────────────────────────────────────────────────────────────────

export interface CronJob {
  id: string
  name: string
  cron_expression: string
  schedule: string
  task_goal: string
  goal: string
  edition: string
  enabled: boolean
  context_from: string[]
  last_run: string | null
  last_run_at: string | null
  next_run: string | null
  created_at: string
  updated_at: string
}

// ── Analytics ───────────────────────────────────────────────────────────

export interface AnalyticsOverview {
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  active_tasks: number
  total_skills: number
  active_skills: number
  total_memories: number
  avg_task_duration: number
  success_rate: number
  recent_activity_24h: number
}

export interface TaskTrendPoint {
  date: string
  count: number
}

export interface SkillsPerformanceItem {
  name: string
  success_rate: number
  total_runs: number
  avg_duration: number
}

export interface MemoriesGrowthPoint {
  date: string
  cumulative: number
}

export interface RecentActivityItem {
  event_type: string
  description: string
  timestamp: string
}

// ── Advanced Analytics ──────────────────────────────────────────────────

export interface RealtimeMetrics {
  running_tasks: number
  completed_last_hour: number
  failed_last_hour: number
  avg_execution_time_seconds: number | null
  tasks_per_hour: number
  active_skills: number
  total_cost_usd: number
}

export interface CostTrendPoint {
  date: string
  cost_usd: number
  prompt_tokens: number
  completion_tokens: number
  requests: number
}

export interface CostBreakdownItem {
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  requests: number
  estimated_cost_usd: number
}

export interface CostSummary {
  total_cost_usd: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_requests: number
  breakdown: CostBreakdownItem[]
}

export interface SkillBenchmarkItem {
  name: string
  success_rate: number
  total_runs: number
  avg_execution_time: number | null
  avg_cost_usd: number | null
  with_skill_duration?: number | null
  without_skill_duration?: number | null
  improvement_ratio?: number | null
  trend: { success: boolean; created_at: string }[]
}

export interface AnomalyAlert {
  type: string
  severity: string
  message: string
  resource: string
  value: number
  threshold: number
  detected_at: string
}

// ── Task DAG ────────────────────────────────────────────────────────────

export interface TaskDAGNode {
  id: string
  name: string
  status: string
  goal: string
  risk_level: string | null
  created_at: string
}

export interface TaskDAGEdge {
  source: string
  target: string
  label?: string
}

export interface TaskDAGGraph {
  nodes: TaskDAGNode[]
  edges: TaskDAGEdge[]
}

// ── Template ────────────────────────────────────────────────────────────

export interface Template {
  id: string
  name: string
  description: string
  goal_template: string
  edition: string
  parameters: Record<string, unknown>
  created_at: string
  updated_at: string
}

// ── Search ──────────────────────────────────────────────────────────────

export interface SearchHit {
  id: string
  title: string
  matched_field: string
  extra?: Record<string, unknown>
}

export interface SearchResults {
  tasks: SearchHit[]
  memories: SearchHit[]
  skills: SearchHit[]
  conversations: SearchHit[]
}

export interface SearchResponse {
  results: SearchResults
  total: number
  query: string
}

// ── RBAC ────────────────────────────────────────────────────────────────

export interface Role {
  id: string
  name: string
  description: string | null
  is_default: boolean
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface Permission {
  id: string
  name: string
  resource: string
  action: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface RoleWithPermissions extends Role {
  permissions: Permission[]
}

export interface UserRoleAssignment {
  id: string
  user_id: string
  role_id: string
  granted_by: string | null
  created_at: string
}

export interface UserWithRoles {
  id: string
  username: string
  email: string | null
  role: string
  roles: Role[]
}

// ── Edition Profile ─────────────────────────────────────────────────────

export interface EditionProfile {
  id: string
  edition: string
  name: string
  config: Record<string, unknown>
  is_active: boolean
}

// ── User ────────────────────────────────────────────────────────────────

export interface User {
  id: string
  username: string
  email: string | null
  role: string
  is_active: boolean
  sso_id: string | null
  sso_provider: string | null
  auth_method: 'local' | 'sso'
  created_at: string
  updated_at: string
}
