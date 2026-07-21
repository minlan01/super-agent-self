<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import {
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NModal,
  NPopconfirm,
  NScrollbar,
  NSpace,
  NSwitch,
  NTag,
  NText,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  ContractOutline,
  ExpandOutline,
  SendOutline,
  StopCircleOutline,
  TimeOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useOfficeStore } from '@/stores/office'
import { useChatStore } from '@/stores/chat'
import { useWebSocketStore } from '@/stores/websocket'
import { useConfigStore } from '@/stores/config'
import { useSkillStore } from '@/stores/skill'
import { useQuickReplies } from '@/composables/useQuickReplies'
import { useSlashCommands } from '@/composables/useSlashCommands'
import ChatHeader from './chat/ChatHeader.vue'
import ChatSkillSelector from './chat/ChatSkillSelector.vue'
import ChatMessageBubble from './chat/ChatMessageBubble.vue'
import { truncate } from '@/utils/format'

import type {
  ChatMessage,
  ChatMessageContent,
  ConfiguredModelOption,
  RenderMessage,
  Skill,
  SlashCommandPreset,
  SlashSuggestionItem,
  SubagentsSubcommandPreset,
  SessionsUsageSession,
} from '@/api/types'
import { getMessageContent, formatDurationMs } from '@/utils/chat-parser'

const props = withDefaults(
  defineProps<{
    title?: string
  }>(),
  {
    title: '',
  }
)

const message = useMessage()
const { t, locale } = useI18n()
const officeStore = useOfficeStore()
const chatStore = useChatStore()
const wsStore = useWebSocketStore()
const configStore = useConfigStore()
const skillStore = useSkillStore()
const draft = ref('')
const scrollRef = ref<InstanceType<typeof NScrollbar> | null>(null)
const expandedScrollRef = ref<InstanceType<typeof NScrollbar> | null>(null)
const showExpandedModal = ref(false)
const autoFollowBottom = ref(true)
const aborting = ref(false)
const nowMs = ref(Date.now())
let nowTimer: ReturnType<typeof setInterval> | null = null

const {
  quickReplySearch,
  showQuickReplyModal,
  quickReplyModalMode,
  editingQuickReplyId,
  quickReplyForm,
  quickReplies,
  filteredQuickReplies,
  loadQuickReplies,
  openCreateQuickReply,
  openEditQuickReply,
  handleDeleteQuickReply,
  handleInsertQuickReply,
  handleSendQuickReply,
  handleSaveQuickReply,
} = useQuickReplies(draft, message)

type SessionTokenUsage = {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  total: number
}

const sessionTokenUsage = ref<SessionTokenUsage | null>(null)
const sessionTokenUsageLoading = ref(false)
let sessionTokenUsageRequestId = 0

function normalizeTokenValue(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, Math.round(value))
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return Math.max(0, Math.round(parsed))
    }
  }
  return 0
}

function createSessionTokenUsage(params: {
  input: unknown
  output: unknown
  cacheRead?: unknown
  cacheWrite?: unknown
  total?: unknown
}): SessionTokenUsage {
  const inputValue = normalizeTokenValue(params.input)
  const outputValue = normalizeTokenValue(params.output)
  const cacheReadValue = normalizeTokenValue(params.cacheRead)
  const cacheWriteValue = normalizeTokenValue(params.cacheWrite)
  const totalFromParts = inputValue + outputValue + cacheReadValue + cacheWriteValue
  const totalValue = params.total === undefined
    ? totalFromParts
    : normalizeTokenValue(params.total)

  return {
    input: inputValue,
    output: outputValue,
    cacheRead: cacheReadValue,
    cacheWrite: cacheWriteValue,
    total: totalValue,
  }
}

const sessionTokenUsageFromList = computed<SessionTokenUsage | null>(() => {
  const tokenUsage = selectedSession.value?.tokenUsage
  if (!tokenUsage) return null
  return createSessionTokenUsage({
    input: tokenUsage.totalInput,
    output: tokenUsage.totalOutput,
    total: tokenUsage.totalInput + tokenUsage.totalOutput,
  })
})

const currentSessionTokenUsage = computed<SessionTokenUsage | null>(() =>
  sessionTokenUsage.value || sessionTokenUsageFromList.value
)

function formatTokenCount(value: number): string {
  return new Intl.NumberFormat(locale.value, { maximumFractionDigits: 0 }).format(Math.max(0, value))
}

const sessionTokenMetricTags = computed(() => {
  const usage = currentSessionTokenUsage.value
  if (!usage) return []

  return [
    { key: 'total', label: t('pages.chat.tokens.total'), value: formatTokenCount(usage.total), highlight: true },
    { key: 'input', label: t('pages.chat.tokens.input'), value: formatTokenCount(usage.input), highlight: false },
    { key: 'output', label: t('pages.chat.tokens.output'), value: formatTokenCount(usage.output), highlight: false },
    { key: 'cacheRead', label: t('pages.chat.tokens.cacheRead'), value: formatTokenCount(usage.cacheRead), highlight: false },
    { key: 'cacheWrite', label: t('pages.chat.tokens.cacheWrite'), value: formatTokenCount(usage.cacheWrite), highlight: false },
  ]
})

const sessionTokenStatusText = computed(() =>
  sessionTokenUsageLoading.value
    ? t('pages.chat.tokens.loading')
    : t('pages.chat.tokens.unavailable')
)

function resolveUsageSession(sessions: SessionsUsageSession[], key: string): SessionsUsageSession | null {
  if (sessions.length === 0) return null
  const normalized = key.trim()
  const found = sessions.find((item) => item.key === normalized)
  return found || null
}

async function fetchSessionTokenUsage(rawKey: string) {
  const key = rawKey.trim()
  sessionTokenUsageRequestId += 1
  const requestId = sessionTokenUsageRequestId

  if (!key) {
    sessionTokenUsage.value = null
    sessionTokenUsageLoading.value = false
    return
  }

  sessionTokenUsage.value = null
  sessionTokenUsageLoading.value = true

  try {
    const usageResult = await wsStore.rpc.getSessionsUsage({
      key,
      limit: 1,
    })
    if (requestId !== sessionTokenUsageRequestId) return

    const usageSession = resolveUsageSession(usageResult.sessions || [], key)
    if (!usageSession?.usage) {
      sessionTokenUsage.value = null
      return
    }

    const usage = usageSession.usage
    sessionTokenUsage.value = createSessionTokenUsage({
      input: usage.input,
      output: usage.output,
      cacheRead: usage.cacheRead,
      cacheWrite: usage.cacheWrite,
      total: usage.totalTokens,
    })
  } catch (error) {
    if (requestId !== sessionTokenUsageRequestId) return
    sessionTokenUsage.value = null
    console.warn('[AgentChatPanel] 获取会话 token 用量失败:', error)
  } finally {
    if (requestId === sessionTokenUsageRequestId) {
      sessionTokenUsageLoading.value = false
    }
  }
}

const selectedAgent = computed(() => officeStore.selectedAgent)
const selectedSession = computed(() => officeStore.selectedSession)
const selectedSessionKey = computed(() => officeStore.selectedSessionKey)
const executionInProgress = computed(() => officeStore.executionInProgress)
const activeTasks = computed(() => officeStore.activeTasks)

const panelTitle = computed(() => props.title || t('pages.office.chat.title'))

