<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NGrid,
  NGridItem,
  NIcon,
  NSpace,
  NSpin,
  NTag,
  NText,
} from 'naive-ui'
import {
  CalendarOutline,
  ChatbubblesOutline,
  ChatboxEllipsesOutline,
  ExtensionPuzzleOutline,
  FlashOutline,
  RefreshOutline,
  SparklesOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import StatCard from '@/components/common/StatCard.vue'
import MuseumCanvas from '@/components/museum/MuseumCanvas.vue'
import { useWebSocketStore } from '@/stores/websocket'
import { useHermesConnectionStore } from '@/stores/hermes/connection'
import { useMuseumStore } from '@/stores/museum'
import { ROOM_ROUTE_MAP, ROOM_LABEL_MAP } from '@/adapters/museum/router-sync'
import type { ResourcePartitionId } from '@/museum/core/types'
import { formatRelativeTime } from '@/utils/format'
import type {
  CostUsageSummary,
  CronJob,
  ModelInfo,
  OpenClawConfig,
  SessionsUsageResult,
  SessionsUsageTotals,
  Skill,
} from '@/api/types'
import type { HermesSession, HermesCronJob, HermesSkill, HermesUsageAnalytics } from '@/api/hermes/types'

type RangePreset = 'today' | '7d' | '30d' | 'custom'
type UsageMode = 'tokens' | 'cost'

const router = useRouter()
const wsStore = useWebSocketStore()
const hermesConnStore = useHermesConnectionStore()
const museumStore = useMuseumStore()
const isHermes = computed(() => hermesConnStore.currentGateway === 'hermes')
const { t, locale } = useI18n()
const loading = ref(true)
const refreshing = ref(false)
const usageError = ref<string | null>(null)
const lastUpdatedAt = ref<number | null>(null)
const rangePreset = ref<RangePreset>('7d')
const usageMode = ref<UsageMode>('tokens')
const usageStartDate = ref('')
const usageEndDate = ref('')

const stats = ref({
  sessionCount: 0,
  cronCount: 0,
  modelCount: 0,
  installedSkills: 0,
})

const sessionsUsageResult = ref<SessionsUsageResult | null>(null)
const usageCostSummary = ref<CostUsageSummary | null>(null)

let cleanupStateChange: (() => void) | null = null
let retryAfterFirstConnect = false

const ZERO_USAGE_TOTALS: SessionsUsageTotals = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  totalCost: 0,
  inputCost: 0,
  outputCost: 0,
  cacheReadCost: 0,
  cacheWriteCost: 0,
  missingCostEntries: 0,
}

const connectionLabel = computed(() => {
  if (isHermes.value) {
    return hermesConnStore.hermesConnected
      ? t('pages.dashboard.connection.connected')
      : t('pages.dashboard.connection.connecting')
  }
  if (wsStore.state === 'connected') return t('pages.dashboard.connection.connected')
  if (wsStore.state === 'connecting') return t('pages.dashboard.connection.connecting')
  if (wsStore.state === 'reconnecting') return t('pages.dashboard.connection.reconnecting')
  if (wsStore.state === 'failed') return t('pages.dashboard.connection.failed')
  return t('pages.dashboard.connection.disconnected')
})

const connectionType = computed<'success' | 'warning' | 'error' | 'default'>(() => {
  if (isHermes.value) {
    return hermesConnStore.hermesConnected ? 'success' : 'warning'
  }
  if (wsStore.state === 'connected') return 'success'
  if (wsStore.state === 'connecting' || wsStore.state === 'reconnecting') return 'warning'
  if (wsStore.state === 'failed') return 'error'
  return 'default'
})

const lastUpdatedText = computed(() => {
  if (!lastUpdatedAt.value) return t('pages.dashboard.lastUpdated.none')
  return t('pages.dashboard.lastUpdated.text', { time: formatRelativeTime(lastUpdatedAt.value) })
})

const usageTotals = computed(() =>
  sessionsUsageResult.value?.totals || usageCostSummary.value?.totals || ZERO_USAGE_TOTALS
)

const usageSessions = computed(() => sessionsUsageResult.value?.sessions || [])

const usageCoverageText = computed(() => {
  const total = usageSessions.value.length
  const withUsage = usageSessions.value.filter((item) => item.usage && item.usage.totalTokens > 0).length
  if (total === 0) return t('pages.dashboard.usage.coverage.none')
  return t('pages.dashboard.usage.coverage.text', { withUsage, total })
})

const tokenTotalDisplay = computed(() => formatCompactNumber(usageTotals.value.totalTokens))
const costTotalDisplay = computed(() => formatUsd(usageTotals.value.totalCost))

const usageSegments = computed(() => {
  const totals = usageTotals.value
  if (usageMode.value === 'tokens') {
    return [
      { key: 'input', label: t('pages.dashboard.usage.segments.input'), value: totals.input, color: '#2a7fff' },
      { key: 'output', label: t('pages.dashboard.usage.segments.output'), value: totals.output, color: '#18a058' },
      { key: 'cacheRead', label: t('pages.dashboard.usage.segments.cacheRead'), value: totals.cacheRead, color: '#13c2c2' },
      { key: 'cacheWrite', label: t('pages.dashboard.usage.segments.cacheWrite'), value: totals.cacheWrite, color: '#f0a020' },
    ]
  }

  return [
    { key: 'inputCost', label: t('pages.dashboard.usage.segments.inputCost'), value: totals.inputCost, color: '#2a7fff' },
    { key: 'outputCost', label: t('pages.dashboard.usage.segments.outputCost'), value: totals.outputCost, color: '#18a058' },
    { key: 'cacheReadCost', label: t('pages.dashboard.usage.segments.cacheReadCost'), value: totals.cacheReadCost, color: '#13c2c2' },
    { key: 'cacheWriteCost', label: t('pages.dashboard.usage.segments.cacheWriteCost'), value: totals.cacheWriteCost, color: '#f0a020' },
  ]
})

const segmentTotal = computed(() => {
  const sum = usageSegments.value.reduce((acc, item) => acc + item.value, 0)
  return sum > 0 ? sum : 1
})

const dailyUsage = computed(() => {
  const fromSessions = sessionsUsageResult.value?.aggregates?.daily || []
  if (fromSessions.length > 0) return fromSessions

  const fromCost = usageCostSummary.value?.daily || []
  return fromCost.map((item) => ({
    date: item.date,
    tokens: item.totalTokens,
    cost: item.totalCost,
    messages: 0,
    toolCalls: 0,
    errors: 0,
  }))
})

const dailyUsageVisible = computed(() => dailyUsage.value.slice(-14))

const trendSeries = computed(() =>
  dailyUsageVisible.value.map((item) => ({
    date: item.date,
    value: usageMode.value === 'tokens' ? item.tokens : item.cost,
    messages: item.messages,
    errors: item.errors,
  }))
)

