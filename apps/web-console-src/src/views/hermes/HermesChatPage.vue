<script setup lang="ts">
import { ref, shallowRef, computed, reactive, nextTick, onMounted, onUnmounted, watch, h } from 'vue'
import {
  NCard,
  NGrid,
  NGridItem,
  NInput,
  NButton,
  NIcon,
  NText,
  NTag,
  NSpin,
  NEmpty,
  NSelect,
  NAlert,
  NSwitch,
  NModal,
  NForm,
  NFormItem,
  NPopconfirm,
  NSpace,
  NTooltip,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import {
  SendOutline,
  StopCircleOutline,
  RefreshOutline,
  ChevronBackOutline,
  ChevronForwardOutline,
  CopyOutline,
  ChatbubblesOutline,
  VolumeHighOutline,
  StopOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useHermesChatStore } from '@/stores/hermes/chat'
import { useHermesSessionStore } from '@/stores/hermes/session'
import { useHermesModelStore } from '@/stores/hermes/model'
import { useHermesSkillStore } from '@/stores/hermes/skill'
import { useHermesConnectionStore } from '@/stores/hermes/connection'
import { useHermesConfigStore } from '@/stores/hermes/config'
import { useEdgeTTS } from '@/composables/useEdgeTTS'
import { useTTSSettings } from '@/composables/useTTSSettings'
import { useHermesCommands } from '@/composables/useHermesCommands'
import { renderSimpleMarkdown } from '@/utils/markdown'
import type { HermesMessage, ModelSelection } from '@/api/hermes/types'
import type { CommandItem, ToolCallItemView, RenderMessage, StructuredMessageView } from '@/api/hermes/chat-types'
import { getToolDisplayName, parseToolMessage, parseStructuredMessage, formatToolDuration } from '@/utils/hermes-tool-parser'
import { useQuickReplies, type QuickReplyItem } from '@/composables/useQuickReplies'
import HermesChatCommandPanel from '@/components/hermes/HermesChatCommandPanel.vue'

const { t, locale } = useI18n()
const message = useMessage()
const chatStore = useHermesChatStore()
const sessionStore = useHermesSessionStore()
const modelStore = useHermesModelStore()
const skillStore = useHermesSkillStore()
const connStore = useHermesConnectionStore()
const configStore = useHermesConfigStore()

// ---- Constants ----

const BOTTOM_GAP = 32

// ---- State ----

const inputText = ref('')
const selectedModelSelection = ref<ModelSelection | null>(null)
const messageListRef = ref<HTMLElement | null>(null)

// Auto-scroll
const autoFollowBottom = ref(true)
const showScrollToBottomBtn = ref(false)
let pendingForceScroll = false
let pendingScroll = false
let destroyed = false

// Token usage tracking
const lastTokenUsage = ref<{ input: number; output: number; total: number } | null>(null)

// Sidebar collapse
const sideCollapsed = ref(false)

// Copy state
const copiedMessageId = ref<string | null>(null)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

// TTS state
const playingMessageId = ref<string | null>(null)
const { speak: ttsSpeak, stop: ttsStop, isLoading: ttsIsLoading } = useEdgeTTS({
  voice: 'zh-CN',
})
const { settings: ttsSettings } = useTTSSettings()

// Quick replies
const {
  quickReplies,
  quickReplySearch,
  showQuickReplyModal,
  quickReplyModalMode,
  editingQuickReplyId,
  quickReplyForm,
  filteredQuickReplies,
  loadQuickReplies,
  openCreateQuickReply,
  openEditQuickReply,
  handleDeleteQuickReply,
  handleInsertQuickReply,
  handleSendQuickReply,
  handleSaveQuickReply,
} = useQuickReplies(inputText, message, {
  storageKey: 'hermes_chat_quick_replies_v1',
  i18nPrefix: 'pages.hermesChat.quickReplies',
})

// Role filter
const roleFilter = ref<'all' | 'user' | 'assistant' | 'system'>('all')

// ---- Commands (Hermes Agent COMMAND_REGISTRY) ----

const {
  commands,
  filteredCommands,
  showCommandPanel,
  commandFilter,
  selectedCommandIndex,
  handleInputUpdate,
  handleCommandSelect,
  handleCommandKeydown,
} = useHermesCommands({
  t,
  message,
  inputText,
  chatStore,
  modelStore,
  skillStore,
  connStore,
  selectedModelSelection,
  selectedSession,
  lastTokenUsage,
  handleNewSession,
})

// ---- Computed ----



const isConnected = computed(() => connStore.hermesConnected)

const messageCount = computed(() => chatStore.messages.length)

const roleFilterOptions = computed<SelectOption[]>(() => [
  { label: t('pages.hermesChat.filters.all'), value: 'all' },
  { label: t('pages.hermesChat.filters.user'), value: 'user' },
  { label: t('pages.hermesChat.filters.assistant'), value: 'assistant' },
  { label: t('pages.hermesChat.filters.system'), value: 'system' },
])

// Token usage tags
const tokenMetricTags = computed(() => {
  const usage = lastTokenUsage.value
  if (!usage) return []
  return [
    { key: 'total', label: t('pages.hermesChat.tokenTotal'), value: formatTokenCount(usage.total), highlight: true },
    { key: 'input', label: t('pages.hermesChat.tokenInput'), value: formatTokenCount(usage.input), highlight: false },
    { key: 'output', label: t('pages.hermesChat.tokenOutput'), value: formatTokenCount(usage.output), highlight: false },
  ]
})

// Streaming text display
const displayMessages = computed(() => {
  const msgs = chatStore.messages
  if (msgs.length === 0) return msgs
  if (chatStore.streaming && msgs[msgs.length - 1]!.role === 'assistant') {
    return msgs.map((m, i) => {
      if (i === msgs.length - 1) {
        return { ...m, content: chatStore.streamingText || m.content }
      }
      return m
    })
  }
  return msgs
})

// Role-filtered messages
const filteredMessages = computed(() => {
  if (roleFilter.value === 'all') return displayMessages.value
  return displayMessages.value.filter((m) => m.role === roleFilter.value)
})


const renderMessageEntries = computed<RenderMessage[]>(() => {
  const list = filteredMessages.value
  const rendered: RenderMessage[] = []

  for (let idx = 0; idx < list.length; idx += 1) {
    const item = list[idx]
    if (!item) continue

    if (item.role === 'tool') {
      const parsedContent = parseToolMessage(item.content)
      const rawToolName = item.toolName || parsedContent?.toolName || 'Tool'
      const toolName = getToolDisplayName(rawToolName)
      const isError = item.isError || parsedContent?.isError
      const outputContent = parsedContent?.output || item.content || ''
      
      const structured: StructuredMessageView = {
        toolCalls: [],
        thinkings: [],
        toolResults: [{
          id: item.toolCallId,
          name: toolName,
          status: isError ? 'error' : undefined,
          content: outputContent,
        }],
        plainTexts: [],
      }
      rendered.push({
        key: item.id || `tool-${idx}`,
        item,
        structured,
      })
      continue
    }

    // 处理助手消息：检查消息对象上的 tool_calls 字段
    if (item.role === 'assistant') {
      const rawMsg = item as unknown as Record<string, unknown>
      const toolCalls = rawMsg.tool_calls as Array<{ 
        id?: string
        function?: { name?: string; arguments?: string | Record<string, unknown> }
        name?: string
        arguments?: string | Record<string, unknown>
      }> | null
      
      // 先从 content 解析结构化消息
      const contentStructured = parseStructuredMessage(item.content)
      
      // 如果消息对象有 tool_calls，合并到结构化视图中
      if (toolCalls && toolCalls.length > 0) {
        const toolCallViews: ToolCallItemView[] = toolCalls.map(tc => {
          const args = tc.function?.arguments || tc.arguments
          let argumentsJson: string | undefined
          if (args) {
            if (typeof args === 'string') {
              argumentsJson = args
            } else {
              try {
                argumentsJson = JSON.stringify(args, null, 2)
              } catch {
                argumentsJson = String(args)
              }
            }
          }
          return {
            id: tc.id,
            name: getToolDisplayName(tc.function?.name || tc.name || 'unknown'),
            argumentsJson,
          }
        })
        
        // 合并 content 解析的结果和消息对象的 tool_calls
        const merged: StructuredMessageView = {
          toolCalls: [...toolCallViews, ...(contentStructured?.toolCalls || [])],
          thinkings: contentStructured?.thinkings || [],
          toolResults: contentStructured?.toolResults || [],
          plainTexts: contentStructured?.plainTexts || [],
        }
        rendered.push({
          key: item.id || `assistant-${idx}`,
          item,
          structured: merged,
        })
        continue
      }
    }

    const structured = parseStructuredMessage(item.content)
    rendered.push({
      key: item.id || `${item.role}-${idx}`,
      item,
      structured,
    })
  }

  return rendered
})

// Character count
const inputCharCount = computed(() => inputText.value.length)

// Session options for NSelect
const sessionOptions = computed(() =>
  sessionStore.sessions.map((s) => ({
    label: `[${s.id}] ${s.title || s.id}`,
    value: s.id,
  })),
)

// Platform display configuration
const platformConfig: Record<string, { color: string; label: string; icon?: string }> = {
  telegram: { color: '#0088cc', label: 'Telegram' },
  discord: { color: '#5865F2', label: 'Discord' },
  slack: { color: '#4A154B', label: 'Slack' },
  whatsapp: { color: '#25D366', label: 'WhatsApp' },
  signal: { color: '#3A76F0', label: 'Signal' },
  matrix: { color: '#0DBD8B', label: 'Matrix' },
  mattermost: { color: '#0058CC', label: 'Mattermost' },
  email: { color: '#EA4335', label: 'Email' },
  sms: { color: '#6B7280', label: 'SMS' },
  dingtalk: { color: '#0089FF', label: '钉钉' },
  feishu: { color: '#3370FF', label: '飞书' },
  wecom: { color: '#2B7D39', label: '企业微信' },
  wechat: { color: '#07C160', label: '微信' },
  cli: { color: '#6B7280', label: 'CLI' },
  tui: { color: '#6B7280', label: 'TUI' },
  webui: { color: '#3B82F6', label: 'Web' },
  api: { color: '#8B5CF6', label: 'API' },
}

function getPlatformInfo(platform?: string) {
  if (!platform) return null
  const key = platform.toLowerCase()
  return platformConfig[key] || { color: '#6B7280', label: platform }
}

function renderSessionLabel(option: { label: string; value: string }) {
  const session = sessionStore.sessions.find((s) => s.id === option.value)
  const fullText = session ? `[${session.id}] ${session.title || session.id}` : option.label
  const platformInfo = session?.platform ? getPlatformInfo(session.platform) : null
  
  if (platformInfo) {
    return h(
      'div',
      {
        style: {
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          overflow: 'hidden',
        },
      },
      [
        h('span', {
          style: {
            display: 'inline-block',
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            backgroundColor: platformInfo.color,
            flexShrink: '0',
          },
        }),
        h(
          'span',
          {
            title: fullText,
            style: {
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: '1',
            },
          },
          option.label,
        ),
        h(
          'span',
          {
            style: {
              fontSize: '10px',
              color: '#999',
              flexShrink: '0',
            },
          },
          platformInfo.label,
        ),
      ],
    )
  }
  
  return h(
    'span',
    {
      title: fullText,
      style: {
        display: 'block',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        maxWidth: '100%',
      },
    },
    option.label,
  )
}

// Selected session metadata
const selectedSession = computed(() => {
  if (!chatStore.currentSessionId) return null
  return sessionStore.sessions.find((s) => s.id === chatStore.currentSessionId) || null
})

// Stats
const stats = computed(() => {
  const list = displayMessages.value
  let user = 0
  let assistant = 0
  let system = 0

  for (const msg of list) {
    if (msg.role === 'user') user += 1
    else if (msg.role === 'assistant') assistant += 1
    else if (msg.role === 'system') system += 1
  }

  const last = list.length > 0 ? list[list.length - 1] : null
  return {
    total: list.length,
    user,
    assistant,
    system,
    lastMessageAt: last?.timestamp ? formatRelativeTime(last.timestamp) : '-',
  }
})

// ---- Lifecycle ----

onMounted(async () => {
  loadQuickReplies()

  if (!isConnected.value) {
    await connStore.connect()
  }
  try {
    await sessionStore.fetchSessions()
  } catch { /* ignore */ }
  try {
    await modelStore.fetchModels()
  } catch { /* ignore */ }
  try {
    await configStore.fetchConfig()
  } catch { /* ignore */ }

  // 同步当前模型选择
  modelStore.syncCurrentModelSelectionFromConfig()
  if (modelStore.currentModelSelection) {
    selectedModelSelection.value = modelStore.currentModelSelection
  }

  // Auto-select first session if none selected
  if (!chatStore.currentSessionId && sessionStore.sessions.length > 0) {
    const firstSession = sessionStore.sessions[0]
    if (firstSession) {
      await handleSelectSession(firstSession.id)
    }
  }
})

onUnmounted(() => {
  destroyed = true
  pendingForceScroll = false
  pendingScroll = false
  if (copiedTimer) {
    clearTimeout(copiedTimer)
    copiedTimer = null
  }
  // 停止自动刷新
  chatStore.stopAutoRefresh()
  // 停止 TTS 播放
  stopTTS()
})

// ---- Scroll Logic ----

function isNearBottom(): boolean {
  const el = messageListRef.value
  if (!el) return true
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  return distance <= BOTTOM_GAP
}

function handleMessagesScroll() {
  const near = isNearBottom()
  autoFollowBottom.value = near
  showScrollToBottomBtn.value = !near
}

function scrollToBottom(options?: { force?: boolean }) {
  const el = messageListRef.value
  if (!el) return

  const force = options?.force ?? false
  if (!force && !autoFollowBottom.value) return

  el.scrollTop = el.scrollHeight
}

function requestScrollToBottom(options?: { force?: boolean }) {
  const force = options?.force ?? false
  if (!force && !autoFollowBottom.value) return
  if (force) pendingForceScroll = true
  if (pendingScroll) return

  pendingScroll = true
  const schedule =
    typeof queueMicrotask === 'function'
      ? queueMicrotask
      : (fn: () => void) => Promise.resolve().then(fn)
  schedule(() => {
    pendingScroll = false
    if (destroyed) return
    const forceNow = pendingForceScroll
    pendingForceScroll = false
    scrollToBottom({ force: forceNow })
  })
}

// Watch messages length
watch(
  () => chatStore.messages.length,
  () => {
    requestScrollToBottom()
  },
)

// Watch streaming text
watch(
  () => chatStore.streamingText,
  () => {
    if (chatStore.streaming) {
      requestScrollToBottom()
    }
  },
)

// ---- Markdown Rendering ----

function renderChatMarkdown(content: string, role: HermesMessage['role']): string {
  if (!content || !content.trim()) return ''
  if (role === 'user') {
    return content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br/>')
  }
  return renderSimpleMarkdown(content)
}

// ---- Token Usage ----

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(
    Math.max(0, value),
  )
}