const expandedToolCalls = shallowRef(new Set<string>())
const expandedToolResults = shallowRef(new Set<string>())
const showAgentDetails = ref(false)
const eventCleanups: Array<() => void> = []

// ── Slash Commands (composable) ──────────────────────────────────────────────

const {
  selectedSlashCommandIndex,
  slashMode,
  slashSuggestions,
  activeSlashSuggestion,
  applySlashSuggestion,
  handleSlashKeydown,
} = useSlashCommands(draft, { skillStore, configStore })

async function handleDraftKeydown(e: KeyboardEvent) {
  if (await handleSlashKeydown(e)) return

  const isEnter = e.key === 'Enter'
  const canSend = !e.shiftKey && !e.isComposing

  if ((e.metaKey || e.ctrlKey) && isEnter) {
    e.preventDefault()
    await handleSend()
    return
  }

  if (isEnter && canSend) {
    e.preventDefault()
    await handleSend()
  }
}

interface ToolCallItemView {
  id?: string
  name: string
  command?: string
  workdir?: string
  timeout?: number
  partialJson?: string
  argumentsJson?: string
}

interface ThinkingItemView {
  type?: string
  text: string
  signatureId?: string
  summaryText?: string
  hasEncryptedSignature: boolean
}

interface ToolResultItemView {
  id?: string
  name?: string
  status?: string
  content: string
}

interface ToolValidationErrorItemView {
  toolName: string
  issues: string[]
  argumentsText?: string
}

interface ImageItemView {
  mimeType?: string
  bytes?: number
  data?: string
  mediaPath?: string
  url?: string
}

interface StructuredMessageView {
  toolCalls: ToolCallItemView[]
  thinkings: ThinkingItemView[]
  toolResults: ToolResultItemView[]
  validationErrors: ToolValidationErrorItemView[]
  plainTexts: string[]
  images: ImageItemView[]
}

const BOTTOM_GAP = 32
let pendingForceScroll = false
let pendingScroll = false
let destroyed = false

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

async function copyMessageContent(entry: RenderMessage) {
  const content = getMessageContent(entry)
  try {
    await navigator.clipboard.writeText(content)
    message.success(t('common.copied'))
  } catch {
    message.error(t('common.copyFailed'))
  }
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    message.success(t('common.copied'))
  } catch {
    message.error(t('common.copyFailed'))
  }
}

const imagePreviewUrl = ref<string | null>(null)
const showImagePreviewModal = ref(false)

function openImagePreview(url: string) {
  imagePreviewUrl.value = url
  showImagePreviewModal.value = true
}

function closeImagePreview() {
  showImagePreviewModal.value = false
  imagePreviewUrl.value = null
}

function asString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function asText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value
      .map((item) => asText(item))
      .filter((item) => item.trim().length > 0)
      .join('\n')
  }
  const row = asRecord(value)
  if (!row) return ''
  if ('text' in row) return asText(row.text)
  if ('content' in row) return asText(row.content)
  if ('message' in row) return asText(row.message)
  if ('output' in row) return asText(row.output)
  try {
    return JSON.stringify(row, null, 2)
  } catch {
    return ''
  }
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function isThinkingOnlyStructuredMessage(structured: StructuredMessageView | null): boolean {
  if (!structured) return false
  if (structured.thinkings.length === 0) return false
  return (
    structured.toolCalls.length === 0 &&
    structured.toolResults.length === 0 &&
    structured.validationErrors.length === 0 &&
    structured.plainTexts.length === 0
  )
}

function parseToolResultMessage(item: ChatMessage): StructuredMessageView | null {
  const toolResults: ToolResultItemView[] = []
  
  let contentText = ''
  if (item.rawContent && Array.isArray(item.rawContent)) {
    for (const part of item.rawContent) {
      if (part.type === 'text' && part.text) {
        contentText = part.text
      }
    }
  } else if (item.content) {
    contentText = item.content
  }
  
  toolResults.push({
    id: item.toolCallId,
    name: item.toolName || 'unknown',
    status: item.isError ? 'error' : undefined,
    content: contentText,
  })
  
  return {
    toolCalls: [],
    thinkings: [],
    toolResults,
    validationErrors: [],
    plainTexts: [],
    images: [],
  }
}

function buildImageUrl(part: ChatMessageContent): string | undefined {
  if (part.data) {
    const mimeType = part.mimeType || 'image/png'
    return `data:${mimeType};base64,${part.data}`
  }
  if (part.mediaPath) {
    let mediaPath = part.mediaPath
    
    // 处理 MEDIA: 前缀
    if (mediaPath.startsWith('MEDIA:')) {
      mediaPath = mediaPath.slice(6)
    }
    
    // 从 file:// URL 中提取相对路径
    // 例如: file:///C:/Users/xxx/.openclaw/media/browser/xxx.png -> browser/xxx.png
    if (mediaPath.startsWith('file://')) {
      // 查找 .openclaw/media/ 后面的相对路径
      const mediaIndex = mediaPath.indexOf('.openclaw/media/')
      if (mediaIndex !== -1) {
        mediaPath = mediaPath.slice(mediaIndex + '.openclaw/media/'.length)
      } else {
        // 如果没有找到标准路径，尝试提取文件名
        const lastSlash = mediaPath.lastIndexOf('/')
        if (lastSlash !== -1) {
          mediaPath = `browser/${mediaPath.slice(lastSlash + 1)}`
        }
      }
    }
    
    return `/api/media?path=${encodeURIComponent(mediaPath)}`
  }
  return undefined
}

/**
 * 从路径中提取相对于媒体目录的相对路径
 */
function normalizeMediaPath(path: string): string {
  // 处理 MEDIA: 前缀
  if (path.startsWith('MEDIA:')) {
    path = path.slice(6)
  }
  
  // 从 file:// URL 中提取相对路径
  // 例如: file:///C:/Users/xxx/.openclaw/media/browser/xxx.png -> browser/xxx.png
  if (path.startsWith('file://')) {
    const mediaIndex = path.indexOf('.openclaw/media/')
    if (mediaIndex !== -1) {
      return path.slice(mediaIndex + '.openclaw/media/'.length)
    }
    // 如果没有找到标准路径，尝试提取文件名
    const lastSlash = path.lastIndexOf('/')
    if (lastSlash !== -1) {
      return `browser/${path.slice(lastSlash + 1)}`
    }
  }
  
  return path
}

function extractImageFromText(text: string): { images: ImageItemView[]; cleanedText: string } {
  const images: ImageItemView[] = []
  let cleanedText = text
  
  const mdImageRegex = /!\[([^\]]*)\]\(([^)]+)\)/g
  let match
  while ((match = mdImageRegex.exec(text)) !== null) {
    const imagePath = match[2]
    if (imagePath && imagePath.match(/\.(png|jpg|jpeg|gif|webp|bmp)$/i)) {
      const normalizedPath = normalizeMediaPath(imagePath)
      const imageUrl = `/api/media?path=${encodeURIComponent(normalizedPath)}`
      images.push({
        mimeType: `image/${imagePath.split('.').pop()?.toLowerCase() || 'png'}`,
        url: imageUrl,
      })
      cleanedText = cleanedText.replace(match[0], '').trim()
    }
  }
  
  const mediaPathRegex = /MEDIA:([^\s\n]+)/g
  while ((match = mediaPathRegex.exec(text)) !== null) {
    const imagePath = match[1]
    if (imagePath && imagePath.match(/\.(png|jpg|jpeg|gif|webp|bmp)$/i)) {
      const normalizedPath = normalizeMediaPath(imagePath)
      const imageUrl = `/api/media?path=${encodeURIComponent(normalizedPath)}`
      images.push({
        mimeType: `image/${imagePath.split('.').pop()?.toLowerCase() || 'png'}`,
        url: imageUrl,
      })
      cleanedText = cleanedText.replace(match[0], '').trim()
    }
  }
  
  return { images, cleanedText }
}