const trendGeometry = computed(() => {
  const width = 760
  const height = 240
  const left = 56
  const right = 18
  const top = 18
  const bottom = 44
  const series = trendSeries.value
  const usableWidth = width - left - right
  const usableHeight = height - top - bottom
  const maxValue = Math.max(...series.map((item) => item.value), 0, 1)

  const points = series.map((item, index) => {
    const x =
      series.length === 1
        ? left + usableWidth / 2
        : left + (index / (series.length - 1)) * usableWidth
    const y = top + usableHeight - (item.value / maxValue) * usableHeight
    return {
      ...item,
      x,
      y,
    }
  })

  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ')
  const areaPath = points.length
    ? `M ${left} ${top + usableHeight} L ${points.map((point) => `${point.x} ${point.y}`).join(' L ')} L ${left + usableWidth} ${top + usableHeight} Z`
    : ''
  const guides = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    ratio,
    y: top + usableHeight - usableHeight * ratio,
    value: maxValue * ratio,
  }))

  return {
    width,
    height,
    left,
    right,
    top,
    bottom,
    usableWidth,
    usableHeight,
    maxValue,
    points,
    polyline,
    areaPath,
    guides,
  }
})

const trendAxisLabels = computed(() => {
  if (trendSeries.value.length === 0) {
    return { start: '-', mid: '-', end: '-' }
  }
  const start = trendSeries.value[0]
  const mid = trendSeries.value[Math.floor((trendSeries.value.length - 1) / 2)]
  const end = trendSeries.value[trendSeries.value.length - 1]
  return {
    start: start?.date.slice(5) || '-',
    mid: mid?.date.slice(5) || '-',
    end: end?.date.slice(5) || '-',
  }
})

const trendSvgRef = ref<SVGSVGElement | null>(null)
const trendHoverIndex = ref<number | null>(null)
const trendTooltipStyle = ref<Record<string, string> | null>(null)

/* ── Museum ── */
const museumReady = ref(false)
const museumExpanded = ref(false)

function toggleMuseumExpand() {
  museumExpanded.value = !museumExpanded.value
}

function onMuseumEscKey(event: KeyboardEvent) {
  if (event.key === 'Escape' && museumExpanded.value) {
    museumExpanded.value = false
  }
}

function onMuseumRoomSelect(resourceId: ResourcePartitionId) {
  const route = ROOM_ROUTE_MAP[resourceId]
  if (route) {
    router.push(route)
  }
}

const hoveredTrendPoint = computed(() => {
  const index = trendHoverIndex.value
  if (index === null) return null
  return trendGeometry.value.points[index] || null
})

const hoveredTrendText = computed(() => {
  const point = hoveredTrendPoint.value
  if (!point) return ''
  return t('pages.dashboard.trend.pointTitle', {
    date: point.date,
    value: formatUsageValue(point.value),
    messages: point.messages,
    errors: point.errors,
  })
})

function clearTrendHover() {
  trendHoverIndex.value = null
  trendTooltipStyle.value = null
}

function handleTrendMouseMove(event: MouseEvent) {
  const svg = trendSvgRef.value
  const points = trendGeometry.value.points
  if (!svg || points.length === 0) {
    clearTrendHover()
    return
  }

  const firstPoint = points[0]
  if (!firstPoint) {
    clearTrendHover()
    return
  }

  const rect = svg.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) {
    clearTrendHover()
    return
  }

  const svgX = ((event.clientX - rect.left) / rect.width) * trendGeometry.value.width
  const plotMinX = trendGeometry.value.left
  const plotMaxX = trendGeometry.value.left + trendGeometry.value.usableWidth
  if (svgX < plotMinX || svgX > plotMaxX) {
    clearTrendHover()
    return
  }

  let nearestIndex = 0
  let nearestDistance = Math.abs(firstPoint.x - svgX)
  for (let i = 1; i < points.length; i += 1) {
    const candidate = points[i]
    if (!candidate) continue

    const distance = Math.abs(candidate.x - svgX)
    if (distance < nearestDistance) {
      nearestDistance = distance
      nearestIndex = i
    }
  }

  const point = points[nearestIndex]
  if (!point) {
    clearTrendHover()
    return
  }
  trendHoverIndex.value = nearestIndex

  const pointPxX = (point.x / trendGeometry.value.width) * rect.width
  const pointPxY = (point.y / trendGeometry.value.height) * rect.height

  // Keep in sync with `.trend-tooltip` width/height
  const tooltipWidth = 260
  const tooltipHeight = 32
  const margin = 8
  const offsetX = 12
  const offsetY = 10

  let left = pointPxX + offsetX
  let top = pointPxY - offsetY - tooltipHeight

  if (left + tooltipWidth > rect.width - margin) left = pointPxX - offsetX - tooltipWidth
  left = Math.max(margin, Math.min(left, rect.width - tooltipWidth - margin))

  if (top < margin) top = pointPxY + offsetY
  top = Math.max(margin, Math.min(top, rect.height - tooltipHeight - margin))

  trendTooltipStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
  }
}

const maxValues = { sessions: 100, cronJobs: 50, models: 30, skills: 30, tokens: 1_000_000 }

const kpiColors = ['#3dd68c', '#59d0ff', '#ffb16b', '#a58aff', '#ff7b7b', '#7ce6c7']

const statBars = computed(() => ({
  sessions: Math.min((stats.value.sessionCount / maxValues.sessions) * 100, 100),
  cronJobs: Math.min((stats.value.cronCount / maxValues.cronJobs) * 100, 100),
  models: Math.min((stats.value.modelCount / maxValues.models) * 100, 100),
  skills: Math.min((stats.value.installedSkills / maxValues.skills) * 100, 100),
  tokens: Math.min((usageTotals.value.totalTokens / maxValues.tokens) * 100, 100),
}))