watch(
  () => chatStore.streaming,
  (newVal, oldVal) => {
    if (oldVal === true && newVal === false && !chatStore.error) {
      const lastAssistant = [...chatStore.messages]
        .reverse()
        .find((m) => m.role === 'assistant')
      if (lastAssistant && lastAssistant.usage) {
        const usage = lastAssistant.usage
        lastTokenUsage.value = {
          input: typeof usage.input === 'number' ? usage.input : 0,
          output: typeof usage.output === 'number' ? usage.output : 0,
          total: typeof usage.total === 'number' ? usage.total : 0,
        }
      }
    }
  },
)

// ---- Actions ----

function handleSend() {
  const text = inputText.value.trim()
  if (!text || chatStore.streaming) return

  // All commands starting with / should be sent directly to Hermes
  // Frontend doesn't need to handle any command processing

  inputText.value = ''
  showCommandPanel.value = false
  commandFilter.value = ''

  chatStore.sendMessage(text, {
    modelSelection: selectedModelSelection.value || undefined,
  }).catch(() => {
    message.error(chatStore.error || t('pages.hermesChat.sendFailed'))
  })

  // Refresh session list after sending
  nextTick(() => {
    sessionStore.fetchSessions().catch(() => {})
  })
}

function handleStop() {
  chatStore.stopGeneration()
}

function handleNewSession() {
  chatStore.clearMessages()
  lastTokenUsage.value = null
  autoFollowBottom.value = true
  showScrollToBottomBtn.value = false
  nextTick(() => requestScrollToBottom({ force: true }))
}