function parseRawContent(rawContent: ChatMessageContent[]): StructuredMessageView | null {
  const toolCalls: ToolCallItemView[] = []
  const thinkings: ThinkingItemView[] = []
  const toolResults: ToolResultItemView[] = []
  const plainTexts: string[] = []
  const images: ImageItemView[] = []

  for (const part of rawContent) {
    if (part.type === 'text' && part.text) {
      const { images: extractedImages, cleanedText } = extractImageFromText(part.text)
      images.push(...extractedImages)
      
      const trimmedText = cleanedText.trim()
      if (trimmedText.match(/\.(png|jpg|jpeg|gif|webp|bmp)$/i)) {
        // Add "browser/" prefix for image filenames without a path
        const imagePath = trimmedText.includes('/') ? trimmedText : `browser/${trimmedText}`
        const imageUrl = `/api/media?path=${encodeURIComponent(imagePath)}`
        images.push({
          mimeType: `image/${trimmedText.split('.').pop()?.toLowerCase() || 'png'}`,
          url: imageUrl,
        })
        // Also add the image filename to plainTexts to display it as text
        plainTexts.push(cleanedText)
      } else if (trimmedText) {
        plainTexts.push(cleanedText)
      }
    }
    
    if (part.type === 'thinking' && part.thinking) {
      thinkings.push({
        text: part.thinking,
        hasEncryptedSignature: false,
      })
    }
    
    if (part.type === 'tool_call') {
      let argumentsJson: string | undefined
      if (part.arguments) {
        try {
          argumentsJson = JSON.stringify(part.arguments, null, 2)
        } catch {
          argumentsJson = String(part.arguments)
        }
      }
      toolCalls.push({
        id: part.id,
        name: part.name || 'unknown',
        argumentsJson,
      })
    }
    
    if (part.type === 'tool_result') {
      let contentText: string
      const rawContent = part.content
      if (rawContent && typeof rawContent === 'object' && !Array.isArray(rawContent)) {
        try {
          contentText = JSON.stringify(rawContent, null, 2)
        } catch {
          contentText = String(rawContent)
        }
      } else if (typeof rawContent === 'string') {
        contentText = rawContent
      } else {
        contentText = String(rawContent || '')
      }
      
      toolResults.push({
        id: part.id,
        name: part.name || 'unknown',
        status: part.isError ? 'error' : undefined,
        content: contentText,
      })
    }

    if (part.type === 'image') {
      const imageUrl = buildImageUrl(part)
      images.push({
        mimeType: part.mimeType,
        bytes: part.bytes,
        data: part.data,
        mediaPath: part.mediaPath,
        url: imageUrl,
      })
    }
  }

  if (toolCalls.length === 0 && thinkings.length === 0 && toolResults.length === 0 && plainTexts.length === 0 && images.length === 0) {
    return null
  }

  return {
    toolCalls,
    thinkings,
    toolResults,
    validationErrors: [],
    plainTexts,
    images,
  }
}

function stripCodeFence(text: string): string {
  const value = text.trim()
  if (!value.startsWith('```') || !value.endsWith('```')) return value
  const lines = value.split('\n')
  if (lines.length < 2) return value
  return lines.slice(1, -1).join('\n').trim()
}

function decodeEscapedJsonText(text: string): string | null {
  const normalized = text.trim()
  if (!normalized.includes('\\"')) return null
  try {
    const wrapped = `"${normalized.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
    const decoded = JSON.parse(wrapped)
    if (typeof decoded === 'string' && decoded.trim()) {
      return decoded.trim()
    }
  } catch {
    return null
  }
  return null
}

function looksLikeJsonString(value: string): boolean {
  const text = value.trim()
  if (!text) return false
  return (
    text.startsWith('{') ||
    text.startsWith('[') ||
    text.startsWith('{\\') ||
    text.startsWith('[\\') ||
    (text.startsWith('"') && text.endsWith('"'))
  )
}

function unwrapJsonValue(value: unknown, depth = 0): unknown {
  if (depth > 3) return value
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!looksLikeJsonString(text)) return value
  try {
    const parsed = JSON.parse(text)
    return unwrapJsonValue(parsed, depth + 1)
  } catch {
    return value
  }
}

function parseSingleJsonValue(text: string): unknown | null {
  const normalized = text.trim()
  if (!normalized) return null

  const candidates: string[] = [normalized]
  const decoded = decodeEscapedJsonText(normalized)
  if (decoded && decoded !== normalized) {
    candidates.push(decoded)
  }

  for (const candidate of candidates) {
    try {
      return unwrapJsonValue(JSON.parse(candidate))
    } catch {
      // try next
    }
  }

  return null
}

function splitLeadingJsonValue(line: string): { parsed: unknown; rest: string } | null {
  const text = line.trimStart()
  if (!text || (text[0] !== '{' && text[0] !== '[')) return null

  let inString = false
  let escaped = false
  let depth = 0

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (inString) {
      if (escaped) {
        escaped = false
        continue
      }
      if (ch === '\\') {
        escaped = true
        continue
      }
      if (ch === '"') {
        inString = false
      }
      continue
    }

    if (ch === '"') {
      inString = true
      continue
    }

    if (ch === '{' || ch === '[') {
      depth += 1
      continue
    }

    if (ch === '}' || ch === ']') {
      depth -= 1
      if (depth !== 0) continue

      const jsonText = text.slice(0, i + 1)
      const parsed = parseSingleJsonValue(jsonText)
      if (parsed == null) return null

      const rest = text.slice(i + 1).trim()
      return {
        parsed,
        rest,
      }
    }
  }

  return null
}

function parseJsonItems(content: string): { items: unknown[]; plainLines: string[] } | null {
  const normalized = stripCodeFence(content).trim()
  if (!normalized) return null

  const rawItems: unknown[] = []
  const plainLines: string[] = []
  const parsed = parseSingleJsonValue(normalized)
  if (parsed != null) {
    if (Array.isArray(parsed)) {
      for (const item of parsed) {
        rawItems.push(unwrapJsonValue(item))
      }
    } else {
      rawItems.push(parsed)
    }
    return {
      items: rawItems,
      plainLines,
    }
  }

  const lines = normalized
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return null
  for (const line of lines) {
    const parsedLine = parseSingleJsonValue(line)
    if (parsedLine == null) {
      const split = splitLeadingJsonValue(line)
      if (split) {
        const parsedValue = split.parsed
        if (Array.isArray(parsedValue)) {
          for (const item of parsedValue) {
            rawItems.push(unwrapJsonValue(item))
          }
        } else {
          rawItems.push(parsedValue)
        }

        if (split.rest) {
          plainLines.push(split.rest)
        }
        continue
      }

      plainLines.push(line)
      continue
    }
    if (Array.isArray(parsedLine)) {
      for (const item of parsedLine) {
        rawItems.push(unwrapJsonValue(item))
      }
      continue
    }
    rawItems.push(parsedLine)
  }

  if (!rawItems.length) return null
  return {
    items: rawItems,
    plainLines,
  }
}

function parseThinkingSignature(value: unknown): {
  signatureId?: string
  summaryText?: string
  hasEncryptedSignature: boolean
} {
  const row = asRecord(unwrapJsonValue(value))
  if (!row) {
    return {
      hasEncryptedSignature: false,
    }
  }
  const signatureId = asString(row.id) || undefined
  const summaryArray = Array.isArray(row.summary) ? row.summary : []
  let summaryText = ''
  for (const item of summaryArray) {
    const text = asText(item).trim()
    if (text) {
      summaryText = text
      break
    }
  }
  const encrypted = asString(row.encrypted_content)
  return {
    signatureId,
    summaryText: summaryText || undefined,
    hasEncryptedSignature: !!encrypted,
  }
}

function parseToolValidationError(content: string): ToolValidationErrorItemView | null {
  const normalized = stripCodeFence(content).trim()
  if (!normalized) return null

  const lines = normalized.split('\n')
  const headerIndex = lines.findIndex((line) => /validation failed for tool/i.test(line))
  if (headerIndex < 0) return null

  const header = lines[headerIndex]?.trim() || ''
  const toolMatch = header.match(/validation failed for tool\s+["'`]?(.+?)["'`]?:?\s*$/i)
  const toolName = toolMatch?.[1]?.trim() || 'unknown'

  const argsMarkerIndex = lines.findIndex((line, idx) => {
    if (idx <= headerIndex) return false
    return /^\s*received arguments\s*:?\s*$/i.test(line)
  })

  const issueSliceEnd = argsMarkerIndex >= 0 ? argsMarkerIndex : lines.length
  const issues = lines
    .slice(headerIndex + 1, issueSliceEnd)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^-\s*/, '').trim())
    .filter(Boolean)

  let argumentsText = ''
  if (argsMarkerIndex >= 0) {
    const rawArguments = lines.slice(argsMarkerIndex + 1).join('\n').trim()
    const normalizedArguments = stripCodeFence(rawArguments).trim()
    if (rawArguments) {
      const parsedArgs = parseSingleJsonValue(normalizedArguments || rawArguments)
      if (parsedArgs == null) {
        argumentsText = normalizedArguments || rawArguments
      } else if (typeof parsedArgs === 'string') {
        argumentsText = parsedArgs
      } else {
        try {
          argumentsText = JSON.stringify(parsedArgs, null, 2)
        } catch {
          argumentsText = rawArguments
        }
      }
    }
  }

  if (!toolName && issues.length === 0 && !argumentsText) return null
  return {
    toolName,
    issues,
    argumentsText: argumentsText || undefined,
  }
}