/** Map each room id → its telemetry status from the current snapshot */
const roomStatusMap = computed(() => {
  const snap = museumStore.snapshot
  if (!snap?.resources) return {} as Record<string, { status: string; count: number }>
  const map: Record<string, { status: string; count: number }> = {}
  for (const r of snap.resources) {
    map[r.id] = { status: r.status, count: r.itemCount }
  }
  return map
})
const usageKpis = computed(() => {
  const totals = usageTotals.value
  const rows = dailyUsage.value

  const totalMessages = rows.reduce((acc, item) => acc + (item.messages || 0), 0)
  const totalToolCalls = rows.reduce((acc, item) => acc + (item.toolCalls || 0), 0)
  const totalErrors = rows.reduce((acc, item) => acc + (item.errors || 0), 0)
  const activeDays = rows.filter((item) => {
    if (usageMode.value === 'tokens') return item.tokens > 0
    return item.cost > 0
  }).length

  const avgTokensPerMessage = totalMessages > 0 ? totals.totalTokens / totalMessages : 0
  const errorRate = totalMessages > 0 ? (totalErrors / totalMessages) * 100 : 0
  const cacheReadRatio = totals.input > 0 ? (totals.cacheRead / totals.input) * 100 : 0

  return [
    {
      key: 'messages',
      label: t('pages.dashboard.kpis.messages.label'),
      value: formatCompactNumber(totalMessages),
      hint: totalMessages > 0 ? t('pages.dashboard.kpis.messages.hint', { days: rows.length }) : t('pages.dashboard.kpis.messages.emptyHint'),
    },
    {
      key: 'tool-calls',
      label: t('pages.dashboard.kpis.toolCalls.label'),
      value: formatCompactNumber(totalToolCalls),
      hint: totalToolCalls > 0 ? t('pages.dashboard.kpis.toolCalls.hint', { tool: topTools.value[0]?.name || '-' }) : t('pages.dashboard.kpis.toolCalls.emptyHint'),
    },
    {
      key: 'error-rate',
      label: t('pages.dashboard.kpis.errorRate.label'),
      value: `${errorRate.toFixed(errorRate >= 1 ? 1 : 2)}%`,
      hint: t('pages.dashboard.kpis.errorRate.hint', { errors: formatCompactNumber(totalErrors), messages: formatCompactNumber(totalMessages) }),
    },
    {
      key: 'avg-token',
      label: t('pages.dashboard.kpis.avgTokens.label'),
      value: avgTokensPerMessage > 0 ? formatCompactNumber(avgTokensPerMessage) : '0',
      hint: t('pages.dashboard.kpis.avgTokens.hint'),
    },
    {
      key: 'cache-read-ratio',
      label: t('pages.dashboard.kpis.cacheReadRatio.label'),
      value: `${cacheReadRatio.toFixed(cacheReadRatio >= 10 ? 1 : 2)}%`,
      hint: t('pages.dashboard.kpis.cacheReadRatio.hint', { cacheRead: formatCompactNumber(totals.cacheRead), input: formatCompactNumber(totals.input) }),
    },
    {
      key: 'active-days',
      label: t('pages.dashboard.kpis.activeDays.label'),
      value: String(activeDays),
      hint: t('pages.dashboard.kpis.activeDays.hint', { days: rows.length }),
    },
  ]
})

const topModels = computed(() => {
  const list = sessionsUsageResult.value?.aggregates?.byModel || []
  const key = usageMode.value === 'tokens' ? 'totalTokens' : 'totalCost'
  return [...list]
    .sort((a, b) => (b.totals[key] || 0) - (a.totals[key] || 0))
    .slice(0, 5)
})

const topProviders = computed(() => {
  const list = sessionsUsageResult.value?.aggregates?.byProvider || []
  const key = usageMode.value === 'tokens' ? 'totalTokens' : 'totalCost'
  return [...list]
    .sort((a, b) => (b.totals[key] || 0) - (a.totals[key] || 0))
    .slice(0, 5)
})

const topTools = computed(() => {
  const list = sessionsUsageResult.value?.aggregates?.tools?.tools || []
  return [...list].sort((a, b) => b.count - a.count).slice(0, 6)
})

const topModelMax = computed(() =>
  Math.max(...topModels.value.map((item) => usageMetric(item.totals)), 0)
)

const topProviderMax = computed(() =>
  Math.max(...topProviders.value.map((item) => usageMetric(item.totals)), 0)
)

const topToolMax = computed(() =>
  Math.max(...topTools.value.map((item) => item.count || 0), 0)
)

onMounted(async () => {
  applyRangePreset('7d', false)

  if (isHermes.value) {
    // Hermes 模式：先确保连接，再刷新数据
    if (!hermesConnStore.hermesConnected) {
      await hermesConnStore.connect()
    }
  } else {
    retryAfterFirstConnect = wsStore.state !== 'connected'
    cleanupStateChange = wsStore.subscribe('stateChange', () => {
      maybeRetryAfterConnect()
    })
  }
  await refreshDashboard()
  if (!isHermes.value) {
    maybeRetryAfterConnect()
  }
  // Start museum polling
  museumStore.startPolling(15000)
  window.addEventListener('keydown', onMuseumEscKey)
})

onUnmounted(() => {
  cleanupStateChange?.()
  cleanupStateChange = null
  museumStore.stopPolling()
  window.removeEventListener('keydown', onMuseumEscKey)
})

function maybeRetryAfterConnect() {
  if (!retryAfterFirstConnect) return
  if (wsStore.state !== 'connected') return
  if (refreshing.value) return

  retryAfterFirstConnect = false
  void refreshDashboard()
}