async function handleSelectSession(sessionId: string) {
  try {
    const session = sessionStore.sessions.find((s) => s.id === sessionId)
    await chatStore.loadSessionMessages(sessionId, session?.model)
    lastTokenUsage.value = null
    autoFollowBottom.value = true
    showScrollToBottomBtn.value = false
    nextTick(() => requestScrollToBottom({ force: true }))
    // 启动自动刷新，实现多终端联动
    chatStore.startAutoRefresh()
  } catch {
    message.error(t('pages.hermesChat.loadMessagesFailed'))
  }
}

async function handleRefreshChatData() {
  try {
    await sessionStore.fetchSessions()
    if (chatStore.currentSessionId) {
      const session = sessionStore.sessions.find((s) => s.id === chatStore.currentSessionId)
      await chatStore.loadSessionMessages(chatStore.currentSessionId, session?.model)
      autoFollowBottom.value = true
      nextTick(() => requestScrollToBottom({ force: true }))
    }
  } catch {
    // ignore
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (showCommandPanel.value) {
    handleCommandKeydown(e)
    return
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function getRoleTagType(role: HermesMessage['role']): 'info' | 'success' | 'warning' | 'error' {
  switch (role) {
    case 'user': return 'info'
    case 'assistant': return 'success'
    case 'tool': return 'warning'
    case 'system': return 'error'
    default: return 'info'
  }
}

function getRoleLabel(role: HermesMessage['role']): string {
  switch (role) {
    case 'user': return t('pages.hermesChat.roleUser')
    case 'assistant': return t('pages.hermesChat.roleAssistant')
    case 'tool': return t('pages.hermesChat.roleTool')
    case 'system': return t('pages.hermesChat.roleSystem')
    default: return role
  }
}

// ---- Tool Call Expand/Collapse ----

const expandedToolCalls = shallowRef(new Set<string>())
const expandedToolResults = shallowRef(new Set<string>())
const showToolDetails = ref(false)

// ---- Hermes Status Text ----

const hermesStatusText = computed(() => {
  if (chatStore.streaming) {
    const toolCalls = chatStore.activeToolCalls
    if (toolCalls.length > 0) {
      const runningTools = toolCalls.filter(tc => tc.status === 'running')
      if (runningTools.length > 0) {
        const names = runningTools.map(tc => `${tc.emoji || '🔧'} ${tc.toolName}`).join(', ')
        return `${t('pages.hermesChat.toolCall')}: ${names}`
      }
    }
    return t('pages.hermesChat.streaming')
  }
  // 显示"本轮完成"当有消息且不在流式传输中
  if (chatStore.messages.length > 0) {
    return t('pages.hermesChat.roundComplete')
  }
  return ''
})

const hermesStatusTagType = computed((): 'default' | 'success' | 'error' | 'warning' | 'info' => {
  if (chatStore.streaming) {
    if (chatStore.activeToolCalls.some(tc => tc.status === 'error')) {
      return 'error'
    }
    if (chatStore.activeToolCalls.some(tc => tc.status === 'running')) {
      return 'warning'
    }
    return 'info'
  }
  // 完成状态显示绿色
  if (chatStore.messages.length > 0) {
    return 'success'
  }
  return 'default'
})

function toggleToolCallExpand(key: string) {
  const set = expandedToolCalls.value
  if (set.has(key)) {
    set.delete(key)
  } else {
    set.add(key)
  }
  expandedToolCalls.value = new Set(set)
}

function toggleToolResultExpand(key: string) {
  const set = expandedToolResults.value
  if (set.has(key)) {
    set.delete(key)
  } else {
    set.add(key)
  }
  expandedToolResults.value = new Set(set)
}


// ---- Copy to Clipboard ----

function copyToClipboard(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    message.success(t('common.copied'))
  }).catch(() => {
    message.error(t('common.copyFailed'))
  })
}

// ---- Copy Message ----

async function copyMessageContent(msg: HermesMessage) {
  const content = msg.content || ''
  try {
    await navigator.clipboard.writeText(content)
    copiedMessageId.value = msg.id || null
    message.success(t('common.copied'))
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => {
      copiedMessageId.value = null
      copiedTimer = null
    }, 2000)
  } catch {
    message.error(t('common.copyFailed'))
  }
}

// ---- Text-to-Speech ----

function stopTTS() {
  ttsStop()
  playingMessageId.value = null
}

async function playTTS(msg: HermesMessage) {
  const content = msg.content || ''
  if (!content.trim()) return

  // If already playing this message, stop it
  if (playingMessageId.value === msg.id) {
    stopTTS()
    return
  }

  // Stop any current playback
  stopTTS()

  try {
    playingMessageId.value = msg.id || null

    // Use TTS settings from local storage
    const voice = ttsSettings.value.voice || 'zh-CN'
    const rate = ttsSettings.value.rate ?? 1.0
    const volume = ttsSettings.value.volume ?? 1.0
    const pitch = ttsSettings.value.pitch ?? 1.0


    // Use Web Speech API TTS
    await ttsSpeak(content, { voice, rate, volume, pitch })
  } catch (err) {
    console.error('[HermesChat] TTS error:', err)
    message.error(t('pages.hermesChat.tts.error'))
    stopTTS()
  }
}

// ---- Auto Play TTS for new assistant messages ----

const lastPlayedMessageId = ref<string | null>(null)

watch(
  () => chatStore.messages,
  (messages) => {
    // Check if auto-play is enabled
    if (!ttsSettings.value.autoPlay || !ttsSettings.value.enabled) return
    
    // Find the last assistant message
    const lastAssistantMsg = [...messages].reverse().find(m => m.role === 'assistant')
    if (!lastAssistantMsg?.id) return
    
    // Skip if already played or currently playing
    if (lastPlayedMessageId.value === lastAssistantMsg.id) return
    if (playingMessageId.value === lastAssistantMsg.id) return
    
    // Skip if currently streaming
    if (chatStore.streaming) return
    
    // Play the message
    lastPlayedMessageId.value = lastAssistantMsg.id
    playTTS(lastAssistantMsg)
  },
  { deep: true }
)

function formatRelativeTime(timestamp?: string | number): string {
  if (!timestamp) return '-'
  try {
    let date: Date
    if (typeof timestamp === 'number') {
      // Unix timestamp in seconds (e.g., 1776268987.7534964)
      // Check if it's in seconds (value < 1e12) or milliseconds (value >= 1e12)
      const ts = timestamp < 1e12 ? timestamp * 1000 : timestamp
      date = new Date(ts)
    } else if (typeof timestamp === 'string') {
      // Check if it's a numeric string (Unix timestamp)
      const num = parseFloat(timestamp)
      if (!isNaN(num) && num > 0) {
        const ts = num < 1e12 ? num * 1000 : num
        date = new Date(ts)
      } else {
        date = new Date(timestamp)
      }
    } else {
      return '-'
    }
    if (isNaN(date.getTime())) return '-'
    
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffSec = Math.floor(diffMs / 1000)
    const diffMin = Math.floor(diffSec / 60)
    const diffHour = Math.floor(diffMin / 60)
    const diffDay = Math.floor(diffHour / 24)

    if (diffSec < 60) return `${diffSec}s`
    if (diffMin < 60) return `${diffMin}m`
    if (diffHour < 24) return `${diffHour}h`
    if (diffDay < 30) return `${diffDay}d`
    return date.toLocaleDateString(locale.value, { month: 'short', day: 'numeric', timeZone: 'Asia/Shanghai' })
  } catch {
    return '-'
  }
}

function formatSessionDate(timestamp?: string | number): string {
  if (!timestamp) return '-'
  try {
    let date: Date
    if (typeof timestamp === 'number') {
      const ts = timestamp < 1e12 ? timestamp * 1000 : timestamp
      date = new Date(ts)
    } else if (typeof timestamp === 'string') {
      if (timestamp.includes('-') || timestamp.includes('T') || timestamp.includes(':')) {
        date = new Date(timestamp)
      } else {
        const num = parseFloat(timestamp)
        if (!isNaN(num) && num > 0) {
          const ts = num < 1e12 ? num * 1000 : num
          date = new Date(ts)
        } else {
          date = new Date(timestamp)
        }
      }
    } else {
      return '-'
    }
    if (isNaN(date.getTime())) return '-'
    return date.toLocaleDateString(locale.value, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Shanghai',
    })
  } catch {
    return '-'
  }
}

</script>