function parseStructuredMessage(content: string): StructuredMessageView | null {
  const parsed = parseJsonItems(content)
  if (!parsed?.items.length) {
    const validationError = parseToolValidationError(content)
    if (!validationError) return null
    return {
      toolCalls: [],
      thinkings: [],
      toolResults: [],
      validationErrors: [validationError],
      plainTexts: [],
      images: [],
    }
  }
  const rawItems = parsed.items

  const toolCalls: ToolCallItemView[] = []
  const thinkings: ThinkingItemView[] = []
  const toolResults: ToolResultItemView[] = []
  let recognized = 0

  for (const rowValue of rawItems) {
    const row = asRecord(unwrapJsonValue(rowValue))
    if (!row) continue
    const typeRaw = asString(row.type).toLowerCase()
    const type = typeRaw ||
      ('thinking' in row || 'thinkingSignature' in row
        ? 'thinking'
        : ('arguments' in row && ('name' in row || 'tool' in row) 
          ? 'toolcall' 
          : (('tool_call_id' in row || 'toolCallId' in row || 'call_id' in row) && ('content' in row || 'output' in row || 'result' in row)
            ? 'toolresult'
            : '')))

    if (type === 'toolcall' || type === 'tool_call') {
      const args = asRecord(row.arguments ?? row.args ?? row.params)
      let argumentsJson: string | undefined
      const rawArgs = row.arguments ?? row.args ?? row.params
      if (rawArgs) {
        try {
          if (typeof rawArgs === 'string') {
            argumentsJson = rawArgs
          } else {
            argumentsJson = JSON.stringify(rawArgs, null, 2)
          }
        } catch {
          argumentsJson = String(rawArgs)
        }
      }
      toolCalls.push({
        id: asString(row.id || row.tool_call_id || row.toolCallId || row.call_id) || undefined,
        name: asString(row.name || row.tool || row.toolName || row.tool_name) || 'unknown',
        command: args ? asString(args.command || args.cmd) || undefined : undefined,
        workdir: args ? asString(args.workdir || args.cwd || args.dir) || undefined : undefined,
        timeout: args ? asNumber(args.timeout) : undefined,
        partialJson: asString(row.partialJson || row.partial_json) || undefined,
        argumentsJson,
      })
      recognized += 1
      continue
    }

    if (type === 'thinking' || type === 'reasoning') {
      const signature = parseThinkingSignature(row.thinkingSignature ?? row.signature)
      const text = asText(row.thinking ?? row.text ?? row.message).trim()
      const hasSignature = signature.signatureId || signature.summaryText || signature.hasEncryptedSignature
      if (!text && !hasSignature) continue
      if (!text && hasSignature && parsed.plainLines.length > 0) {
        recognized += 1
        continue
      }
      thinkings.push({
        type: type || undefined,
        text,
        signatureId: signature.signatureId,
        summaryText: signature.summaryText,
        hasEncryptedSignature: signature.hasEncryptedSignature,
      })
      recognized += 1
      continue
    }

    if (type === 'toolresult' || type === 'tool_result') {
      let contentText: string
      const rawContent = row.content ?? row.output ?? row.result ?? row.message ?? row.response
      
      if (rawContent && typeof rawContent === 'object' && !Array.isArray(rawContent)) {
        try {
          contentText = JSON.stringify(rawContent, null, 2)
        } catch {
          contentText = asText(rawContent)
        }
      } else {
        contentText = asText(rawContent)
      }
      
      if (!contentText.trim()) continue
      toolResults.push({
        id: asString(row.id || row.tool_call_id || row.toolCallId || row.call_id) || undefined,
        name: asString(row.name || row.tool || row.toolName || row.tool_name) || undefined,
        status: asString(row.status || row.state || row.error) || undefined,
        content: contentText,
      })
      recognized += 1
      continue
    }
  }

  if (!recognized) return null
  return {
    toolCalls,
    thinkings,
    toolResults,
    validationErrors: [],
    plainTexts: parsed.plainLines,
    images: [],
  }
}

const messageList = computed(() => chatStore.messages)

const visibleMessageEntries = computed<RenderMessage[]>(() => {
  const list = messageList.value
  const rendered: RenderMessage[] = []

  for (let idx = 0; idx < list.length; idx += 1) {
    const item = list[idx]
    if (!item) continue
    
    if (item.role === 'tool') {
      const structured = parseToolResultMessage(item)
      if (structured) {
        rendered.push({
          key: item.id || `tool-${idx}`,
          item,
          structured,
        })
      }
      continue
    }
    
    if (item.rawContent && Array.isArray(item.rawContent)) {
      const structured = parseRawContent(item.rawContent)
      if (structured && (structured.toolCalls.length > 0 || structured.thinkings.length > 0 || structured.toolResults.length > 0 || structured.plainTexts.length > 0)) {
        rendered.push({
          key: item.id || `${item.role}-${idx}`,
          item,
          structured,
        })
        continue
      }
    }
    
    const structured = parseStructuredMessage(item.content)
    if (isThinkingOnlyStructuredMessage(structured)) continue
    rendered.push({
      key: item.id || `${item.role}-${idx}`,
      item,
      structured,
    })
  }

  return rendered
})

