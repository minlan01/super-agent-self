import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { OpenClawSnapshot, ResourcePartitionId } from '@/museum/core/types'

/** Default poll interval in ms (20s) */
const DEFAULT_POLL_MS = 20000
/** Maximum backoff interval (5 min) */
const MAX_BACKOFF_MS = 300000
/** Base backoff multiplier */
const BACKOFF_MULTIPLIER = 2

/** Room labels for mock data */
const ROOM_LABELS: Record<ResourcePartitionId, string> = {
  document: 'Document Vault',
  images: 'Image Gallery',
  memory: 'Memory Hall',
  skills: 'Skill Library',
  gateway: 'Gateway Gate',
  log: 'Log Archives',
  mcp: 'MCP Workshop',
  schedule: 'Schedule Tower',
  alarm: 'Alarm Station',
  agent: 'Agent Hall',
  task_queues: 'Task Queues',
  break_room: 'Break Room',
}

/** Build a mock snapshot for when all backends are offline. */
function buildMockSnapshot(): OpenClawSnapshot {
  const now = new Date().toISOString()
  const resourceIds = Object.keys(ROOM_LABELS) as ResourcePartitionId[]
  return {
    mode: 'mock',
    generatedAt: now,
    resources: resourceIds.map(id => ({
      id,
      label: ROOM_LABELS[id],
      status: 'idle' as const,
      itemCount: 0,
      lastAccessAt: now,
      summary: `${ROOM_LABELS[id]} (offline)`,
      detail: 'Waiting for backend connection',
      source: 'mock',
    })),
    recentEvents: [],
    focus: {
      resourceId: 'agent',
      label: 'Agent Hall',
      occurredAt: now,
      detail: 'Awaiting connection',
      reason: 'No backend available',
    },
    activeAgents: [],
    activeProcesses: [],
    mainActorContext: { tokens: 0, maxTokens: 0, remaining: 1 },
  }
}

export const useMuseumStore = defineStore('museum', () => {
  /* ── State ── */
  const snapshot = ref<OpenClawSnapshot | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const pollIntervalMs = ref(DEFAULT_POLL_MS)
  const paused = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null

  // Backoff state
  let consecutiveFailures = 0
  let currentBackoffMs = DEFAULT_POLL_MS

  /* ── Computed ── */
  const resourceCount = computed(() => snapshot.value?.resources.length ?? 0)
  const activeAgentCount = computed(() => snapshot.value?.activeAgents?.length ?? 0)
  const activeProcessCount = computed(() => snapshot.value?.activeProcesses?.length ?? 0)
  const hasLiveData = computed(() => snapshot.value?.mode === 'live')
  const focusResourceId = computed(() => snapshot.value?.focus?.resourceId ?? null)
  const isMockMode = computed(() => snapshot.value?.mode === 'mock')

  /* ── Actions ── */
  async function fetchSnapshot(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const response = await fetch('/api/openclaw/snapshot', { cache: 'no-store' })
      if (!response.ok) {
        throw new Error(`Snapshot API returned ${response.status}`)
      }
      const data = (await response.json()) as OpenClawSnapshot

      // Validate minimal shape
      if (!data.mode || !data.generatedAt || !Array.isArray(data.resources)) {
        throw new Error('Invalid snapshot shape received')
      }

      snapshot.value = data

      // Reset backoff on success
      consecutiveFailures = 0
      currentBackoffMs = pollIntervalMs.value
    } catch (e) {
      consecutiveFailures++
      error.value = e instanceof Error ? e.message : 'Failed to fetch snapshot'

      // Apply exponential backoff
      currentBackoffMs = Math.min(
        pollIntervalMs.value * Math.pow(BACKOFF_MULTIPLIER, consecutiveFailures),
        MAX_BACKOFF_MS
      )

      // If no snapshot yet, use mock data so the museum always renders
      if (!snapshot.value) {
        snapshot.value = buildMockSnapshot()
      }
      // Otherwise keep previous snapshot (stale but better than blank)
    } finally {
      loading.value = false
    }
  }

  function startPolling(intervalMs: number = DEFAULT_POLL_MS): void {
    stopPolling()
    pollIntervalMs.value = intervalMs
    currentBackoffMs = intervalMs
    consecutiveFailures = 0

    // Fetch immediately
    fetchSnapshot()

    // Poll with adaptive backoff
    pollTimer = setInterval(() => {
      if (!paused.value) {
        fetchSnapshot()

        // If we're in backoff, adjust the interval dynamically
        if (consecutiveFailures > 0) {
          stopPolling()
          // Restart with backoff interval
          pollTimer = setTimeout(() => {
            if (!paused.value) {
              fetchSnapshot()
            }
            // After backoff attempt, restart normal polling
            startPolling(pollIntervalMs.value)
          }, currentBackoffMs - pollIntervalMs.value) as unknown as ReturnType<typeof setInterval>
        }
      }
    }, intervalMs)
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      clearTimeout(pollTimer as unknown as number)
      pollTimer = null
    }
  }

  function setPaused(p: boolean): void {
    paused.value = p
  }

  /** Push external snapshot (e.g. from SSE or WebSocket) */
  function setSnapshot(s: OpenClawSnapshot): void {
    snapshot.value = s
  }

  function clear(): void {
    snapshot.value = null
    error.value = null
    consecutiveFailures = 0
    currentBackoffMs = pollIntervalMs.value
  }

  return {
    // State
    snapshot,
    loading,
    error,
    pollIntervalMs,
    paused,
    // Computed
    resourceCount,
    activeAgentCount,
    activeProcessCount,
    hasLiveData,
    focusResourceId,
    isMockMode,
    // Actions
    fetchSnapshot,
    startPolling,
    stopPolling,
    setPaused,
    setSnapshot,
    clear
  }
})