<template>
  <div class="hermes-chat-page">
    <NCard :title="t('pages.hermesChat.sessions')" class="app-card chat-root-card">
      <template #header-extra>
        <NSpace :size="8" class="app-toolbar">
          <div v-if="tokenMetricTags.length" class="chat-token-metrics">
            <NTag
              v-for="metric in tokenMetricTags"
              :key="metric.key"
              size="small"
              :bordered="false"
              round
              class="chat-token-chip"
              :class="{ 'chat-token-chip--total': metric.highlight }"
            >
              <span class="chat-token-chip__label">{{ metric.label }}</span>
              <span class="chat-token-chip__value">{{ metric.value }}</span>
            </NTag>
          </div>
          <NButton
            size="small"
            class="app-toolbar-btn app-toolbar-btn--refresh"
            :loading="sessionStore.loading || chatStore.loading"
            @click="handleRefreshChatData"
          >
            <template #icon><NIcon :component="RefreshOutline" /></template>
            {{ t('pages.hermesChat.refresh') }}
          </NButton>
        </NSpace>
      </template>

      <NGrid cols="1 l:3" responsive="screen" :x-gap="12" :y-gap="12" class="chat-grid" :class="{ 'chat-grid--collapsed': sideCollapsed }">
        <!-- Sidebar -->
        <NGridItem :span="1" class="chat-grid-side" :class="{ 'chat-grid-side--collapsed': sideCollapsed }">
          <!-- Collapse button -->
          <div class="chat-side-collapse-btn" @click="sideCollapsed = !sideCollapsed">
            <NIcon :component="ChevronBackOutline" size="14" />
          </div>

          <NCard v-show="!sideCollapsed" embedded :bordered="false" class="chat-side-card">
            <NSpace vertical :size="12">
              <!-- Stats panel -->
              <div class="chat-side-stats">
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.hermesChat.stats.total') }}</span>
                  <strong>{{ stats.total }}</strong>
                </div>
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.hermesChat.stats.assistant') }}</span>
                  <strong>{{ stats.assistant }}</strong>
                </div>
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.hermesChat.stats.lastMessage') }}</span>
                  <strong>{{ stats.lastMessageAt }}</strong>
                </div>
              </div>

              <!-- Session selector -->
              <div>
                <NText depth="3" style="font-size: 12px;">{{ t('pages.hermesChat.sessionSelector') }}</NText>
                <NSelect
                  :value="chatStore.currentSessionId"
                  :options="sessionOptions"
                  :render-label="renderSessionLabel"
                  filterable
                  :placeholder="t('pages.hermesChat.sessionSelectorPlaceholder')"
                  style="min-width: 240px; margin-top: 6px;"
                  @update:value="handleSelectSession"
                />
              </div>

              <!-- Quick Replies panel -->
              <div class="chat-quick-panel">
                <NSpace justify="space-between" align="center">
                  <NText strong>{{ t('pages.hermesChat.quickReplies.title') }}</NText>
                  <NButton size="tiny" type="primary" secondary @click="openCreateQuickReply">
                    {{ t('pages.hermesChat.quickReplies.add') }}
                  </NButton>
                </NSpace>
                <NInput
                  v-model:value="quickReplySearch"
                  size="small"
                  style="margin-top: 8px;"
                  :placeholder="t('pages.hermesChat.quickReplies.searchPlaceholder')"
                />

                <div v-if="filteredQuickReplies.length" class="chat-quick-list">
                  <div v-for="item in filteredQuickReplies" :key="item.id" class="chat-quick-item">
                    <NSpace justify="space-between" align="start" :wrap="false">
                      <div style="min-width: 0; flex: 1;">
                        <NText strong>{{ item.title }}</NText>
                        <NText depth="3" style="display: block; font-size: 12px; margin-top: 4px;">
                          {{ item.content.length > 78 ? item.content.slice(0, 78) + '...' : item.content }}
                        </NText>
                      </div>
                      <NSpace :size="2">
                        <NButton size="tiny" text @click="handleInsertQuickReply(item)">
                          {{ t('pages.hermesChat.quickReplies.insert') }}
                        </NButton>
                        <NButton size="tiny" text type="primary" @click="handleSendQuickReply(item, handleSend)">
                          {{ t('pages.hermesChat.quickReplies.send') }}
                        </NButton>
                        <NButton size="tiny" text @click="openEditQuickReply(item)">
                          {{ t('pages.hermesChat.quickReplies.edit') }}
                        </NButton>
                        <NPopconfirm
                          :positive-text="t('common.delete')"
                          :negative-text="t('common.cancel')"
                          @positive-click="handleDeleteQuickReply(item.id)"
                        >
                          <template #trigger>
                            <NButton size="tiny" text type="error">
                              {{ t('pages.hermesChat.quickReplies.delete') }}
                            </NButton>
                          </template>
                          {{ t('pages.hermesChat.quickReplies.confirmDelete') }}
                        </NPopconfirm>
                      </NSpace>
                    </NSpace>
                  </div>
                </div>
                <NEmpty v-else :description="t('pages.hermesChat.quickReplies.empty')" style="padding: 14px 0 8px;" />
              </div>

              <!-- Preferences -->
              <div class="chat-side-switches">
                <NSpace justify="space-between" align="center">
                  <NText>{{ t('pages.hermesChat.preferences.autoFollow') }}</NText>
                  <NSwitch v-model:value="autoFollowBottom" />
                </NSpace>
                <NSpace justify="space-between" align="center" style="margin-top: 8px;">
                  <NText>{{ t('pages.hermesChat.preferences.autoPlay') }}</NText>
                  <NSwitch v-model:value="ttsSettings.autoPlay" />
                </NSpace>
                <NSpace justify="space-between" align="center" style="margin-top: 8px;">
                  <NText>{{ t('pages.hermesChat.filters.title') }}</NText>
                  <NSelect
                    v-model:value="roleFilter"
                    size="small"
                    :options="roleFilterOptions"
                    style="width: 132px;"
                  />
                </NSpace>
              </div>

              <!-- Session metadata -->
              <div v-if="selectedSession" class="chat-side-kv">
                <div class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.title') }}</span>
                  <code class="chat-kv-label">{{ selectedSession.title || selectedSession.id }}</code>
                </div>
                <div class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.sessionId') }}</span>
                  <code class="chat-kv-label" style="font-size: 11px;">{{ selectedSession.id }}</code>
                </div>
                <div v-if="selectedSession.model" class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.model') }}</span>
                  <NTag size="small" :bordered="false" round>{{ selectedSession.model }}</NTag>
                </div>
                <div v-if="selectedSession.platform" class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.platform') }}</span>
                  <NTag 
                    size="small" 
                    :bordered="false" 
                    round 
                    :style="{ backgroundColor: getPlatformInfo(selectedSession.platform)?.color + '20', color: getPlatformInfo(selectedSession.platform)?.color }"
                  >
                    {{ getPlatformInfo(selectedSession.platform)?.label || selectedSession.platform }}
                  </NTag>
                </div>
                <div class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.messages') }}</span>
                  <code>{{ selectedSession.messageCount ?? chatStore.messages.length }}</code>
                </div>
                <div v-if="selectedSession.createdAt" class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.created') }}</span>
                  <code>{{ formatSessionDate(selectedSession.createdAt) }}</code>
                </div>
                <div v-if="chatStore.autoRefreshEnabled" class="chat-kv-row">
                  <span>{{ t('pages.hermesChat.sessionInfo.syncStatus') }}</span>
                  <NTag size="small" :bordered="false" round type="success">
                    {{ t('pages.hermesChat.sessionInfo.syncing') }}
                  </NTag>
                </div>
              </div>
            </NSpace>
          </NCard>
        </NGridItem>

        <!-- Main Chat Area -->
        <NGridItem :span="sideCollapsed ? 3 : 2" class="chat-grid-main">
          <!-- Expand button -->
          <div v-if="sideCollapsed" class="chat-side-expand-btn" @click="sideCollapsed = false">
            <NIcon :component="ChevronForwardOutline" size="14" />
          </div>

          <div class="chat-main-column">
            <!-- Chat Header -->
            <NCard embedded :bordered="false" class="chat-transcript-card">
              <NSpace justify="space-between" align="center" style="margin-bottom: 10px;">
                <NSpace align="center" :size="8">
                  <NTag v-if="messageCount > 0" size="small" :bordered="false" round>
                    {{ messageCount }} {{ t('pages.hermesChat.messages') }}
                  </NTag>
                </NSpace>
                <NText depth="3" style="font-size: 12px;">
                  {{ t('pages.hermesChat.roleUser') }}: {{ stats.user }} / {{ t('pages.hermesChat.roleAssistant') }}: {{ stats.assistant }} / {{ t('pages.hermesChat.roleSystem') }}: {{ stats.system }}
                </NText>
              </NSpace>

              <!-- Messages -->
              <div class="chat-transcript-shell">
                <NSpin :show="chatStore.loading" class="chat-transcript-spin">
                  <div
                    ref="messageListRef"
                    class="chat-transcript"
                    @scroll="handleMessagesScroll"
                  >
                    <!-- Empty state -->
                    <div v-if="filteredMessages.length === 0 && !chatStore.loading" class="hermes-chat-empty">
                      <div class="hermes-chat-empty-content">
                        <NIcon :component="ChatbubblesOutline" size="48" depth="3" />
                        <NText depth="3" style="font-size: 14px; margin-top: 12px;">
                          {{ t('pages.hermesChat.noMessages') }}
                        </NText>
                        <NText depth="3" style="font-size: 12px; margin-top: 4px;">
                          {{ t('pages.hermesChat.emptyHint') }}
                        </NText>
                      </div>
                    </div>

                    <!-- Message list -->
                    <div v-else class="hermes-chat-message-list">
                      <div
                        v-for="entry in renderMessageEntries"
                        :key="entry.key"
                        class="chat-bubble"
                        :class="`is-${entry.item.role}`"
                      >
                        <NSpace justify="space-between" align="center" class="chat-bubble-meta" :size="8">
                          <NSpace align="center" :size="6">
                            <NTag :type="getRoleTagType(entry.item.role)" size="small" :bordered="false" round>
                              {{ getRoleLabel(entry.item.role) }}
                            </NTag>
                            <NText v-if="entry.item.model" depth="3" style="font-size: 12px;">
                              {{ entry.item.model }}
                            </NText>
                            <NText v-else-if="entry.item.role === 'tool' && entry.item.toolName" depth="3" style="font-size: 12px;">
                              {{ entry.item.toolName }}
                            </NText>
                          </NSpace>
                          <NText v-if="entry.item.timestamp" depth="3" style="font-size: 12px;">
                            {{ formatSessionDate(entry.item.timestamp) }}
                          </NText>
                        </NSpace>

                        <div v-if="entry.structured" class="structured-message-list">
                          <div v-if="entry.structured.toolCalls.length" class="tool-call-list">
                            <div
                              v-for="(tool, toolIndex) in entry.structured.toolCalls"
                              :key="`${entry.key}-tool-${toolIndex}`"
                              class="tool-call-card"
                            >
                              <NSpace align="center" justify="space-between">
                                <NSpace align="center" :size="6">
                                  <NTag size="small" type="warning" :bordered="false" round>{{ t('pages.hermesChat.toolCall') }}</NTag>
                                  <NText strong>{{ tool.name }}</NText>
                                </NSpace>
                                <NSpace align="center" :size="8">
                                  <NText v-if="tool.timeout" depth="3" style="font-size: 12px;">
                                    {{ t('pages.hermesChat.toolTimeout', { seconds: tool.timeout }) }}
                                  </NText>
                                  <NButton
                                    v-if="tool.argumentsJson"
                                    size="tiny"
                                    text
                                    @click="toggleToolCallExpand(`${entry.key}-tool-${toolIndex}`)"
                                  >
                                    {{ expandedToolCalls.has(`${entry.key}-tool-${toolIndex}`) ? t('pages.hermesChat.hideArgs') : t('pages.hermesChat.viewArgs') }}
                                  </NButton>
                                </NSpace>
                              </NSpace>

                              <div v-if="tool.command || tool.workdir" class="tool-call-meta">
                                <code v-if="tool.command" class="tool-call-meta__code">{{ tool.command }}</code>
                                <code v-if="tool.workdir" class="tool-call-meta__code">{{ tool.workdir }}</code>
                              </div>

                              <div v-if="tool.argumentsJson && expandedToolCalls.has(`${entry.key}-tool-${toolIndex}`)" class="tool-call-args">
                                <pre class="tool-call-args__content">{{ tool.argumentsJson }}</pre>
                              </div>

                              <details v-if="tool.partialJson" class="tool-call-details">
                                <summary>{{ t('pages.hermesChat.viewPartialJson') }}</summary>
                                <pre>{{ tool.partialJson }}</pre>
                              </details>
                            </div>
                          </div>

                          <div v-if="entry.structured.toolResults.length" class="tool-result-list">
                            <div
                              v-for="(result, resultIndex) in entry.structured.toolResults"
                              :key="`${entry.key}-tool-result-${resultIndex}`"
                              class="tool-result-card"
                            >
                              <NSpace align="center" justify="space-between">
                                <NSpace align="center" :size="6">
                                  <NTag size="small" type="success" :bordered="false" round>{{ t('pages.hermesChat.toolCallResult') }}</NTag>
                                  <NText strong>{{ result.name || 'unknown' }}</NText>
                                </NSpace>
                                <NSpace align="center" :size="8">
                                  <NText v-if="result.status" depth="3" style="font-size: 12px;">
                                    {{ result.status }}
                                  </NText>
                                  <NButton
                                    size="tiny"
                                    text
                                    @click="toggleToolResultExpand(`${entry.key}-result-${resultIndex}`)"
                                  >
                                    {{ expandedToolResults.has(`${entry.key}-result-${resultIndex}`) ? t('pages.hermesChat.hideArgs') : t('pages.hermesChat.viewArgs') }}
                                  </NButton>
                                </NSpace>
                              </NSpace>

                              <div v-if="expandedToolResults.has(`${entry.key}-result-${resultIndex}`)" class="tool-call-grid">
                                <span class="tool-call-label">{{ t('pages.hermesChat.toolCallId') }}</span>
                                <div class="tool-call-value-wrapper">
                                  <code>{{ result.id || '-' }}</code>
                                  <NTooltip>
                                    <template #trigger>
                                      <NButton quaternary size="tiny" class="tool-value-copy-btn" @click="copyToClipboard(result.id || '-')">
                                        <template #icon>
                                          <NIcon :component="CopyOutline" />
                                        </template>
                                      </NButton>
                                    </template>
                                    {{ t('common.copy') }}
                                  </NTooltip>
                                </div>
                                <span class="tool-call-label">{{ t('pages.hermesChat.toolCallContent') }}</span>
                                <div class="tool-call-value-wrapper tool-result-content-wrapper">
                                  <pre class="tool-result-content">{{ result.content }}</pre>
                                  <NTooltip>
                                    <template #trigger>
                                      <NButton quaternary size="tiny" class="tool-value-copy-btn" @click="copyToClipboard(result.content)">
                                        <template #icon>
                                          <NIcon :component="CopyOutline" />
                                        </template>
                                      </NButton>
                                    </template>
                                    {{ t('common.copy') }}
                                  </NTooltip>
                                </div>
                              </div>
                            </div>
                          </div>

                          <div
                            v-if="entry.structured.plainTexts.length"
                            class="chat-bubble-content-wrapper"
                          >
                            <div class="chat-bubble-content structured-plain-text chat-markdown"
                              v-html="renderChatMarkdown(entry.structured.plainTexts.join('\n'), entry.item.role)"
                            ></div>
                            <div class="chat-content-actions">
                              <NTooltip>
                                <template #trigger>
                                  <NButton quaternary size="tiny" @click="copyMessageContent(entry.item)">
                                    <template #icon>
                                      <NIcon :component="CopyOutline" />
                                    </template>
                                  </NButton>
                                </template>
                                {{ t('common.copy') }}
                              </NTooltip>
                              <NTooltip v-if="entry.item.role === 'user' || entry.item.role === 'assistant'">
                                <template #trigger>
                                  <NButton
                                    quaternary
                                    size="tiny"
                                    :loading="ttsIsLoading && playingMessageId === entry.item.id"
                                    @click="playTTS(entry.item)"
                                  >
                                    <template #icon>
                                      <NIcon :component="playingMessageId === entry.item.id ? StopOutline : VolumeHighOutline" />
                                    </template>
                                  </NButton>
                                </template>
                                {{ playingMessageId === entry.item.id ? t('pages.hermesChat.tts.stop') : t('pages.hermesChat.tts.play') }}
                              </NTooltip>
                            </div>
                          </div>
                        </div>

                        <div v-else class="chat-bubble-content-wrapper">
                          <div
                            v-if="entry.item.role === 'assistant'"
                            class="chat-bubble-content chat-markdown"
                            v-html="renderChatMarkdown(entry.item.content, entry.item.role)"
                          ></div>
                          <div
                            v-else
                            class="chat-bubble-content"
                            v-html="renderChatMarkdown(entry.item.content, entry.item.role)"
                          ></div>
                          <div class="chat-content-actions">
                            <NTooltip>
                              <template #trigger>
                                <NButton
                                  quaternary
                                  size="tiny"
                                  :type="copiedMessageId === entry.item.id ? 'success' : 'default'"
                                  @click="copyMessageContent(entry.item)"
                                >
                                  <template #icon>
                                    <NIcon :component="CopyOutline" />
                                  </template>
                                </NButton>
                              </template>
                              {{ t('common.copy') }}
                            </NTooltip>
                            <NTooltip v-if="entry.item.role === 'user' || entry.item.role === 'assistant'">
                              <template #trigger>
                                <NButton
                                  quaternary
                                  size="tiny"
                                  :loading="ttsIsLoading && playingMessageId === entry.item.id"
                                  @click="playTTS(entry.item)"
                                >
                                  <template #icon>
                                    <NIcon :component="playingMessageId === entry.item.id ? StopOutline : VolumeHighOutline" />
                                  </template>
                                </NButton>
                              </template>
                              {{ playingMessageId === entry.item.id ? t('pages.hermesChat.tts.stop') : t('pages.hermesChat.tts.play') }}
                            </NTooltip>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </NSpin>
              </div>
            </NCard>

            <!-- Input Area -->
            <NCard embedded :bordered="false" class="chat-compose-card">
              <NSpace vertical :size="10">
                <!-- Command Panel -->
                <HermesChatCommandPanel
                  v-if="showCommandPanel"
                  :commands="filteredCommands"
                  :selected-index="selectedCommandIndex"
                  @select="handleCommandSelect"
                  @hover="selectedCommandIndex = $event"
                />

                <NInput
                  :value="inputText"
                  type="textarea"
                  :autosize="{ minRows: 3, maxRows: 8 }"
                  :placeholder="t('pages.hermesChat.inputPlaceholder')"
                  :disabled="!isConnected"
                  @update:value="handleInputUpdate"
                  @keydown="handleKeydown"
                />

                <!-- Tool Progress Status Line -->
                <div v-if="chatStore.streaming || chatStore.messages.length > 0" class="chat-compose-status-line">
                  <NSpace align="center" justify="space-between" style="width: 100%;">
                    <NTag
                      size="small"
                      :type="hermesStatusTagType"
                      :bordered="false"
                      round
                      class="chat-agent-status-tag"
                    >
                      {{ hermesStatusText }}
                    </NTag>
                    <NButton
                      v-if="chatStore.activeToolCalls.length > 0"
                      size="tiny"
                      text
                      @click="showToolDetails = !showToolDetails"
                    >
                      {{ showToolDetails ? t('pages.hermesChat.hideArgs') : t('pages.hermesChat.viewArgs') }}
                    </NButton>
                  </NSpace>
                </div>

                <!-- Tool Progress Details Panel -->
                <div v-if="showToolDetails && chatStore.activeToolCalls.length > 0" class="chat-tool-progress">
                  <div v-for="(tc, tcIdx) in chatStore.activeToolCalls" :key="tc.toolCallId || tcIdx" class="chat-tool-progress__item">
                    <div class="chat-tool-progress__title">
                      <span>{{ tc.emoji || '🔧' }} {{ tc.toolName }}</span>
                      <span v-if="tc.duration" class="chat-tool-progress__meta">{{ formatToolDuration(tc.duration) }}</span>
                    </div>
                    <div class="chat-tool-progress__kv">
                      <span class="chat-tool-progress__k">{{ t('pages.hermesChat.toolCallId') }}</span>
                      <code class="chat-tool-progress__v">{{ tc.toolCallId || '-' }}</code>
                      <span class="chat-tool-progress__k">{{ t('pages.hermesChat.toolCallPhase') }}</span>
                      <code class="chat-tool-progress__v">{{ tc.phase }}</code>
                      <span class="chat-tool-progress__k">{{ t('pages.hermesChat.toolCallStatus') }}</span>
                      <code class="chat-tool-progress__v">{{ tc.status }}</code>
                    </div>

                    <details v-if="tc.argsPreview" class="chat-tool-progress__details">
                      <summary>{{ t('pages.hermesChat.viewArgs') }}</summary>
                      <pre>{{ tc.argsPreview }}</pre>
                    </details>

                    <details v-if="tc.resultPreview" class="chat-tool-progress__details">
                      <summary>{{ t('pages.hermesChat.toolCallContent') }}</summary>
                      <pre>{{ tc.resultPreview }}</pre>
                    </details>
                  </div>
                </div>

                <NSpace justify="space-between" align="center">
                  <NText v-if="inputCharCount > 0" depth="3" style="font-size: 11px;">
                    {{ inputCharCount }}
                  </NText>
                  <span v-else />
                  <NSpace :size="8">
                    <NButton
                      v-if="chatStore.streaming"
                      type="warning"
                      size="small"
                      class="app-toolbar-btn"
                      @click="handleStop"
                    >
                      <template #icon><NIcon :component="StopCircleOutline" /></template>
                      {{ t('pages.hermesChat.stop') }}
                    </NButton>
                    <NButton
                      type="primary"
                      size="small"
                      class="app-toolbar-btn"
                      :disabled="!inputText.trim() || chatStore.streaming || !isConnected"
                      @click="handleSend"
                    >
                      <template #icon><NIcon :component="SendOutline" /></template>
                      {{ t('pages.hermesChat.send') }}
                    </NButton>
                  </NSpace>
                </NSpace>
              </NSpace>
            </NCard>
          </div>
        </NGridItem>
      </NGrid>

      <!-- Error -->
      <NAlert v-if="chatStore.error" type="error" :bordered="false" closable style="margin-top: 12px;">
        {{ chatStore.error }}
      </NAlert>
    </NCard>

    <!-- Quick Reply Modal -->
    <NModal
      v-model:show="showQuickReplyModal"
      preset="card"
      :title="quickReplyModalMode === 'edit'
        ? t('pages.hermesChat.quickReplies.editTitle')
        : t('pages.hermesChat.quickReplies.createTitle')"
      style="width: 640px; max-width: calc(100vw - 28px);"
    >
      <NForm label-placement="left" label-width="72">
        <NFormItem :label="t('pages.hermesChat.quickReplies.titleLabel')" required>
          <NInput v-model:value="quickReplyForm.title" :placeholder="t('pages.hermesChat.quickReplies.titlePlaceholder')" />
        </NFormItem>
        <NFormItem :label="t('pages.hermesChat.quickReplies.contentLabel')" required>
          <NInput
            v-model:value="quickReplyForm.content"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
            :placeholder="t('pages.hermesChat.quickReplies.contentPlaceholder')"
          />
        </NFormItem>
      </NForm>
      <template #footer>
        <NSpace justify="end">
          <NButton @click="showQuickReplyModal = false">{{ t('common.cancel') }}</NButton>
          <NButton type="primary" @click="handleSaveQuickReply">
            {{ quickReplyModalMode === 'edit'
              ? t('common.save')
              : t('pages.hermesChat.quickReplies.add') }}
          </NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.hermes-chat-page {
  min-height: 0;
}