const currentAgentId = computed(() => {
  const sessionKey = chatStore.sessionKey
  if (!sessionKey) return 'default'
  const match = sessionKey.match(/^agent:([^:]+):/)
  if (match && match[1]) {
    return match[1]
  }
  return 'default'
})

const currentAgentStatus = computed(() => {
  return chatStore.getOrCreateAgentStatus(currentAgentId.value)
})

const agentBusy = computed(() => {
  const phase = currentAgentStatus.value.phase
  return (
    phase === 'sending' ||
    phase === 'waiting' ||
    phase === 'thinking' ||
    phase === 'tool' ||
    phase === 'replying' ||
    phase === 'aborting'
  )
})

const currentToolProgress = computed(() => {
  return chatStore.toolProgress.get(currentAgentId.value) || null
})

const agentBusyToolName = computed(() => {
  if (!agentBusy.value) return ''

  const toolProgress = currentToolProgress.value
  if (toolProgress && toolProgress.phase !== 'result' && toolProgress.name.trim()) {
    return toolProgress.name.trim()
  }

  const phase = currentAgentStatus.value.phase
  if (phase === 'replying' || phase === 'aborting') return ''

  const runId = currentAgentStatus.value.runId
  const list = visibleMessageEntries.value
  let startIndex = 0
  if (runId) {
    const idx = list.findIndex((entry) => entry.item.id === runId)
    if (idx >= 0) startIndex = idx + 1
  }

  for (let i = list.length - 1; i >= startIndex; i -= 1) {
    const entry = list[i]
    if (!entry) continue
    const item = entry.item
    if (item.role !== 'assistant') continue
    const structured = entry.structured
    if (!structured) return ''

    if (structured.toolCalls.length === 0) return ''
    if (structured.toolResults.length >= structured.toolCalls.length) {
      return ''
    }

    const lastToolCall = structured.toolCalls[structured.toolCalls.length - 1]
    if (!lastToolCall?.name) return ''
    const normalized = lastToolCall.name.trim()
    return normalized
  }

  return ''
})

const agentStatusTagType = computed<'default' | 'success' | 'warning' | 'info' | 'error'>(() => {
  if (agentBusyToolName.value) return 'warning'
  const phase = currentAgentStatus.value.phase
  if (phase === 'replying' || phase === 'sending' || phase === 'waiting' || phase === 'thinking') return 'info'
  if (phase === 'tool' || phase === 'aborting' || phase === 'aborted') return 'warning'
  if (phase === 'done') return 'success'
  if (phase === 'error') return 'error'
  return 'default'
})

const agentStatusText = computed(() => {
  if (agentBusyToolName.value) return t('pages.chat.agentStatus.toolCall', { name: agentBusyToolName.value })
  const status = currentAgentStatus.value
  if (status.phase === 'sending') return t('pages.chat.agentStatus.sending')
  if (status.phase === 'waiting') return t('pages.chat.agentStatus.waiting')
  if (status.phase === 'thinking') return status.detail ? status.detail : t('pages.chat.agentStatus.thinking')
  if (status.phase === 'tool') {
    return status.detail
      ? t('pages.chat.agentStatus.toolCall', { name: status.detail })
      : t('pages.chat.agentStatus.toolRunning')
  }
  if (status.phase === 'replying') return t('pages.chat.agentStatus.replying')
  if (status.phase === 'aborting') return t('pages.chat.agentStatus.aborting')
  if (status.phase === 'done') return t('pages.chat.agentStatus.done')
  if (status.phase === 'aborted') return t('pages.chat.agentStatus.aborted')
  if (status.phase === 'error') {
    return status.detail
      ? t('pages.chat.agentStatus.errorWithDetail', { detail: status.detail })
      : t('pages.chat.agentStatus.error')
  }
  return t('pages.chat.agentStatus.idle')
})

const hasAgentDetails = computed(() => {
  if (agentBusy.value) return true
  const agentSteps = chatStore.agentSteps.get(currentAgentId.value)
  if (agentSteps && agentSteps.length > 0) return true
  if (currentToolProgress.value) return true
  return false
})

const toolElapsedMs = computed(() => {
  const progress = currentToolProgress.value
  if (!progress) return 0
  const endAt = progress.phase === 'result' ? progress.updatedAtMs : nowMs.value
  return endAt - progress.startedAtMs
})