async function refreshDashboard() {
  if (refreshing.value) return

  refreshing.value = true
  usageError.value = null

  try {
    if (isHermes.value) {
      // Hermes 模式：通过 Hermes API 获取数据
      if (!hermesConnStore.hermesConnected) {
        await hermesConnStore.connect()
      }
      const hermesApi = hermesConnStore.getClient()
      if (!hermesApi) throw new Error('Hermes not connected')

      const [sessionsRes, cronsRes, skillsRes, usageRes] = await Promise.allSettled([
        hermesApi.listSessions(),
        hermesApi.listCronJobs(),
        hermesApi.listSkills(),
        hermesApi.getUsageAnalytics(7),
      ])

      const sessionList = sessionsRes.status === 'fulfilled' ? (sessionsRes.value as HermesSession[]) : []
      const cronList = cronsRes.status === 'fulfilled' ? (cronsRes.value as HermesCronJob[]) : []
      const skillList = skillsRes.status === 'fulfilled' ? (skillsRes.value as HermesSkill[]) : []

      stats.value = {
        sessionCount: sessionList.length,
        cronCount: cronList.filter((job: HermesCronJob) => job.enabled).length,
        modelCount: 1,
        installedSkills: skillList.length,
      }

      if (usageRes.status === 'fulfilled') {
        const usage = usageRes.value as HermesUsageAnalytics
        sessionsUsageResult.value = {
          updatedAt: Date.now(),
          startDate: usageStartDate.value || '',
          endDate: usageEndDate.value || '',
          sessions: [],
          totals: {
            input: usage.totals?.total_input || 0,
            output: usage.totals?.total_output || 0,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: (usage.totals?.total_input || 0) + (usage.totals?.total_output || 0),
            totalCost: usage.totals?.total_estimated_cost || 0,
            inputCost: 0,
            outputCost: 0,
            cacheReadCost: 0,
            cacheWriteCost: 0,
            missingCostEntries: 0,
          },
          aggregates: {
            messages: { total: 0, user: 0, assistant: 0, toolCalls: 0, toolResults: 0, errors: 0 },
            tools: { totalCalls: 0, uniqueTools: 0, tools: [] },
            byModel: [],
            byProvider: [],
            byAgent: [],
            byChannel: [],
            daily: [],
          },
        } as SessionsUsageResult
      } else {
        sessionsUsageResult.value = null
      }
    } else {
      // OpenClaw 模式：通过 WebSocket RPC 获取数据
      const [sessionsRes, cronsRes, modelsRes, skillsRes, configRes, usageRes, usageCostRes] = await Promise.allSettled([
        wsStore.rpc.listSessions(),
        wsStore.rpc.listCrons(),
        wsStore.rpc.listModels(),
        wsStore.rpc.listSkills(),
        wsStore.rpc.getConfig(),
        wsStore.rpc.getSessionsUsage({
          startDate: usageStartDate.value,
          endDate: usageEndDate.value,
          limit: 1000,
        }),
        wsStore.rpc.getUsageCost({
          startDate: usageStartDate.value,
          endDate: usageEndDate.value,
        }),
      ])

      const sessionList = sessionsRes.status === 'fulfilled' ? sessionsRes.value : []
      const cronList = cronsRes.status === 'fulfilled' ? cronsRes.value : []
      const modelList = modelsRes.status === 'fulfilled' ? modelsRes.value : []
      const skillList = skillsRes.status === 'fulfilled' ? skillsRes.value : []
      const config = configRes.status === 'fulfilled' ? configRes.value : null
      stats.value = {
        sessionCount: sessionList.length,
        cronCount: cronList.filter((job: CronJob) => job.enabled).length,
        modelCount: resolveConfiguredModelCount(config, modelList),
        installedSkills: skillList.filter((s: Skill) => s.installed).length,
      }

      if (usageRes.status === 'fulfilled') {
        sessionsUsageResult.value = usageRes.value
      } else {
        sessionsUsageResult.value = null
        usageError.value = usageRes.reason instanceof Error ? usageRes.reason.message : String(usageRes.reason)
      }

      if (usageCostRes.status === 'fulfilled') {
        usageCostSummary.value = usageCostRes.value
      } else {
        usageCostSummary.value = null
        if (!usageError.value) {
          usageError.value = usageCostRes.reason instanceof Error
            ? usageCostRes.reason.message
            : String(usageCostRes.reason)
        }
      }
    }

    lastUpdatedAt.value = Date.now()
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function applyRangePreset(preset: Exclude<RangePreset, 'custom'>, refresh = true) {
  rangePreset.value = preset
  const today = new Date()
  const end = formatYmd(today)

  if (preset === 'today') {
    usageStartDate.value = end
    usageEndDate.value = end
  } else if (preset === '7d') {
    usageStartDate.value = formatYmd(addDays(today, -6))
    usageEndDate.value = end
  } else {
    usageStartDate.value = formatYmd(addDays(today, -29))
    usageEndDate.value = end
  }

  if (refresh) {
    void refreshDashboard()
  }
}

function handleDateRangeChanged() {
  rangePreset.value = 'custom'
}

function addDays(base: Date, offset: number): Date {
  const next = new Date(base)
  next.setDate(next.getDate() + offset)
  return next
}

function formatYmd(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function toRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function splitModelRef(value: string): { providerId: string; modelId: string } | null {
  const modelRef = value.trim()
  const slashIndex = modelRef.indexOf('/')
  if (slashIndex <= 0 || slashIndex >= modelRef.length - 1) return null

  const providerId = modelRef.slice(0, slashIndex).trim()
  const modelId = modelRef.slice(slashIndex + 1).trim()
  if (!providerId || !modelId) return null

  return { providerId, modelId }
}

function collectConfiguredModelRefs(input: unknown, refs: Set<string>) {
  if (!input) return

  if (typeof input === 'string') {
    const parsed = splitModelRef(input)
    if (parsed) refs.add(`${parsed.providerId}/${parsed.modelId}`)
    return
  }

  if (Array.isArray(input)) {
    for (const item of input) {
      collectConfiguredModelRefs(item, refs)
    }
    return
  }

  const row = toRecord(input)
  if (!row) return

  for (const candidate of [row.id, row.model, row.ref, row.primary]) {
    if (typeof candidate === 'string') {
      const parsed = splitModelRef(candidate)
      if (parsed) refs.add(`${parsed.providerId}/${parsed.modelId}`)
    }
  }

  for (const [key, value] of Object.entries(row)) {
    const keyParsed = splitModelRef(key)
    if (keyParsed) refs.add(`${keyParsed.providerId}/${keyParsed.modelId}`)
    if (typeof value === 'string') {
      const valueParsed = splitModelRef(value)
      if (valueParsed) refs.add(`${valueParsed.providerId}/${valueParsed.modelId}`)
    }
  }
}

function collectProviderModelIds(provider: unknown, modelIds: Set<string>) {
  const row = toRecord(provider)
  if (!row) return

  const extract = (value: unknown) => {
    if (!value) return

    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'string' && item.trim()) {
          modelIds.add(item.trim())
          continue
        }
        const itemRow = toRecord(item)
        if (!itemRow) continue
        const id =
          (typeof itemRow.id === 'string' && itemRow.id.trim()) ||
          (typeof itemRow.name === 'string' && itemRow.name.trim()) ||
          ''
        if (id) modelIds.add(id)
      }
      return
    }

    const mapRow = toRecord(value)
    if (!mapRow) return
    for (const [key, item] of Object.entries(mapRow)) {
      const normalizedKey = key.trim()
      if (!normalizedKey) continue
      if (typeof item === 'string' && item.trim()) {
        modelIds.add(item.trim())
        continue
      }
      const itemRow = toRecord(item)
      if (itemRow) {
        const id =
          (typeof itemRow.id === 'string' && itemRow.id.trim()) ||
          (typeof itemRow.name === 'string' && itemRow.name.trim()) ||
          normalizedKey
        if (id) modelIds.add(id)
      } else {
        modelIds.add(normalizedKey)
      }
    }
  }

  extract(row.models)
  extract(row.modelIds)
  extract(row.availableModels)
  extract(row.whitelist)
}

function resolveConfiguredModelCount(config: OpenClawConfig | null, fallbackModels: ModelInfo[]): number {
  const refs = new Set<string>()
  const defaultsRaw = toRecord(config?.agents?.defaults)
  const defaultsModelRaw = toRecord(defaultsRaw?.model)
  collectConfiguredModelRefs(config?.models?.primary, refs)
  collectConfiguredModelRefs(config?.models?.fallback, refs)
  collectConfiguredModelRefs(defaultsRaw?.models, refs)
  collectConfiguredModelRefs(defaultsModelRaw?.primary, refs)
  collectConfiguredModelRefs(defaultsModelRaw?.fallback, refs)
  collectConfiguredModelRefs(defaultsModelRaw?.fallbacks, refs)

  if (refs.size > 0) return refs.size

  const providerModelIds = new Set<string>()
  const providers = toRecord(config?.models?.providers)
  if (providers) {
    for (const provider of Object.values(providers)) {
      collectProviderModelIds(provider, providerModelIds)
    }
  }
  if (providerModelIds.size > 0) return providerModelIds.size

  const fallbackIds = new Set(
    fallbackModels
      .filter((model) => model.available !== false)
      .map((model) => model.id)
      .filter((id) => !!id)
  )
  return fallbackIds.size
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat(locale.value, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
    maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
  }).format(value)
}

