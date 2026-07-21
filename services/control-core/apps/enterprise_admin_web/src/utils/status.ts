export const taskStatusType = (s: string): string =>
  ({ completed: 'success', failed: 'danger', executing: 'warning' }[s] ?? 'info')

export const extendedTaskStatusType = (s: string): string =>
  ({ completed: 'success', approved: 'success', failed: 'danger', rejected: 'danger', executing: 'warning' }[s] ?? 'info')

export const skillStatusType = (s: string): string =>
  ({ stable: 'success', candidate: 'warning', disabled: 'danger', deprecated: 'info' }[s] ?? 'info')

export const agentStateType = (s: string): string =>
  ({ idle: 'info', assigned: 'warning', running: '', completed: 'success', failed: 'danger', offline: 'info' }[s] ?? 'info')

export const scenarioStatusType = (s: string): string =>
  ({ draft: 'info', active: 'warning', completed: 'success', archived: 'info' }[s] ?? 'info')

// ── Shared status color maps (for ECharts / CSS) ──────────────────────

export const STATUS_COLORS: Record<string, string> = {
  completed: '#67c23a',
  failed: '#f56c6c',
  executing: '#e6a23c',
  running: '#e6a23c',
  planning: '#909399',
  pending: '#b1d3ff',
  cancelled: '#c0c4cc',
  awaiting_approval: '#e6a23c',
  queued: '#409eff',
  assigned: '#409eff',
  idle: '#909399',
  offline: '#c0c4cc',
}

export const AGENT_TYPE_COLORS: Record<string, string> = {
  general: '#409eff',
  codegen: '#67c23a',
  data_analysis: '#e6a23c',
  domain: '#f56c6c',
}