function formatClock(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '--:--:--'
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

async function handleAbort() {
  if (aborting.value) return
  if (!agentBusy.value) return

  aborting.value = true
  try {
    await chatStore.abortActiveRun()
    message.info(t('pages.chat.messages.abortRequested'))
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    message.error(t('pages.chat.messages.abortFailed', { reason }))
  } finally {
    aborting.value = false
  }
}

function isNearBottom(scrollbar: InstanceType<typeof NScrollbar> | null): boolean {
  if (!scrollbar) return true
  const el = scrollbar.$el as HTMLElement | undefined
  if (!el) return true
  const containerEl = el.querySelector('.n-scrollbar-container') as HTMLElement | null
  if (!containerEl) return true
  const distance = containerEl.scrollHeight - containerEl.scrollTop - containerEl.clientHeight
  return distance <= BOTTOM_GAP
}

function handleTranscriptScroll() {
  autoFollowBottom.value = isNearBottom(scrollRef.value)
}

function handleExpandedScroll() {
  autoFollowBottom.value = isNearBottom(expandedScrollRef.value)
}

function scrollToBottom(options?: { force?: boolean; expanded?: boolean }) {
  const scrollbar = options?.expanded ? expandedScrollRef.value : scrollRef.value
  if (!scrollbar) return

  const force = options?.force ?? false
  if (!force && !autoFollowBottom.value) return

  nextTick(() => {
    scrollbar.scrollTo({ top: Number.MAX_SAFE_INTEGER })
  })
}

function requestScrollToBottom(options?: { force?: boolean; expanded?: boolean }) {
  const force = options?.force ?? false
  if (!force && !autoFollowBottom.value) return
  if (force) pendingForceScroll = true
  if (pendingScroll) return

  pendingScroll = true
  const schedule =
    typeof queueMicrotask === 'function' ? queueMicrotask : (fn: () => void) => Promise.resolve().then(fn)
  schedule(() => {
    pendingScroll = false
    if (destroyed) return
    const forceNow = pendingForceScroll
    pendingForceScroll = false
    scrollToBottom({ force: forceNow, expanded: options?.expanded })
  })
}

function cancelPendingScroll() {
  destroyed = true
  pendingForceScroll = false
  pendingScroll = false
}

async function handleSend() {
  const content = draft.value.trim()
  if (!content) return
  if (agentBusy.value) return

  try {
    const sessionKey = selectedSessionKey.value || (selectedAgent.value ? `${selectedAgent.value.id}:main` : 'main')
    chatStore.setSessionKey(sessionKey)
    await chatStore.sendMessage(content)
    void fetchSessionTokenUsage(sessionKey)
    draft.value = ''
    await nextTick()
    autoFollowBottom.value = true
    requestScrollToBottom({ force: true })
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    message.error(reason)
  }
}

function openExpandedModal() {
  showExpandedModal.value = true
  nextTick(() => {
    if (expandedScrollRef.value) {
      expandedScrollRef.value.scrollTo({ top: Number.MAX_SAFE_INTEGER })
    }
  })
}

function closeExpandedModal() {
  showExpandedModal.value = false
}

const messageSignature = computed(() => {
  const list = visibleMessageEntries.value
  const last = list.length > 0 ? list[list.length - 1]?.item : null
  const lastContentLength = last?.content ? last.content.length : 0
  return `${list.length}|${last?.id || ''}|${last?.role || ''}|${last?.timestamp || ''}|${lastContentLength}`
})

watch(
  messageSignature,
  async (next, prev) => {
    if (next === prev) return
    requestScrollToBottom()
    requestScrollToBottom({ expanded: true })
  },
  { flush: 'post' }
)

function handleCodeCopy(event: Event) {
  const target = event.target as HTMLElement
  const button = target.closest('.code-copy-btn') as HTMLButtonElement
  if (!button) return

  const code = button.dataset.code || ''
  navigator.clipboard.writeText(code).then(() => {
    button.classList.add('copied')
    button.title = 'Copied!'
    setTimeout(() => {
      button.classList.remove('copied')
      button.title = 'Copy code'
    }, 2000)
  }).catch((err) => {
    console.error('Failed to copy:', err)
  })
}

onMounted(async () => {
  nowTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)

  loadQuickReplies()
  document.addEventListener('click', handleCodeCopy)

  eventCleanups.push(
    wsStore.subscribe('event', (evt: unknown) => {
      const data = evt as { event?: string; payload?: unknown }
      const eventName = data.event || ''
      if (
        eventName === 'chat' ||
        eventName.startsWith('chat.') ||
        eventName === 'agent' ||
        eventName.startsWith('agent.') ||
        eventName.startsWith('tool.') ||
        eventName.startsWith('model.')
      ) {
        const name = eventName.toLowerCase()
        const isStreamingEvent =
          name.includes('stream') ||
          name.includes('delta') ||
          name.includes('chunk') ||
          name.includes('partial')
        chatStore.handleAgentStatusEvent(eventName, data.payload)
        chatStore.handleRealtimeEvent(data.payload, {
          refreshHistory: false,
          streaming: isStreamingEvent,
        })
      }
    })
  )

  const sessionKey = selectedSessionKey.value || (selectedAgent.value ? `${selectedAgent.value.id}:main` : null)
  if (sessionKey) {
    chatStore.setSessionKey(sessionKey)
    await chatStore.fetchHistory(sessionKey)
    await nextTick()
    autoFollowBottom.value = true
    requestScrollToBottom({ force: true })
    requestScrollToBottom({ force: true, expanded: true })
  }
})

onUnmounted(() => {
  eventCleanups.forEach((cleanup) => cleanup())
  chatStore.clearTimers()
  cancelPendingScroll()
  if (nowTimer) {
    clearInterval(nowTimer)
    nowTimer = null
  }
  document.removeEventListener('click', handleCodeCopy)
})

watch(selectedSessionKey, async (newSessionKey) => {
  if (newSessionKey) {
    chatStore.setSessionKey(newSessionKey)
    await chatStore.fetchHistory(newSessionKey)
    await nextTick()
    autoFollowBottom.value = true
    requestScrollToBottom({ force: true })
    requestScrollToBottom({ force: true, expanded: true })
  }
})
</script>