function formatUsageValue(value: number): string {
  return usageMode.value === 'tokens' ? formatCompactNumber(value) : formatUsd(value)
}

function usageMetric(totals: SessionsUsageTotals): number {
  return usageMode.value === 'tokens' ? totals.totalTokens : totals.totalCost
}

function topBarWidth(value: number, max: number): string {
  if (max <= 0 || value <= 0) return '0%'
  return `${Math.max((value / max) * 100, 8)}%`
}

function viewChat() {
  router.push({ name: 'Chat' })
}

function viewCron() {
  router.push({ name: 'Cron' })
}

function viewModels() {
  router.push({ name: 'Models' })
}
</script>

<template>
  <NSpin :show="loading">
    <div class="dashboard-page">
      <NCard class="dashboard-hero" :bordered="false">
        <div class="dashboard-hero-top">
          <div>
            <div class="dashboard-hero-title pixel-text-glow">{{ t('pages.dashboard.hero.title') }}</div>
            <div class="dashboard-hero-subtitle">
              {{ t('pages.dashboard.hero.subtitle') }}
            </div>
          </div>
          <NSpace :size="8" wrap>
            <NTag :type="connectionType" round :bordered="false">{{ connectionLabel }}</NTag>
            <NTag type="info" round :bordered="false">{{ usageCoverageText }}</NTag>
            <NTag round :bordered="false">{{ lastUpdatedText }}</NTag>
          </NSpace>
        </div>

        <NSpace :size="8" wrap class="dashboard-filters-row">
          <NButton size="small" :type="rangePreset === 'today' ? 'primary' : 'default'" secondary @click="applyRangePreset('today')">{{ t('pages.dashboard.range.today') }}</NButton>
          <NButton size="small" :type="rangePreset === '7d' ? 'primary' : 'default'" secondary @click="applyRangePreset('7d')">7d</NButton>
          <NButton size="small" :type="rangePreset === '30d' ? 'primary' : 'default'" secondary @click="applyRangePreset('30d')">30d</NButton>

          <input
            v-model="usageStartDate"
            class="usage-date-input"
            type="date"
            @change="handleDateRangeChanged"
          />
          <span class="usage-date-sep">{{ t('pages.dashboard.range.to') }}</span>
          <input
            v-model="usageEndDate"
            class="usage-date-input"
            type="date"
            @change="handleDateRangeChanged"
          />

          <NButton size="small" :type="usageMode === 'tokens' ? 'primary' : 'default'" secondary @click="usageMode = 'tokens'">{{ t('pages.dashboard.usageMode.tokens') }}</NButton>

          <NButton type="primary" :loading="refreshing" @click="refreshDashboard">
            <template #icon><NIcon :component="RefreshOutline" /></template>
            {{ t('common.refresh') }}
          </NButton>
          <NButton secondary @click="viewChat">
            <template #icon><NIcon :component="ChatboxEllipsesOutline" /></template>
            {{ t('routes.chat') }}
          </NButton>
          <NButton secondary @click="viewCron">{{ t('routes.cron') }}</NButton>
          <NButton secondary @click="viewModels">{{ t('routes.models') }}</NButton>
        </NSpace>

        <NAlert v-if="usageError" type="warning" :bordered="false" style="margin-top: 10px;">
          {{ t('pages.dashboard.usage.error', { error: usageError }) }}
        </NAlert>
      </NCard>

      <!-- ═══ Pixel Museum ═══ -->
      <div class="museum-section" :class="{ expanded: museumExpanded }">
        <div class="museum-header">
          <span class="museum-title pixel-text">Agent Command Center</span>
          <div class="museum-header-right">
            <div class="museum-status">
              <span class="museum-status-dot" :class="museumStore.hasLiveData ? 'live' : museumStore.isMockMode ? 'mock' : 'dead'" />
              <span class="museum-status-text">
                {{ museumStore.hasLiveData ? `${museumStore.activeAgentCount} agents · ${museumStore.activeProcessCount} tasks` : museumStore.isMockMode ? 'Mock mode' : 'No data' }}
              </span>
            </div>
            <button
              class="museum-expand-btn"
              :title="museumExpanded ? 'Collapse' : 'Expand'"
              @click="toggleMuseumExpand"
            >
              <span class="expand-icon">{{ museumExpanded ? '⊟' : '⊞' }}</span>
            </button>
          </div>
        </div>
        <div class="museum-frame pixel-corners" :class="{ expanded: museumExpanded }">
          <MuseumCanvas
            mode="full"
            :snapshot="museumStore.snapshot"
            @room-select="onMuseumRoomSelect"
            @ready="museumReady = true"
          />
          <div v-if="!museumReady" class="museum-loading">
            <div class="pixel-spinner">
              <span /><span /><span /><span />
            </div>
            <span class="museum-loading-text">INITIALIZING MUSEUM</span>
          </div>
        </div>
        <!-- Room legend -->
        <div class="museum-legend">
          <button
            v-for="(label, id) in ROOM_LABEL_MAP"
            :key="id"
            class="legend-chip pixel-text"
            :class="roomStatusMap[id]?.status || 'idle'"
            :title="roomStatusMap[id] ? `${label}: ${roomStatusMap[id].status} (${roomStatusMap[id].count})` : label"
            @click="onMuseumRoomSelect(id)"
          >
            <span class="legend-dot" :class="roomStatusMap[id]?.status || 'idle'" />
            {{ label }}
          </button>
        </div>
      </div>

      <NGrid cols="1 s:2 m:3 l:5" responsive="screen" :x-gap="12" :y-gap="12">
        <NGridItem>
          <StatCard :title="t('pages.dashboard.stats.sessions')" :value="stats.sessionCount" :icon="ChatbubblesOutline" color="#3dd68c" :bar-value="statBars.sessions" />
        </NGridItem>
        <NGridItem>
          <StatCard :title="t('pages.dashboard.stats.cronJobs')" :value="stats.cronCount" :icon="CalendarOutline" color="#f0a020" :bar-value="statBars.cronJobs" />
        </NGridItem>
        <NGridItem>
          <StatCard :title="t('pages.dashboard.stats.models')" :value="stats.modelCount" :icon="SparklesOutline" color="#2080f0" :bar-value="statBars.models" />
        </NGridItem>
        <NGridItem>
          <StatCard :title="t('pages.dashboard.stats.skills')" :value="stats.installedSkills" :icon="ExtensionPuzzleOutline" color="#8b5cf6" :bar-value="statBars.skills" />
        </NGridItem>
        <NGridItem>
          <StatCard :title="t('pages.dashboard.stats.totalTokens')" :value="tokenTotalDisplay" :icon="FlashOutline" color="#d03050" :bar-value="statBars.tokens" />
        </NGridItem>
      </NGrid>

      <NCard :title="t('pages.dashboard.cards.kpis')" class="dashboard-card">
        <div class="kpi-grid">
          <div v-for="(kpi, idx) in usageKpis" :key="kpi.key" class="kpi-card" :style="{ '--kpi-accent': kpiColors[idx % kpiColors.length] }">
            <NText depth="3" class="pixel-text kpi-label">{{ kpi.label }}</NText>
            <div class="kpi-value pixel-text">{{ kpi.value }}</div>
            <NText depth="3" class="kpi-hint">{{ kpi.hint }}</NText>
          </div>
        </div>
      </NCard>

      <NGrid cols="1 l:3" responsive="screen" :x-gap="12" :y-gap="12">
        <NGridItem :span="2" class="usage-trend-item">
          <NCard :title="t('pages.dashboard.cards.trend')" class="dashboard-card usage-trend-card">
            <template #header-extra>
              <NSpace :size="8" align="center">
                <NTag size="small" :bordered="false" round type="info">
                  {{ usageStartDate }} ~ {{ usageEndDate }}
                </NTag>
                <NTag size="small" :bordered="false" round>
                  {{ usageMode === 'tokens' ? tokenTotalDisplay : costTotalDisplay }}
                </NTag>
              </NSpace>
            </template>

            <div class="trend-chart-panel">
              <template v-if="trendGeometry.points.length">
                <div class="trend-chart-canvas">
                  <svg
                    ref="trendSvgRef"
                    class="trend-chart-svg"
                    :viewBox="`0 0 ${trendGeometry.width} ${trendGeometry.height}`"
                    preserveAspectRatio="none"
                    @mousemove="handleTrendMouseMove"
                    @mouseleave="clearTrendHover"
                  >
                    <g v-for="guide in trendGeometry.guides" :key="`guide-${guide.ratio}`">
                      <line
                        :x1="trendGeometry.left"
                        :y1="guide.y"
                        :x2="trendGeometry.left + trendGeometry.usableWidth"
                        :y2="guide.y"
                        class="trend-grid-line"
                      />
                      <text
                        x="4"
                        :y="guide.y + 4"
                        class="trend-grid-label"
                      >
                        {{ formatUsageValue(guide.value) }}
                      </text>
                    </g>

                    <path
                      v-if="trendGeometry.areaPath"
                      class="trend-area"
                      :d="trendGeometry.areaPath"
                    />
                    <polyline
                      v-if="trendGeometry.polyline"
                      class="trend-line"
                      :points="trendGeometry.polyline"
                    />
                    <line
                      v-if="hoveredTrendPoint"
                      class="trend-hover-line"
                      :x1="hoveredTrendPoint.x"
                      :y1="trendGeometry.top"
                      :x2="hoveredTrendPoint.x"
                      :y2="trendGeometry.top + trendGeometry.usableHeight"
                    />
                    <circle
                      v-for="point in trendGeometry.points"
                      :key="`point-${point.date}`"
                      class="trend-point"
                      :class="{ 'trend-point-active': hoveredTrendPoint?.date === point.date }"
                      :cx="point.x"
                      :cy="point.y"
                      :r="hoveredTrendPoint?.date === point.date ? 6 : 3.5"
                    />
                  </svg>

                  <div v-if="hoveredTrendPoint && trendTooltipStyle" class="trend-tooltip" :style="trendTooltipStyle">
                    {{ hoveredTrendText }}
                  </div>
                </div>

                <div class="trend-axis-note">
                  <span>{{ trendAxisLabels.start }}</span>
                  <span>{{ trendAxisLabels.mid }}</span>
                  <span>{{ trendAxisLabels.end }}</span>
                </div>
              </template>
              <div v-else class="daily-empty">{{ t('pages.dashboard.trend.empty') }}</div>
            </div>
          </NCard>
        </NGridItem>

        <NGridItem :span="1" class="usage-structure-item">
          <NCard :title="t('pages.dashboard.cards.structure')" class="dashboard-card usage-structure-card">
            <NSpace justify="space-between" align="center" style="margin-bottom: 8px;">
              <NText depth="3">{{ usageMode === 'tokens' ? t('pages.dashboard.usage.totalTokens') : t('pages.dashboard.usage.totalCost') }}</NText>
              <NText strong>{{ usageMode === 'tokens' ? tokenTotalDisplay : costTotalDisplay }}</NText>
            </NSpace>

            <div class="segment-track">
              <div
                v-for="segment in usageSegments"
                :key="segment.key"
                class="segment-item"
                :style="{
                  width: `${Math.max((segment.value / segmentTotal) * 100, segment.value > 0 ? 4 : 0)}%`,
                  background: segment.color,
                }"
              />
            </div>

            <div class="segment-list">
              <div v-for="segment in usageSegments" :key="`${segment.key}-row`" class="segment-row">
                <div class="segment-row-label">
                  <span class="segment-dot" :style="{ background: segment.color }" />
                  <span>{{ segment.label }}</span>
                </div>
                <NText>{{ formatUsageValue(segment.value) }}</NText>
              </div>
            </div>

            <NText depth="3" style="display: block; margin-top: 8px; font-size: 12px;">
              {{ t('pages.dashboard.usage.missingCostEntries', { count: usageTotals.missingCostEntries }) }}
            </NText>
          </NCard>
        </NGridItem>
      </NGrid>

      <NCard :title="t('pages.dashboard.cards.top')" class="dashboard-card">
        <NGrid cols="1 m:3" responsive="screen" :x-gap="12" :y-gap="12">
          <NGridItem>
            <div class="top-pane-card">
              <div class="top-title">{{ t('pages.dashboard.top.models') }}</div>
              <div v-if="topModels.length" class="top-list">
                <div v-for="item in topModels" :key="`${item.provider || '-'}:${item.model || '-'}`" class="top-row">
                  <div class="top-row-main">
                    <span>{{ item.provider ? `${item.provider}/${item.model || '-'}` : item.model || '-' }}</span>
                    <span>{{ usageMode === 'tokens' ? formatCompactNumber(item.totals.totalTokens) : formatUsd(item.totals.totalCost) }}</span>
                  </div>
                  <div class="top-row-bar">
                    <div
                      class="top-row-bar-inner top-row-bar-inner-model"
                      :style="{ width: topBarWidth(usageMetric(item.totals), topModelMax) }"
                    />
                  </div>
                </div>
              </div>
              <div v-else class="top-empty">{{ t('common.empty') }}</div>
            </div>
          </NGridItem>

          <NGridItem>
            <div class="top-pane-card">
              <div class="top-title">{{ t('pages.dashboard.top.providers') }}</div>
              <div v-if="topProviders.length" class="top-list">
                <div v-for="item in topProviders" :key="item.provider || 'unknown-provider'" class="top-row">
                  <div class="top-row-main">
                    <span>{{ item.provider || '-' }}</span>
                    <span>{{ usageMode === 'tokens' ? formatCompactNumber(item.totals.totalTokens) : formatUsd(item.totals.totalCost) }}</span>
                  </div>
                  <div class="top-row-bar">
                    <div
                      class="top-row-bar-inner top-row-bar-inner-provider"
                      :style="{ width: topBarWidth(usageMetric(item.totals), topProviderMax) }"
                    />
                  </div>
                </div>
              </div>
              <div v-else class="top-empty">{{ t('common.empty') }}</div>
            </div>
          </NGridItem>

          <NGridItem>
            <div class="top-pane-card">
              <div class="top-title">{{ t('pages.dashboard.top.tools') }}</div>
              <div v-if="topTools.length" class="top-list">
                <div v-for="item in topTools" :key="item.name" class="top-row">
                  <div class="top-row-main">
                    <span>{{ item.name }}</span>
                    <span>{{ item.count }}</span>
                  </div>
                  <div class="top-row-bar">
                    <div
                      class="top-row-bar-inner top-row-bar-inner-tool"
                      :style="{ width: topBarWidth(item.count, topToolMax) }"
                    />
                  </div>
                </div>
              </div>
              <div v-else class="top-empty">{{ t('common.empty') }}</div>
            </div>
          </NGridItem>
        </NGrid>
      </NCard>

    </div>
  </NSpin>