/* Desktop: fill available height */
@media (min-width: 1024px) {
  .hermes-chat-page {
    height: calc(100vh - var(--header-height) - 48px);
    display: flex;
    flex-direction: column;
  }

  :deep(.chat-root-card) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  :deep(.chat-root-card .n-card__content) {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .chat-grid {
    flex: 1;
    min-height: 0;
    align-content: stretch;
  }

  .chat-grid-side,
  .chat-grid-main {
    min-height: 0;
    display: flex;
    position: relative;
  }

  /* Collapse button */
  .chat-side-collapse-btn {
    position: absolute;
    right: -8px;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 48px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 0 4px 4px 0;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    z-index: 10;
    transition: all 0.2s ease;
    opacity: 0.6;
  }

  .chat-side-collapse-btn:hover {
    background: var(--bg-secondary);
    opacity: 1;
  }

  /* Expand button */
  .chat-side-expand-btn {
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 48px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 4px 0 0 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    z-index: 10;
    transition: all 0.2s ease;
    opacity: 0.6;
  }

  .chat-side-expand-btn:hover {
    background: var(--bg-secondary);
    opacity: 1;
  }

  /* Sidebar collapsed state */
  .chat-grid-side--collapsed {
    width: 0 !important;
    min-width: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    overflow: hidden;
  }

  .chat-grid-side--collapsed .chat-side-card {
    display: none;
  }

  .chat-grid-side--collapsed .chat-side-collapse-btn {
    display: none;
  }

  .chat-side-card {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  .chat-main-column {
    flex: 1;
    min-height: 0;
  }
}

/* Token metrics */
.chat-token-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.chat-token-chip.n-tag {
  border-radius: 999px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.chat-token-chip--total.n-tag {
  background: rgba(32, 128, 240, 0.12);
}

.chat-token-chip__label {
  color: var(--text-secondary);
  margin-right: 4px;
}

.chat-token-chip__value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* Side card */
.chat-side-card {
  border-radius: var(--radius);
}

.chat-main-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow: hidden;
}

.chat-side-switches,
.chat-side-stats,
.chat-side-kv,
.chat-quick-panel {
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  background: var(--bg-primary);
}

/* Quick replies */
.chat-quick-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow-y: auto;
  padding-right: 2px;
}

.chat-quick-item {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
  background: var(--bg-secondary);
}

.chat-quick-footnote {
  margin-top: 8px;
  border-top: 1px dashed var(--border-color);
  padding-top: 8px;
}

/* Stats */
.chat-side-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.chat-stat-item {
  padding: 8px;
  border-radius: 6px;
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chat-stat-item strong {
  font-size: 13px;
  line-height: 1.3;
}

.chat-stat-label {
  font-size: 11px;
  color: var(--text-secondary);
}

/* Session metadata KV rows */
.chat-kv-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
  font-size: 12px;
  border-bottom: 1px dashed var(--border-color);
}

.chat-kv-row:last-child {
  border-bottom: none;
}

.chat-kv-row code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-secondary);
  word-break: break-all;
}