<template>
  <NCard :title="panelTitle" size="small" embedded class="chat-panel-card">
    <template #header-extra>
      <ChatHeader
        :token-metrics="sessionTokenMetricTags"
        :has-session-key="!!selectedSessionKey"
        :token-status-text="sessionTokenStatusText"
        :execution-in-progress="executionInProgress"
        :agent-display-name="selectedAgent?.name || 'Agent'"
        :session-display-label="selectedSession?.label || selectedSession?.key?.slice(0, 16) || ''"
        :session-tooltip="`${t('pages.office.chat.chattingWith')}: ${selectedAgent?.name || ''} - ${selectedSession?.label || selectedSession?.key || ''}`"
        :auto-follow-bottom="autoFollowBottom"
        @update:auto-follow-bottom="autoFollowBottom = $event"
        @open-expanded="openExpandedModal"
      />
    </template>

    <div class="chat-panel">
      <div v-if="!selectedSessionKey" class="chat-empty">
        <NEmpty :description="t('pages.office.chat.selectSession')" />
      </div>

      <template v-else>
        <div v-if="activeTasks.length > 0" class="active-tasks-bar">
          <NSpace :size="8" align="center">
            <NIcon :component="TimeOutline" :color="'#2080f0'" />
            <NText depth="3" style="font-size: 12px;">
              {{ t('pages.office.chat.activeTasks', { count: activeTasks.length }) }}
            </NText>
          </NSpace>
        </div>

        <NScrollbar ref="scrollRef" class="chat-messages" @scroll="handleTranscriptScroll">
          <div v-if="visibleMessageEntries.length === 0" class="chat-empty">
            <NEmpty :description="t('pages.office.chat.noMessages')" />
          </div>
          <div v-else class="message-list">
            <ChatMessageBubble
              v-for="entry in visibleMessageEntries"
              :key="entry.key"
              :entry="entry"
              :expanded-tool-calls="expandedToolCalls"
              :expanded-tool-results="expandedToolResults"
              @toggle-tool-call="toggleToolCallExpand"
              @toggle-tool-result="toggleToolResultExpand"
              @copy-message="copyMessageContent"
              @copy-text="copyToClipboard"
              @preview-image="openImagePreview"
            />
          </div>
        </NScrollbar>

        <NCollapse class="chat-quick-collapse">
          <NCollapseItem :title="t('pages.chat.quickReplies.title')" name="quick-replies">
            <template #header-extra>
              <NButton size="tiny" type="primary" secondary @click.stop="openCreateQuickReply">{{ t('pages.chat.quickReplies.add') }}</NButton>
            </template>
            <NInput
              v-model:value="quickReplySearch"
              size="small"
              :placeholder="t('pages.chat.quickReplies.searchPlaceholder')"
            />

            <div v-if="filteredQuickReplies.length" class="chat-quick-list">
              <div v-for="item in filteredQuickReplies" :key="item.id" class="chat-quick-item">
                <NSpace justify="space-between" align="start" :wrap="false">
                  <div style="min-width: 0; flex: 1;">
                    <NText strong style="font-size: 12px;">{{ item.title }}</NText>
                    <NText depth="3" style="display: block; font-size: 11px; margin-top: 2px;">
                      {{ truncate(item.content, 60) }}
                    </NText>
                  </div>
                  <NSpace :size="2">
                    <NButton size="tiny" text @click="handleInsertQuickReply(item)">{{ t('pages.chat.quickReplies.insert') }}</NButton>
                    <NButton size="tiny" text type="primary" @click="handleSendQuickReply(item, handleSend)">{{ t('pages.chat.actions.send') }}</NButton>
                    <NButton size="tiny" text @click="openEditQuickReply(item)">{{ t('common.edit') }}</NButton>
                    <NPopconfirm
                      :positive-text="t('common.delete')"
                      :negative-text="t('common.cancel')"
                      @positive-click="handleDeleteQuickReply(item.id)"
                    >
                      <template #trigger>
                        <NButton size="tiny" text type="error">{{ t('common.delete') }}</NButton>
                      </template>
                      {{ t('pages.chat.quickReplies.confirmDelete') }}
                    </NPopconfirm>
                  </NSpace>
                </NSpace>
              </div>
            </div>
            <NEmpty v-else :description="t('pages.chat.quickReplies.empty')" style="padding: 10px 0 6px;" size="small" />
          </NCollapseItem>
        </NCollapse>

        <div class="chat-input">
          <NInput
            v-model:value="draft"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            :placeholder="t('pages.office.chat.inputPlaceholder')"
            @keydown="handleDraftKeydown"
          />

          <ChatSkillSelector
            v-if="slashMode"
            :suggestions="slashSuggestions"
            :selected-index="selectedSlashCommandIndex"
            @update:selected-index="selectedSlashCommandIndex = $event"
            @apply="applySlashSuggestion"
          />
          <div class="chat-compose-status-line">
            <NTag
              size="small"
              :type="agentStatusTagType"
              :bordered="false"
              round
              class="chat-agent-status-tag"
            >
              {{ agentStatusText }}
            </NTag>
            <NButton
              v-if="hasAgentDetails"
              size="tiny"
              text
              @click="showAgentDetails = !showAgentDetails"
            >
              {{ showAgentDetails ? t('pages.chat.agentDetails.hide') : t('pages.chat.agentDetails.show') }}
            </NButton>
          </div>

          <div v-if="showAgentDetails && hasAgentDetails" class="chat-agent-details">
            <NSpace vertical :size="6">
              <NText depth="3" style="font-size: 12px;">
                {{ t('pages.chat.agentDetails.phaseDuration', { duration: formatDurationMs(nowMs - currentAgentStatus.sinceMs) }) }}
              </NText>

              <div v-if="chatStore.agentSteps.get(currentAgentId)?.length" class="chat-agent-steps">
                <div v-for="(step, index) in chatStore.agentSteps.get(currentAgentId)" :key="`step-${step.ts}-${index}`" class="chat-agent-step">
                  <span class="chat-agent-step__time">{{ formatClock(step.ts) }}</span>
                  <span class="chat-agent-step__label">{{ step.label }}</span>
                </div>
              </div>

              <div v-if="currentToolProgress" class="chat-tool-progress">
                <div class="chat-tool-progress__title">
                  <span>{{ t('pages.chat.agentDetails.tool', { name: currentToolProgress.name }) }}</span>
                  <span v-if="currentToolProgress.meta" class="chat-tool-progress__meta">{{ currentToolProgress.meta }}</span>
                </div>
                <div class="chat-tool-progress__kv">
                  <span class="chat-tool-progress__k">{{ t('pages.chat.structured.callId') }}</span>
                  <code class="chat-tool-progress__v">{{ currentToolProgress.toolCallId }}</code>
                  <span class="chat-tool-progress__k">{{ t('pages.chat.agentDetails.phase') }}</span>
                  <code class="chat-tool-progress__v">{{ currentToolProgress.phase }}</code>
                  <span class="chat-tool-progress__k">{{ t('pages.chat.agentDetails.elapsed') }}</span>
                  <code class="chat-tool-progress__v">
                    {{ formatDurationMs(toolElapsedMs) }}
                  </code>
                </div>

                <details v-if="currentToolProgress.argsPreview" class="tool-call-details">
                  <summary>{{ t('pages.chat.structured.viewArgs') }}</summary>
                  <pre>{{ currentToolProgress.argsPreview }}</pre>
                </details>

                <details v-if="currentToolProgress.partialPreview" class="tool-call-details">
                  <summary>{{ t('pages.chat.agentDetails.viewPartialResult') }}</summary>
                  <pre>{{ currentToolProgress.partialPreview }}</pre>
                </details>

                <details v-if="currentToolProgress.resultPreview" class="tool-call-details">
                  <summary>{{ t('pages.chat.agentDetails.viewResult') }}</summary>
                  <pre>{{ currentToolProgress.resultPreview }}</pre>
                </details>
              </div>
            </NSpace>
          </div>

          <div class="chat-actions">
            <NButton
              v-if="agentBusy"
              size="small"
              type="warning"
              secondary
              :loading="aborting"
              :disabled="aborting"
              @click="handleAbort"
            >
              <template #icon><NIcon :component="StopCircleOutline" /></template>
              {{ t('pages.chat.actions.stop') }}
            </NButton>
            <NButton size="small" type="primary" :loading="agentBusy" :disabled="agentBusy || !draft.trim()" @click="handleSend">
              <template #icon><NIcon :component="SendOutline" /></template>
              {{ t('pages.office.chat.send') }}
            </NButton>
          </div>
        </div>
      </template>
    </div>
  </NCard>

  <NModal
    v-model:show="showExpandedModal"
    preset="card"
    :title="t('pages.office.chat.expandedTitle')"
    :style="{ width: '90vw', maxWidth: '1400px', height: '85vh' }"
    :mask-closable="true"
    class="expanded-chat-modal"
  >
    <template #header-extra>
      <NButton size="small" quaternary @click="closeExpandedModal">
        <template #icon>
          <NIcon :component="ContractOutline" />
        </template>
      </NButton>
    </template>

    <div class="expanded-chat-content">
      <div v-if="!selectedSessionKey" class="chat-empty">
        <NEmpty :description="t('pages.office.chat.selectSession')" />
      </div>

      <template v-else>
        <NScrollbar ref="expandedScrollRef" class="expanded-chat-messages" @scroll="handleExpandedScroll">
          <div v-if="visibleMessageEntries.length === 0" class="chat-empty">
            <NEmpty :description="t('pages.office.chat.noMessages')" />
          </div>
          <div v-else class="message-list expanded">
            <ChatMessageBubble
              v-for="entry in visibleMessageEntries"
              :key="entry.key"
              :entry="entry"
              :expanded-tool-calls="expandedToolCalls"
              :expanded-tool-results="expandedToolResults"
              @toggle-tool-call="toggleToolCallExpand"
              @toggle-tool-result="toggleToolResultExpand"
              @copy-message="copyMessageContent"
              @copy-text="copyToClipboard"
              @preview-image="openImagePreview"
            />
          </div>
        </NScrollbar>

        <div class="chat-input expanded">
          <NInput
            v-model:value="draft"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 6 }"
            :placeholder="t('pages.office.chat.inputPlaceholder')"
            @keydown="handleDraftKeydown"
          />

          <ChatSkillSelector
            v-if="slashMode"
            :suggestions="slashSuggestions"
            :selected-index="selectedSlashCommandIndex"
            @update:selected-index="selectedSlashCommandIndex = $event"
            @apply="applySlashSuggestion"
          />
          <div class="chat-compose-status-line">
            <NTag
              size="small"
              :type="agentStatusTagType"
              :bordered="false"
              round
              class="chat-agent-status-tag"
            >
              {{ agentStatusText }}
            </NTag>
            <NButton
              v-if="hasAgentDetails"
              size="tiny"
              text
              @click="showAgentDetails = !showAgentDetails"
            >
              {{ showAgentDetails ? t('pages.chat.agentDetails.hide') : t('pages.chat.agentDetails.show') }}
            </NButton>
          </div>

          <div v-if="showAgentDetails && hasAgentDetails" class="chat-agent-details">
            <NSpace vertical :size="6">
              <NText depth="3" style="font-size: 12px;">
                {{ t('pages.chat.agentDetails.phaseDuration', { duration: formatDurationMs(nowMs - currentAgentStatus.sinceMs) }) }}
              </NText>

              <div v-if="chatStore.agentSteps.get(currentAgentId)?.length" class="chat-agent-steps">
                <div v-for="(step, index) in chatStore.agentSteps.get(currentAgentId)" :key="`step-${step.ts}-${index}`" class="chat-agent-step">
                  <span class="chat-agent-step__time">{{ formatClock(step.ts) }}</span>
                  <span class="chat-agent-step__label">{{ step.label }}</span>
                </div>
              </div>

              <div v-if="currentToolProgress" class="chat-tool-progress">
                <div class="chat-tool-progress__title">
                  <span>{{ t('pages.chat.agentDetails.tool', { name: currentToolProgress.name }) }}</span>
                </div>
                <div class="chat-tool-progress__kv">
                  <span class="chat-tool-progress__k">{{ t('pages.chat.structured.callId') }}</span>
                  <code class="chat-tool-progress__v">{{ currentToolProgress.toolCallId }}</code>
                  <span class="chat-tool-progress__k">{{ t('pages.chat.agentDetails.phase') }}</span>
                  <code class="chat-tool-progress__v">{{ currentToolProgress.phase }}</code>
                  <span class="chat-tool-progress__k">{{ t('pages.chat.agentDetails.elapsed') }}</span>
                  <code class="chat-tool-progress__v">{{ formatDurationMs(toolElapsedMs) }}</code>
                </div>

                <details v-if="currentToolProgress.argsPreview" class="tool-call-details">
                  <summary>{{ t('pages.chat.structured.viewArgs') }}</summary>
                  <pre>{{ currentToolProgress.argsPreview }}</pre>
                </details>

                <details v-if="currentToolProgress.resultPreview" class="tool-call-details">
                  <summary>{{ t('pages.chat.agentDetails.viewResult') }}</summary>
                  <pre>{{ currentToolProgress.resultPreview }}</pre>
                </details>
              </div>
            </NSpace>
          </div>

          <div class="chat-actions">
            <NButton
              v-if="agentBusy"
              size="small"
              type="warning"
              secondary
              :loading="aborting"
              :disabled="aborting"
              @click="handleAbort"
            >
              <template #icon><NIcon :component="StopCircleOutline" /></template>
              {{ t('pages.chat.actions.stop') }}
            </NButton>
            <NButton size="small" type="primary" :loading="agentBusy" :disabled="agentBusy || !draft.trim()" @click="handleSend">
              <template #icon><NIcon :component="SendOutline" /></template>
              {{ t('pages.office.chat.send') }}
            </NButton>
          </div>
        </div>
      </template>
    </div>
  </NModal>

  <NModal
    v-model:show="showQuickReplyModal"
    preset="card"
    :title="quickReplyModalMode === 'edit'
      ? t('pages.chat.quickReplies.modal.editTitle')
      : t('pages.chat.quickReplies.modal.createTitle')"
    style="width: 500px; max-width: calc(100vw - 28px);"
  >
    <NForm label-placement="left" label-width="72">
      <NFormItem :label="t('pages.chat.quickReplies.modal.title')" required>
        <NInput v-model:value="quickReplyForm.title" :placeholder="t('pages.chat.quickReplies.modal.titlePlaceholder')" />
      </NFormItem>
      <NFormItem :label="t('pages.chat.quickReplies.modal.content')" required>
        <NInput
          v-model:value="quickReplyForm.content"
          type="textarea"
          :autosize="{ minRows: 4, maxRows: 10 }"
          :placeholder="t('pages.chat.quickReplies.modal.contentPlaceholder')"
        />
      </NFormItem>
    </NForm>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="showQuickReplyModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="primary" @click="handleSaveQuickReply">
          {{ quickReplyModalMode === 'edit'
            ? t('pages.chat.quickReplies.modal.saveChanges')
            : t('pages.chat.quickReplies.add') }}
        </NButton>
      </NSpace>
    </template>
  </NModal>

  <NModal
    v-model:show="showImagePreviewModal"
    preset="card"
    :title="t('pages.chat.image.preview')"
    style="width: 90vw; max-width: 1200px;"
    :mask-closable="true"
    @update:show="(val: boolean) => { if (!val) closeImagePreview() }"
  >
    <div v-if="imagePreviewUrl" class="image-preview-container">
      <img :src="imagePreviewUrl" class="image-preview-full" />
    </div>
  </NModal>