</template>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dashboard-card {
  border-radius: 0;
}

.dashboard-hero {
  border-radius: 0;
  background:
    radial-gradient(circle at 84% 16%, rgba(24, 160, 88, 0.22), transparent 36%),
    linear-gradient(120deg, var(--bg-card), rgba(42, 127, 255, 0.08));
  border: 1px solid rgba(42, 127, 255, 0.18);
}

.dashboard-hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.dashboard-hero-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 400;
  line-height: 1.3;
  letter-spacing: 0.02em;
  color: var(--accent);
}

.dashboard-hero-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.55;
}

.dashboard-filters-row {
  align-items: center;
}

.usage-date-input {
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--ink);
  border-radius: 0;
  height: 30px;
  padding: 0 10px;
  font-family: var(--font-display);
  font-size: 13px;
}

.usage-date-sep {
  font-family: var(--font-display);
  font-size: 13px;
  color: var(--muted);
}

.usage-trend-item,
.usage-structure-item {
  display: flex;
}

.usage-trend-card,
.usage-structure-card {
  width: 100%;
  height: 100%;
}

.usage-trend-card :deep(.n-card__content),
.usage-structure-card :deep(.n-card__content) {
  height: 100%;
}

.usage-structure-card :deep(.n-card__content) {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.kpi-card {
  border: 1px solid var(--line);
  border-radius: 0;
  background: linear-gradient(130deg, rgba(42, 127, 255, 0.08), rgba(24, 160, 88, 0.06));
  padding: 10px 12px 10px 16px;
  position: relative;
  overflow: hidden;
  transition: border-color var(--ease-fast), box-shadow var(--ease-fast);
}
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 3px;
  height: 100%;
  background: var(--kpi-accent, var(--accent));
  opacity: 0.6;
}
.kpi-card:hover {
  border-color: var(--line-strong);
  box-shadow: 0 0 12px var(--accent-glow);
}