.chat-kv-label {
  font-style: italic;
  color: var(--text-secondary);
}

/* Transcript card */
.chat-transcript-card,
.chat-compose-card {
  border-radius: var(--radius);
}

.chat-transcript-card {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

:deep(.chat-transcript-card .n-card__content) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-transcript-shell {
  flex: 1;
  min-height: 0;
}

:deep(.chat-transcript-shell .n-spin-container),
:deep(.chat-transcript-shell .n-spin-content) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-transcript {
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  padding-bottom: 20px;
  overflow-anchor: none;
  overscroll-behavior: contain;
  background:
    radial-gradient(circle at top right, rgba(24, 160, 88, 0.06), transparent 30%),
    var(--bg-primary);
}

/* Compose card */
.chat-compose-card {
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
  position: relative;
}

/* Empty state */
.hermes-chat-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.hermes-chat-empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
}

/* Message list */
.hermes-chat-message-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* Chat bubbles */
.chat-bubble {
  position: relative;
  width: fit-content;
  max-width: min(840px, 88%);
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.chat-bubble.is-user {
  margin-left: auto;
  border-color: rgba(24, 160, 88, 0.35);
  background: rgba(24, 160, 88, 0.09);
}

.chat-bubble.is-assistant {
  margin-right: auto;
  border-color: rgba(24, 144, 255, 0.3);
  background: rgba(24, 144, 255, 0.08);
}

.chat-bubble.is-tool {
  margin-right: auto;
  border-style: dashed;
}

.chat-bubble.is-system {
  margin: 0 auto 12px;
  border-style: dashed;
  background: rgba(250, 173, 20, 0.08);
}

.chat-bubble-meta {
  margin-bottom: 6px;
}

.chat-bubble-content-wrapper {
  position: relative;
}

.chat-bubble-content {
  white-space: pre-wrap;
  line-height: 1.65;
  word-break: break-word;
}

.chat-content-actions {
  position: absolute;
  top: 0;
  right: 0;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 10;
  display: flex;
  gap: 4px;
}

.chat-bubble-content-wrapper:hover .chat-content-actions {
  opacity: 1;
}

/* Tool calls */
.hermes-chat-tool-calls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.structured-message-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.structured-plain-text {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px dashed var(--border-color);
  background: var(--bg-primary);
}

.tool-call-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-call-card {
  border: 1px solid rgba(250, 173, 20, 0.35);
  border-radius: 8px;
  background: rgba(250, 173, 20, 0.08);
  padding: 10px;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.tool-call-card:hover {
  border-color: rgba(250, 173, 20, 0.55);
}

.tool-call-card--running {
  border-color: rgba(250, 173, 20, 0.5);
  background: rgba(250, 173, 20, 0.12);
  animation: tool-pulse 1.5s ease-in-out infinite;
}

@keyframes tool-pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}

.tool-call-card--completed {
  border-color: rgba(24, 160, 88, 0.35);
  background: rgba(24, 160, 88, 0.08);
}

.tool-call-card--completed:hover {
  border-color: rgba(24, 160, 88, 0.55);
}

.tool-call-card--error {
  border-color: rgba(208, 48, 80, 0.35);
  background: rgba(208, 48, 80, 0.08);
}

.tool-call-card--error:hover {
  border-color: rgba(208, 48, 80, 0.55);
}

.tool-call-details {
  margin-top: 8px;
}

.tool-call-details summary {
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.tool-call-details pre {
  margin-top: 6px;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
}

.tool-call-args {
  margin-top: 10px;
}

.tool-call-args:first-child {
  margin-top: 0;
}

.tool-call-result {
  margin-top: 10px;
}

.tool-call-args__content {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow: auto;
}

.tool-call-meta {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-call-meta__code {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  line-height: 1.5;
  word-break: break-all;
}

.tool-result-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-result-card {
  border: 1px solid rgba(24, 160, 88, 0.35);
  border-radius: 8px;
  background: rgba(24, 160, 88, 0.08);
  padding: 10px;
  transition: border-color 0.15s ease;
}

.tool-result-card:hover {
  border-color: rgba(24, 160, 88, 0.55);
}

.tool-result-card--error {
  border-color: rgba(208, 48, 80, 0.35);
  background: rgba(208, 48, 80, 0.08);
}

.tool-result-card--error:hover {
  border-color: rgba(208, 48, 80, 0.55);
}

.tool-message-card {
  border: 1px solid rgba(32, 128, 240, 0.35);
  border-radius: 8px;
  background: rgba(32, 128, 240, 0.08);
  padding: 10px;
  width: 100%;
  transition: border-color 0.15s ease;
}

.tool-message-card:hover {
  border-color: rgba(32, 128, 240, 0.55);
}

.tool-message-card--error {
  border-color: rgba(208, 48, 80, 0.35);
  background: rgba(208, 48, 80, 0.08);
}

.tool-message-card--error:hover {
  border-color: rgba(208, 48, 80, 0.55);
}

.tool-message-content {
  margin-top: 10px;
  position: relative;
}

.tool-message-content pre {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow: auto;
}

.tool-message-content .tool-value-copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.tool-message-content:hover .tool-value-copy-btn {
  opacity: 1;
}

.tool-result-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
}

.tool-call-grid {
  margin-top: 8px;
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 6px 8px;
  align-items: start;
}

.tool-call-label {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.tool-call-value-wrapper {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.tool-call-value-wrapper code {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  word-break: break-all;
}

.tool-result-content-wrapper {
  flex-direction: column;
  align-items: stretch;
}

.tool-result-content-wrapper .tool-result-content {
  margin: 0;
}

.tool-result-content-wrapper .tool-value-copy-btn {
  position: absolute;
  top: 4px;
  right: 4px;
}

.tool-value-copy-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
  flex-shrink: 0;
}

.tool-call-value-wrapper:hover .tool-value-copy-btn {
  opacity: 1;
}

/* Tool Progress Panel */
.chat-compose-status-line {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  min-width: 0;
}

.chat-agent-status-tag.n-tag {
  max-width: 360px;
}

.chat-agent-status-tag :deep(.n-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-tool-progress {
  margin-top: 8px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}

.chat-tool-progress__item {
  margin-bottom: 8px;
}

.chat-tool-progress__item:last-child {
  margin-bottom: 0;
}

.chat-tool-progress__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
}

.chat-tool-progress__meta {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}

.chat-tool-progress__kv {
  margin-top: 6px;
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 6px 10px;
  align-items: start;
}

.chat-tool-progress__k {
  font-size: 12px;
  color: var(--text-secondary);
}

.chat-tool-progress__v {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--bg-primary);
  border: 1px solid var(--border-color);
  word-break: break-all;
}

.chat-tool-progress__details {
  margin-top: 8px;
}

.chat-tool-progress__details summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
}

.chat-tool-progress__details pre {
  margin-top: 6px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  background: var(--bg-primary);
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
  max-height: 240px;
}

/* Streaming indicator */
.hermes-chat-streaming {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Command panel */
.hermes-command-panel {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  background: var(--bg-card, #fff);
  border: 1px solid var(--border-color, #efeff5);
  border-radius: var(--card-radius-xl, 8px) var(--card-radius-xl, 8px) 0 0;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
  z-index: 20;
  max-height: 320px;
  overflow-y: auto;
}

.hermes-command-item {
  padding: 8px 12px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.hermes-command-item:hover,
.hermes-command-item--active {
  background: var(--primary-color-hover, rgba(32, 128, 240, 0.08));
}

.hermes-slide-enter-active,
.hermes-slide-leave-active {
  transition: all 0.2s ease;
}

.hermes-slide-enter-from,
.hermes-slide-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* ---- Markdown styles (mirrors ChatPage chat-markdown) ---- */

.chat-markdown {
  white-space: normal;
  font-size: 12.5px;
  line-height: 1.72;
  word-break: break-word;
  overflow-wrap: break-word;
}

.chat-markdown :deep(> :first-child) {
  margin-top: 0;
}

.chat-markdown :deep(> :last-child) {
  margin-bottom: 0;
}

/* Headings */
.chat-markdown :deep(h1),
.chat-markdown :deep(h2),
.chat-markdown :deep(h3),
.chat-markdown :deep(h4),
.chat-markdown :deep(h5),
.chat-markdown :deep(h6) {
  margin: 16px 0 4px;
  line-height: 1.4;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.chat-markdown :deep(h1) { font-size: 1.25em; }
.chat-markdown :deep(h2) { font-size: 1.12em; }
.chat-markdown :deep(h3) { font-size: 1.02em; }

/* Paragraphs */
.chat-markdown :deep(p) {
  margin: 4px 0;
  line-height: 1.72;
}

/* Tables (GFM) */
.chat-markdown :deep(table) {
  width: 100%;
  margin: 8px 0;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-card);
}

.chat-markdown :deep(th),
.chat-markdown :deep(td) {
  padding: 10px 12px;
  border-right: 1px solid var(--border-color);
  border-bottom: 1px solid var(--border-color);
  vertical-align: top;
  text-align: left;
}

.chat-markdown :deep(th) {
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-weight: 600;
}

.chat-markdown :deep(th:last-child),
.chat-markdown :deep(td:last-child) {
  border-right: none;
}

.chat-markdown :deep(tr:last-child > td) {
  border-bottom: none;
}

/* Unordered lists */
.chat-markdown :deep(ul) {
  margin: 4px 0;
  padding-left: 1.1em;
  list-style: none;
}

.chat-markdown :deep(ul > li) {
  position: relative;
  margin: 2px 0;
  line-height: 1.72;
}

.chat-markdown :deep(ul > li::before) {
  content: '';
  position: absolute;
  left: -0.88em;
  top: 0.58em;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--md-bullet-color);
}

/* Nested lists */
.chat-markdown :deep(ul ul) {
  margin: 1px 0 1px 0.15em;
}

.chat-markdown :deep(ul ul > li::before) {
  width: 3.5px;
  height: 3.5px;
  background: transparent;
  border: 1px solid var(--md-bullet-nested-color);
  top: 0.62em;
}

/* Ordered lists */
.chat-markdown :deep(ol) {
  margin: 4px 0;
  padding-left: 1.5em;
  list-style-position: outside;
}

.chat-markdown :deep(ol > li) {
  margin: 2px 0;
  line-height: 1.72;
}

.chat-markdown :deep(ol > li::marker) {
  color: var(--md-bullet-color);
  font-size: 0.9em;
  font-weight: 500;
}

/* Links */
.chat-markdown :deep(a) {
  color: var(--link-color);
  text-decoration: none;
  font-weight: 500;
  text-underline-offset: 2px;
  text-decoration-thickness: 1px;
  transition: color 0.12s ease, text-decoration-color 0.12s ease;
  text-decoration-line: underline;
  text-decoration-color: var(--link-underline);
}

.chat-markdown :deep(a:hover) {
  color: var(--link-color-hover);
  text-decoration-color: var(--link-color-hover);
}

/* Blockquotes */
.chat-markdown :deep(blockquote) {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 2.5px solid var(--md-blockquote-border);
  border-radius: 0 4px 4px 0;
  background: var(--md-blockquote-bg);
}

.chat-markdown :deep(blockquote p) {
  margin: 2px 0;
  color: var(--text-secondary);
  font-size: 0.94em;
}

/* Code */
.chat-markdown :deep(pre) {
  margin: 6px 0;
  padding: 9px 11px;
  border-radius: 6px;
  border: 1px solid var(--md-code-border);
  background: var(--md-pre-bg);
  overflow-x: auto;
  line-height: 1.52;
}

.chat-markdown :deep(code) {
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  font-size: 0.87em;
}

.chat-markdown :deep(p code),
.chat-markdown :deep(li code),
.chat-markdown :deep(td code),
.chat-markdown :deep(th code) {
  padding: 0.5px 4.5px;
  border-radius: 3px;
  border: 1px solid var(--md-code-border);
  background: var(--md-code-bg);
}

/* Code block container (with line numbers) */
.chat-markdown :deep(.code-block-container) {
  display: flex;
  position: relative;
  margin: 6px 0;
  border-radius: 6px;
  border: 1px solid var(--md-code-border);
  background: var(--md-pre-bg);
  overflow-x: auto;
}

.chat-markdown :deep(.code-block-container pre) {
  margin: 0;
  padding: 0;
  border: none;
  background: transparent;
  overflow: visible;
}

.chat-markdown :deep(.code-line-numbers) {
  display: flex;
  flex-direction: column;
  padding: 10px 8px;
  background: rgba(0, 0, 0, 0.03);
  border-right: 1px solid var(--md-code-border);
  text-align: right;
  user-select: none;
  min-width: 40px;
}

.chat-markdown :deep(.line-number) {
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  font-size: 0.87em;
  line-height: 1.52;
  color: var(--text-tertiary);
  padding: 0 4px;
}

.chat-markdown :deep(.code-content) {
  flex: 1;
  padding: 10px 12px;
  overflow-x: auto;
  min-width: 0;
}

.chat-markdown :deep(.code-content code) {
  display: block;
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
  font-size: 0.87em;
  line-height: 1.52;
  white-space: pre;
}

.chat-markdown :deep(.code-copy-btn) {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 4px 6px;
  border: 1px solid var(--md-code-border);
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--text-secondary);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease;
}

.chat-markdown :deep(.code-block-container:hover .code-copy-btn) {
  opacity: 1;
}

.chat-markdown :deep(.code-copy-btn:hover) {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.chat-markdown :deep(.code-copy-btn.copied) {
  color: var(--link-color);
}

/* Horizontal rule */
.chat-markdown :deep(hr) {
  border: 0;
  height: 1px;
  background: var(--border-color);
  margin: 10px 0;
}

/* Strong / Em */
.chat-markdown :deep(strong) {
  font-weight: 600;
}

.chat-markdown :deep(em) {
  font-style: italic;
}

/* Images */
.chat-markdown :deep(img) {
  max-width: 100%;
  border-radius: 6px;
  margin: 4px 0;
}

/* KaTeX */
.chat-markdown :deep(.katex-display) {
  margin: 8px 0;
  overflow-x: auto;
}

/* Responsive */
@media (max-width: 1200px) {
  .chat-side-card {
    min-height: auto;
  }

  .chat-main-column {
    height: auto;
    min-height: 0;
  }

  .chat-transcript {
    min-height: 320px;
    max-height: 52vh;
  }
}

@media (max-width: 640px) {
  .chat-side-stats {
    grid-template-columns: 1fr;
  }

  .chat-bubble {
    max-width: 96%;
  }
}
</style>