</template>

<style scoped>
.chat-panel-card {
  height: 1432px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.chat-panel-card :deep(.n-card__content) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding-bottom: 0 !important;
}

.chat-panel-card :deep(.n-card-header) {
  flex-wrap: wrap;
  min-width: 0;
}

.chat-panel-card :deep(.n-card-header__main) {
  flex: 0 0 100%;
  max-width: 100%;
}

.chat-panel-card :deep(.n-card-header__extra) {
  flex: 0 0 100%;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
  margin-top: 4px;
}

.chat-quick-collapse {
  margin-top: 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  background: var(--bg-primary);
}

.chat-quick-collapse :deep(.n-collapse-item__header-main) {
  font-weight: 600;
  font-size: 12px;
}

.chat-quick-collapse :deep(.n-collapse-item__content-wrapper) {
  padding: 0 10px 10px;
}

.chat-quick-list {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 160px;
  overflow-y: auto;
  padding-right: 2px;
}

.chat-quick-item {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 6px 8px;
  background: var(--bg-secondary);
}

.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.active-tasks-bar {
  padding: 8px 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  margin-bottom: 8px;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 0;
}

.message-list.expanded {
  gap: 20px;
}

.chat-input {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-input.expanded {
  margin-top: 16px;
}

.chat-compose-status-line {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chat-agent-status-tag {
  font-size: 12px;
}

.chat-agent-details {
  padding: 10px 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  font-size: 12px;
}

.chat-agent-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
}

.chat-agent-step {
  display: flex;
  gap: 8px;
  font-size: 11px;
}

.chat-agent-step__time {
  color: var(--text-secondary);
  font-family: monospace;
}

.chat-agent-step__label {
  color: var(--text-primary);
}

.chat-tool-progress {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-tertiary);
  border-radius: var(--radius);
}

.chat-tool-progress__title {
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 6px;
}

.chat-tool-progress__meta {
  margin-left: 8px;
  color: var(--text-secondary);
}

.chat-tool-progress__kv {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 12px;
  font-size: 11px;
}

.chat-tool-progress__k {
  color: var(--text-secondary);
}

.chat-tool-progress__v {
  font-family: monospace;
}

.chat-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.expanded-chat-modal :deep(.n-card__content) {
  padding: 0;
}

.expanded-chat-content {
  display: flex;
  flex-direction: column;
  height: calc(85vh - 120px);
  padding: 16px;
}

.expanded-chat-messages {
  flex: 1;
  min-height: 0;
}

.image-preview-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 200px;
}

.image-preview-full {
  max-width: 100%;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 8px;
}
</style>