.kpi-label {
  font-size: 10px !important;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.kpi-value {
  margin: 4px 0;
  font-size: 22px;
  font-weight: 400;
  line-height: 1.2;
  color: var(--kpi-accent, var(--accent));
  text-shadow: 0 0 12px var(--accent-glow);
}

.kpi-hint {
  font-size: 12px !important;
}

.trend-chart-panel {
  border: 1px solid var(--line);
  border-radius: 0;
  padding: 10px;
  background: linear-gradient(180deg, rgba(42, 127, 255, 0.06), transparent 38%);
}

.trend-chart-canvas {
  position: relative;
}

.trend-chart-svg {
  width: 100%;
  height: 250px;
  cursor: crosshair;
}

.trend-grid-line {
  stroke: var(--border-color);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}

.trend-grid-label {
  fill: var(--text-secondary);
  font-size: 11px;
}

.trend-area {
  fill: rgba(42, 127, 255, 0.2);
}

.trend-line {
  fill: none;
  stroke: #2a7fff;
  stroke-width: 2.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.trend-hover-line {
  stroke: rgba(42, 127, 255, 0.6);
  stroke-width: 1;
  stroke-dasharray: 3 3;
}

.trend-point {
  fill: #18a058;
  stroke: rgba(24, 160, 88, 0.3);
  stroke-width: 3;
}

.trend-point-active {
  stroke: rgba(24, 160, 88, 0.45);
  stroke-width: 6;
}

.trend-tooltip {
  position: absolute;
  width: 260px;
  height: 32px;
  padding: 6px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 0;
  background: var(--bg-deepest);
  color: var(--ink);
  font-family: var(--font-display);
  font-size: 13px;
  line-height: 20px;
  pointer-events: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-shadow: 0 0 16px var(--accent-glow);
}

.trend-axis-note {
  margin-top: 6px;
  display: flex;
  justify-content: space-between;
  color: var(--text-secondary);
  font-size: 12px;
}

.daily-empty {
  font-family: var(--font-display);
  font-size: 12px;
  color: var(--dim);
  padding: 10px 0;
}

.segment-track {
  width: 100%;
  height: 10px;
  border-radius: 0;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid var(--line);
  display: flex;
}

.segment-item {
  min-width: 0;
  height: 100%;
}

.segment-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.segment-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.segment-row-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

.segment-dot {
  width: 8px;
  height: 8px;
  border-radius: 0;
}

.top-title {
  font-family: var(--font-display);
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.top-pane-card {
  border: 1px solid var(--line);
  border-radius: 0;
  background: var(--bg-primary);
  padding: 10px;
  height: 100%;
  position: relative;
  overflow: hidden;
}
.top-pane-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 3px;
  height: 100%;
  background: var(--accent);
  opacity: 0.3;
}

.top-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.top-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.top-row-main {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
}

.top-row-main span:first-child {
  max-width: 70%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-row-bar {
  height: 6px;
  border-radius: 0;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--line);
  overflow: hidden;
}

.top-row-bar-inner {
  height: 100%;
  border-radius: 0;
  min-width: 0;
}

.top-row-bar-inner-model {
  background: linear-gradient(90deg, rgba(42, 127, 255, 0.9), rgba(42, 127, 255, 0.45));
}

.top-row-bar-inner-provider {
  background: linear-gradient(90deg, rgba(24, 160, 88, 0.9), rgba(24, 160, 88, 0.45));
}

.top-row-bar-inner-tool {
  background: linear-gradient(90deg, rgba(240, 160, 32, 0.95), rgba(240, 160, 32, 0.45));
}

.top-empty {
  font-family: var(--font-display);
  font-size: 12px;
  color: var(--dim);
}

/* ── Museum Section ── */
.museum-section {
  position: relative;
  border-radius: var(--radius-lg);
  background: var(--bg-deepest);
  overflow: hidden;
}

/* ── Expand / Collapse transition ── */
.museum-section.expanded {
  position: fixed;
  inset: 0;
  z-index: 1000;
  border-radius: 0;
  background: rgba(0, 0, 0, 0.92);
  display: flex;
  flex-direction: column;
  padding: 16px;
  animation: museum-expand-in 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes museum-expand-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.museum-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px 8px;
  background: linear-gradient(180deg, var(--panel-strong), transparent);
}

.museum-section.expanded .museum-header {
  flex-shrink: 0;
  background: var(--panel-strong);
  padding: 12px 20px;
  border-bottom: 1px solid var(--line);
}

.museum-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.museum-title {
  font-family: var(--font-display, 'Courier New', monospace);
  font-size: 13px;
  color: var(--accent);
  text-shadow: 0 0 8px var(--accent-glow);
  letter-spacing: 0.05em;
}

.museum-section.expanded .museum-title {
  font-size: 16px;
}

.museum-status {
  display: flex;
  align-items: center;
  gap: 6px;
}

.museum-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--dim);
}

.museum-status-dot.live {
  background: var(--tone-active);
  box-shadow: 0 0 6px var(--tone-active);
}

.museum-status-dot.dead {
  background: var(--dim);
}

.museum-status-dot.mock {
  background: #f0a020;
  box-shadow: 0 0 6px #f0a020;
  animation: mock-pulse 2s ease-in-out infinite;
}

@keyframes mock-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.museum-status-text {
  font-family: var(--font-display, monospace);
  font-size: 11px;
  color: var(--dim);
}

/* Expand / collapse toggle */
.museum-expand-btn {
  width: 30px;
  height: 30px;
  border: 1px solid var(--line);
  border-radius: 0;
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--ease-fast);
  font-size: 16px;
  line-height: 1;
}

.museum-expand-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--panel-strong);
  box-shadow: 0 0 8px var(--accent-glow);
}

.expand-icon {
  font-family: monospace;
  font-size: 16px;
  line-height: 1;
}

/* Frame — holds the Phaser canvas */
.museum-frame {
  position: relative;
  width: calc(100% - 24px);
  margin: 0 12px;
  aspect-ratio: 16 / 9;
  max-height: 560px;
  border: 2px solid var(--line-strong);
  background: var(--bg-deepest);
  box-shadow:
    inset 0 0 30px rgba(0, 0, 0, 0.4),
    0 0 20px var(--accent-glow);
}

/* Pixel-art corner brackets */
.museum-frame::before,
.museum-frame::after {
  content: '';
  position: absolute;
  width: 16px;
  height: 16px;
  pointer-events: none;
  z-index: 2;
}
.museum-frame::before {
  top: 4px;
  left: 4px;
  border-top: 2px solid var(--accent);
  border-left: 2px solid var(--accent);
  opacity: 0.6;
}
.museum-frame::after {
  bottom: 4px;
  right: 4px;
  border-bottom: 2px solid var(--accent);
  border-right: 2px solid var(--accent);
  opacity: 0.6;
}

.museum-frame.expanded {
  flex: 1;
  width: 100%;
  margin: 12px 0;
  max-height: none;
  aspect-ratio: auto;
  border-width: 1px;
  box-shadow: 0 0 40px var(--accent-glow);
}

.museum-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  background: var(--bg-deepest);
  z-index: 5;
}

.pixel-spinner {
  display: flex;
  gap: 6px;
}
.pixel-spinner span {
  width: 8px;
  height: 8px;
  background: var(--accent);
  opacity: 0.2;
  animation: pixel-spin-step 1s steps(1) infinite;
}
.pixel-spinner span:nth-child(1) { animation-delay: 0s; }
.pixel-spinner span:nth-child(2) { animation-delay: 0.25s; }
.pixel-spinner span:nth-child(3) { animation-delay: 0.5s; }
.pixel-spinner span:nth-child(4) { animation-delay: 0.75s; }

@keyframes pixel-spin-step {
  0%, 24.9%  { opacity: 1; background: var(--accent); }
  25%, 100%  { opacity: 0.2; background: var(--dim); }
}

.museum-loading-text {
  font-family: var(--font-display, monospace);
  font-size: 14px;
  color: var(--dim);
  animation: museum-blink 1.2s ease-in-out infinite;
}

@keyframes museum-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* ── Room Legend ── */
.museum-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 16px 14px;
  justify-content: center;
}

.legend-chip {
  font-family: var(--font-display, monospace);
  font-size: 10px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: 0;
  background: var(--panel);
  color: var(--muted);
  cursor: pointer;
  transition: all var(--ease-fast);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--panel-strong);
  box-shadow: 0 0 8px var(--accent-glow);
  transform: translateY(-1px);
}

.legend-chip:active {
  transform: translateY(0);
}

.legend-dot {
  width: 6px;
  height: 6px;
  display: inline-block;
  flex-shrink: 0;
}

.legend-dot.idle {
  background: var(--dim);
}

.legend-dot.active {
  background: var(--tone-active);
  box-shadow: 0 0 4px var(--tone-active);
}

.legend-dot.alert {
  background: var(--tone-danger);
  box-shadow: 0 0 4px var(--tone-danger);
}

.legend-dot.offline {
  background: var(--dim);
  opacity: 0.5;
}

/* Legend chip status border highlight */
.legend-chip.active {
  border-color: var(--tone-active);
  color: var(--tone-active);
}

.legend-chip.alert {
  border-color: var(--tone-danger);
  color: var(--tone-danger);
}

@media (max-width: 900px) {
  .museum-frame {
    max-height: 380px;
    margin: 0 8px;
    width: calc(100% - 16px);
  }

  .museum-title {
    font-size: 11px;
  }

  .legend-chip {
    font-size: 9px;
    padding: 3px 7px;
  }
}

@media (max-width: 560px) {
  .museum-frame {
    max-height: 240px;
  }
}

@media (max-width: 900px) {
  .dashboard-filters-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
