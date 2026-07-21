<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NIcon,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  NText,
  NTooltip,
  useMessage,
} from 'naive-ui'
import type { SelectOption } from 'naive-ui'
import { CopyOutline, RefreshOutline, SendOutline, StopCircleOutline, ChevronBackOutline, ChevronForwardOutline, VolumeHighOutline, StopOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useConfigStore } from '@/stores/config'
import { useSessionStore } from '@/stores/session'
import { useSkillStore } from '@/stores/skill'
import { useWebSocketStore } from '@/stores/websocket'
import { formatDate, formatRelativeTime, parseSessionKey, truncate } from '@/utils/format'
import { useQuickReplies } from '@/composables/useQuickReplies'
import { useTokenUsage } from '@/composables/useTokenUsage'
import { useAgentStatus } from '@/composables/useAgentStatus'
import { useMessageList } from '@/composables/useMessageList'
import { useScrollManagement } from '@/composables/useScrollManagement'
import { useSessionManagement } from '@/composables/useSessionManagement'
import { useChatTTS } from '@/composables/useChatTTS'
import { useSlashCommands } from '@/composables/useSlashCommands'
import {
  formatDurationMs,
  getMessageContent,
  roleType,
  looksLikeStreamingPayload,
} from '@/utils/chat-parser'
import { renderChatMarkdown, renderPlainText } from '@/utils/chat-render'
import type {
  AgentInstance,
  ChatMessage,
  ChatMessageContent,
  ConfiguredModelOption,
  ImageItemView,
  RenderMessage,
  Skill,
  SlashCommandPreset,
  SlashSuggestionItem,
  StructuredMessageView,
  SubagentsSubcommand,
  SubagentsSubcommandPreset,
  ThinkingItemView,
  ToolCallItemView,
  ToolResultItemView,
  ToolValidationErrorItemView,
} from '@/api/types'

const message = useMessage()
const route = useRoute()
const chatStore = useChatStore()
const configStore = useConfigStore()
const sessionStore = useSessionStore()
const skillStore = useSkillStore()
const wsStore = useWebSocketStore()
const { t, locale } = useI18n()

const sessionKeyInput = ref('')
const draft = ref('')
const autoFollowBottom = ref(true)
const transcriptRef = ref<HTMLElement | null>(null)
const showAgentDetails = ref(false)
const aborting = ref(false)
const nowMs = ref(Date.now())
let nowTimer: ReturnType<typeof setInterval> | null = null

const sideCollapsed = ref(false)

const { roleFilter, roleFilterOptions, messageList, visibleMessageEntries, renderedMessages } = useMessageList()
const { readStoredSessionKey, writeStoredSessionKey, ensureSessionKey, normalizeSessionSelectValue, refreshingChatData } = useSessionManagement(sessionKeyInput)
const { isNearBottom, handleTranscriptScroll, scrollToBottom, requestScrollToBottom, cancelPendingScroll } = useScrollManagement(transcriptRef, autoFollowBottom)

const expandedToolCalls = shallowRef(new Set<string>())
const expandedToolResults = shallowRef(new Set<string>())

const { playingMessageId, lastPlayedMessageId, ttsIsLoading, ttsSettings, playTTS, stopTTS } = useChatTTS()

// Quick replies (composable)
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

const sessionOptions = computed(() => {
  const seen = new Set<string>()
  const options = sessionStore.sessions
    .map((session) => {
      const key = session.key.trim()
      return {
        key,
        label: session.label,
      }
    })
    .filter((item) => {
      if (!item.key || seen.has(item.key)) return false
      seen.add(item.key)
      return true
    })
    .map((item) => ({
      label: item.label ? `${item.label} (${item.key})` : item.key,
      value: item.key,
    }))

  return options
})

const normalizedSessionKey = computed(() => {
  const input = sessionKeyInput.value.trim()
  if (input) return input
  const firstSession = sessionStore.sessions[0]
  return firstSession?.key || ''
})
const selectedSession = computed(() =>
  sessionStore.sessions.find((session) => session.key === normalizedSessionKey.value) || null
)

const {
  sessionTokenUsage,
  sessionTokenUsageLoading,
  sessionTokenUsageFromList,
  currentSessionTokenUsage,
  sessionTokenMetricTags,
  sessionTokenStatusText,
  formatTokenCount,
  fetchSessionTokenUsage,
  cancelTokenUsageRequests,
} = useTokenUsage(selectedSession, normalizedSessionKey)

const sessionMeta = computed(() => parseSessionKey(normalizedSessionKey.value))
const sessionChannelDisplay = computed(() => {
  const channel = selectedSession.value?.channel?.trim().toLowerCase() || ''
  const parsedChannel = sessionMeta.value.channel?.trim().toLowerCase() || ''
  const isGeneric = (value: string) => !value || value === 'main' || value === 'unknown'

  if (!isGeneric(parsedChannel) && isGeneric(channel)) return parsedChannel
  if (!isGeneric(channel)) return channel
  if (parsedChannel && parsedChannel !== 'unknown') return parsedChannel
  return 'main'
})

const transcriptLoading = computed(() => chatStore.loading && messageList.value.length === 0)
const syncHint = computed(() => {
  if (chatStore.syncing) return t('pages.chat.sync.syncing')
  if (chatStore.lastSyncedAt) {
    return t('pages.chat.sync.syncedAt', { time: formatDate(chatStore.lastSyncedAt) })
  }
  return t('pages.chat.sync.notSynced')
})
const syncTagType = computed<'default' | 'success' | 'warning' | 'info'>(() => {
  if (chatStore.syncing) return 'info'
  if (chatStore.lastError) return 'warning'
  if (chatStore.lastSyncedAt) return 'success'
  return 'default'
})

const {
  currentAgentId,
  currentAgentStatus,
  currentToolProgress,
  agentBusy,
  agentBusyToolName,
  agentStatusTagType,
  agentStatusText,
  hasAgentDetails,
  toolElapsedMs,
} = useAgentStatus(visibleMessageEntries, nowMs)

function formatClock(ts: number): string {
  if (!Number.isFinite(ts) || ts <= 0) return '--:--:--'
  return new Date(ts).toLocaleTimeString(locale.value, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Shanghai',
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

const stats = computed(() => {
  const list = visibleMessageEntries.value
  let user = 0
  let assistant = 0
  let system = 0

  for (const entry of list) {
    const item = entry.item
    if (item.role === 'user') user += 1
    else if (item.role === 'assistant') assistant += 1
    else if (item.role === 'system') system += 1
  }

  const last = list.length > 0 ? list[list.length - 1]?.item : null
  return {
    total: list.length,
    user,
    assistant,
    system,
    lastMessageAt: last?.timestamp ? formatRelativeTime(last.timestamp) : '-',
  }
})

const workspaceRoot = computed(() => configStore.config?.agents?.defaults?.workspace || '~/.openclaw/workspace')
const workspaceQuickReplyDir = computed(() => {
  const root = workspaceRoot.value.endsWith('/') ? workspaceRoot.value.slice(0, -1) : workspaceRoot.value
  return `${root}/prompts/common-replies`
})

function skillSourceLabel(source: Skill['source']): string {
  if (source === 'workspace') return t('pages.skills.sources.workspace')
  if (source === 'managed') return t('pages.skills.sources.managed')
  if (source === 'extra') return t('pages.skills.sources.extra')
  return t('pages.skills.sources.bundled')
}

// ── Slash Commands (composable) ──────────────────────────────────────────────

const availableAgents = computed<AgentInstance[]>(() => {
  const list = configStore.config?.agents?.list || []
  const map = new Map<string, AgentInstance>()
  for (const agent of list) {
    const id = agent.id?.trim()
    if (!id) continue
    if (map.has(id)) continue
    map.set(id, { ...agent, id })
  }
  if (!map.has('main')) {
    map.set('main', { id: 'main' })
  }

  return Array.from(map.values()).sort((a, b) => a.id.localeCompare(b.id))
})

const {
  selectedSlashCommandIndex,
  slashMode,
  slashHasArgs,
  slashSkillMode,
  slashSubagentsMode,
  slashModelMode,
  slashNewMode,
  slashSuggestions,
  activeSlashSuggestion,
  applySlashSuggestion,
  handleSlashKeydown,
} = useSlashCommands(draft, {
  skillStore,
  configStore,
  availableAgents,
  onSend: handleSend,
})

const eventCleanups: Array<() => void> = []

async function loadHistoryForKey(rawKey: string, options?: { force?: boolean }) {
  const key = rawKey.trim() || 'main'
  sessionKeyInput.value = key
  writeStoredSessionKey(key)

  const shouldSkip =
    !options?.force &&
    key === chatStore.sessionKey &&
    !chatStore.loading &&
    !chatStore.syncing
  if (shouldSkip) return

  chatStore.setSessionKey(key)
  void fetchSessionTokenUsage(key)
  await chatStore.fetchHistory(key)
  await nextTick()
  autoFollowBottom.value = true
  requestScrollToBottom({ force: true })
}

function handleSessionKeyChange(value: string | number | null) {
  const key = normalizeSessionSelectValue(value) || 'main'
  sessionKeyInput.value = key
  void loadHistoryForKey(key, { force: true })
}

function roleLabel(role: string): string {
  if (role === 'user') return t('pages.chat.roles.user')
  if (role === 'assistant') return t('pages.chat.roles.assistant')
  if (role === 'tool') return t('pages.chat.roles.tool')
  if (role === 'system') return t('pages.chat.roles.system')
  return role
}

async function handleCopyWorkspaceDir() {
  try {
    await navigator.clipboard.writeText(workspaceQuickReplyDir.value)
    message.success(t('pages.chat.quickReplies.messages.dirCopied'))
  } catch {
    message.warning(t('pages.chat.quickReplies.messages.dirCopyFailed'))
  }
}

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
  void configStore.fetchConfig()
  void skillStore.fetchSkills()
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
          name.includes('partial') ||
          looksLikeStreamingPayload(data.payload)
        chatStore.handleAgentStatusEvent(eventName, data.payload)
        chatStore.handleRealtimeEvent(data.payload, {
          refreshHistory: false,
          streaming: isStreamingEvent,
        })
      }
    })
  )

  await sessionStore.fetchSessions()
  const routeSessionKey = normalizeSessionSelectValue(
    Array.isArray(route.query.session) ? route.query.session[0] : (route.query.session as string | number | null)
  )
  const currentStoreKey = chatStore.sessionKey.trim()
  const storedSessionKey = readStoredSessionKey()
  if (!sessionKeyInput.value && routeSessionKey) {
    sessionKeyInput.value = routeSessionKey
  }
  if (!sessionKeyInput.value && currentStoreKey) {
    sessionKeyInput.value = currentStoreKey
  }
  if (!sessionKeyInput.value && storedSessionKey) {
    sessionKeyInput.value = storedSessionKey
  }

  const firstSession = sessionStore.sessions[0]
  if (!sessionKeyInput.value && firstSession) {
    sessionKeyInput.value = firstSession.key
  }

  await loadHistoryForKey(ensureSessionKey(), { force: true })
})

onUnmounted(() => {
  eventCleanups.forEach((cleanup) => cleanup())
  chatStore.clearTimers()
  cancelPendingScroll()
  cancelTokenUsageRequests()
  if (nowTimer) {
    clearInterval(nowTimer)
    nowTimer = null
  }
  document.removeEventListener('click', handleCodeCopy)
  // Stop TTS playback
  stopTTS()
})

// ---- Auto Play TTS for new assistant messages ----

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
    if (chatStore.sending) return
    
    // Play the message
    lastPlayedMessageId.value = lastAssistantMsg.id
    playTTS(lastAssistantMsg)
  },
  { deep: true }
)

async function handleRefreshChatData() {
  await sessionStore.fetchSessions()
  await loadHistoryForKey(ensureSessionKey(), { force: true })
}

async function handleSend() {
  const content = draft.value.trim()
  if (!content) return
  if (agentBusy.value) return

  try {
    const key = ensureSessionKey()
    chatStore.setSessionKey(key)
    await chatStore.sendMessage(content)
    void fetchSessionTokenUsage(key)
    draft.value = ''
    await nextTick()
    autoFollowBottom.value = true
    requestScrollToBottom({ force: true })
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    message.error(reason)
  }
}
</script>

<template>
  <div class="chat-page">
    <NCard :title="t('pages.chat.title')" class="app-card chat-root-card">
      <template #header-extra>
        <NSpace :size="8" class="app-toolbar">
          <div v-if="sessionTokenMetricTags.length" class="chat-token-metrics">
            <NTag
              v-for="metric in sessionTokenMetricTags"
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
          <NTag v-else size="small" :bordered="false" round class="chat-token-chip chat-token-chip--loading">
            {{ sessionTokenStatusText }}
          </NTag>
          <NButton size="small" class="app-toolbar-btn app-toolbar-btn--refresh" :loading="refreshingChatData" @click="handleRefreshChatData">
            <template #icon><NIcon :component="RefreshOutline" /></template>
            {{ t('pages.chat.actions.refreshChat') }}
          </NButton>
        </NSpace>
      </template>

      <NGrid cols="1 l:3" responsive="screen" :x-gap="12" :y-gap="12" class="chat-grid" :class="{ 'chat-grid--collapsed': sideCollapsed }">
        <NGridItem :span="1" class="chat-grid-side" :class="{ 'chat-grid-side--collapsed': sideCollapsed }">
          <!-- 折叠按钮 -->
          <div class="chat-side-collapse-btn" @click="sideCollapsed = !sideCollapsed">
            <NIcon :component="ChevronBackOutline" size="14" />
          </div>
          
          <NCard v-show="!sideCollapsed" embedded :bordered="false" class="chat-side-card">
            <NSpace vertical :size="12">
              <div class="chat-side-stats">
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.chat.stats.total') }}</span>
                  <strong>{{ stats.total }}</strong>
                </div>
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.chat.stats.assistant') }}</span>
                  <strong>{{ stats.assistant }}</strong>
                </div>
                <div class="chat-stat-item">
                  <span class="chat-stat-label">{{ t('pages.chat.stats.lastMessage') }}</span>
                  <strong>{{ stats.lastMessageAt }}</strong>
                </div>
              </div>

              <div>
                <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.sessionKey') }}</NText>
                <NSelect
                  v-model:value="sessionKeyInput"
                  :options="sessionOptions"
                  filterable
                  tag
                  :placeholder="t('pages.chat.sessionKeyPlaceholder')"
                  style="min-width: 240px; margin-top: 6px;"
                  @update:value="handleSessionKeyChange"
                />
              </div>

              <div class="chat-quick-panel">
                <NSpace justify="space-between" align="center">
                  <NText strong>{{ t('pages.chat.quickReplies.title') }}</NText>
                  <NButton size="tiny" type="primary" secondary @click="openCreateQuickReply">{{ t('pages.chat.quickReplies.add') }}</NButton>
                </NSpace>
                <NInput
                  v-model:value="quickReplySearch"
                  size="small"
                  style="margin-top: 8px;"
                  :placeholder="t('pages.chat.quickReplies.searchPlaceholder')"
                />

                <div v-if="filteredQuickReplies.length" class="chat-quick-list">
                  <div v-for="item in filteredQuickReplies" :key="item.id" class="chat-quick-item">
                    <NSpace justify="space-between" align="start" :wrap="false">
                      <div style="min-width: 0; flex: 1;">
                        <NText strong>{{ item.title }}</NText>
                        <NText depth="3" style="display: block; font-size: 12px; margin-top: 4px;">
                          {{ truncate(item.content, 78) }}
                        </NText>
                      </div>
                      <NSpace :size="2">
                        <NButton size="tiny" text @click="handleInsertQuickReply(item)">{{ t('pages.chat.quickReplies.insert') }}</NButton>
                        <NButton size="tiny" text type="primary" @click="handleSendQuickReply(item)">{{ t('pages.chat.actions.send') }}</NButton>
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
                <NEmpty v-else :description="t('pages.chat.quickReplies.empty')" style="padding: 14px 0 8px;" />

                <div class="chat-quick-footnote">
                  <NText depth="3" style="font-size: 12px;">
                    {{ t('pages.chat.quickReplies.storageHint') }}
                  </NText>
                  <NText depth="3" style="display: block; font-size: 12px; margin-top: 4px;">
                    {{ t('pages.chat.quickReplies.dirLabel') }}<code>{{ workspaceQuickReplyDir }}</code>
                  </NText>
                  <NButton size="tiny" text @click="handleCopyWorkspaceDir" style="margin-top: 4px;">
                    {{ t('pages.chat.quickReplies.copyDir') }}
                  </NButton>
                </div>
              </div>

              <div class="chat-side-switches">
                <NSpace justify="space-between" align="center">
                  <NText>{{ t('pages.chat.preferences.autoFollow') }}</NText>
                  <NSwitch v-model:value="autoFollowBottom" />
                </NSpace>
                <NSpace justify="space-between" align="center" style="margin-top: 8px;">
                  <NText>{{ t('pages.chat.preferences.autoPlay') }}</NText>
                  <NSwitch v-model:value="ttsSettings.autoPlay" />
                </NSpace>
                <NSpace justify="space-between" align="center" style="margin-top: 8px;">
                  <NText>{{ t('pages.chat.filters.title') }}</NText>
                  <NSelect
                    v-model:value="roleFilter"
                    size="small"
                    :options="roleFilterOptions"
                    style="width: 132px;"
                  />
                </NSpace>
              </div>

              <div class="chat-side-kv">
                <div v-if="selectedSession?.label" class="chat-kv-row">
                  <span>{{ t('pages.chat.session.label') }}</span>
                  <code class="chat-kv-label">{{ selectedSession.label }}</code>
                </div>
                <div class="chat-kv-row">
                  <span>Agent</span>
                  <code>{{ selectedSession?.agentId || sessionMeta.agent }}</code>
                </div>
                <div class="chat-kv-row">
                  <span>Channel</span>
                  <code>{{ sessionChannelDisplay }}</code>
                </div>
                <div class="chat-kv-row">
                  <span>Peer</span>
                  <code>{{ selectedSession?.peer || sessionMeta.peer || '-' }}</code>
                </div>
                <div class="chat-kv-row">
                  <span>{{ t('pages.chat.session.model') }}</span>
                  <code>{{ selectedSession?.model || '-' }}</code>
                </div>
              </div>
            </NSpace>
          </NCard>
        </NGridItem>

        <NGridItem :span="sideCollapsed ? 3 : 2" class="chat-grid-main">
          <!-- 展开按钮（侧边栏折叠时显示） -->
          <div v-if="sideCollapsed" class="chat-side-expand-btn" @click="sideCollapsed = false">
            <NIcon :component="ChevronForwardOutline" size="14" />
          </div>
          
          <div class="chat-main-column">
            <NCard embedded :bordered="false" class="chat-transcript-card">
              <NSpace justify="space-between" align="center" style="margin-bottom: 10px;">
                <NSpace align="center" :size="8">
                  <NTag size="small" type="info" :bordered="false" round>
                    {{ t('pages.chat.sessionTag', { key: normalizedSessionKey }) }}
                  </NTag>
                  <NTag size="small" :type="syncTagType" :bordered="false" round>
                    {{ syncHint }}
                  </NTag>
                </NSpace>
                <NText depth="3" style="font-size: 12px;">
                  {{ t('pages.chat.stats.breakdown', { user: stats.user, assistant: stats.assistant, system: stats.system }) }}
                </NText>
              </NSpace>

              <div class="chat-transcript-shell">
                <NSpin :show="transcriptLoading" class="chat-transcript-spin">
                  <div ref="transcriptRef" class="chat-transcript" @scroll="handleTranscriptScroll">
                    <template v-if="renderedMessages.length">
                      <div
                        v-for="entry in renderedMessages"
                        :key="entry.key"
                        class="chat-bubble"
                        :class="`is-${entry.item.role}`"
                      >
                        <NSpace justify="space-between" align="center" class="chat-bubble-meta" :size="8">
                          <NSpace align="center" :size="6">
                            <NTag size="small" :type="roleType(entry.item.role)" :bordered="false" round>
                              {{ roleLabel(entry.item.role) }}
                            </NTag>
                            <NText v-if="entry.item.name" depth="3" style="font-size: 12px;">
                              {{ entry.item.name }}
                            </NText>
                          </NSpace>
                          <NText v-if="entry.item.timestamp" depth="3" style="font-size: 12px;">
                            {{ formatDate(entry.item.timestamp) }}
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
                                  <NTag size="small" type="warning" :bordered="false" round>{{ t('pages.chat.structured.toolCall') }}</NTag>
                                  <NText strong>{{ tool.name }}</NText>
                                </NSpace>
                                <NSpace align="center" :size="8">
                                  <NText v-if="tool.timeout" depth="3" style="font-size: 12px;">
                                    {{ t('pages.chat.structured.timeout', { seconds: tool.timeout }) }}
                                  </NText>
                                  <NButton
                                    v-if="tool.argumentsJson"
                                    size="tiny"
                                    text
                                    @click="toggleToolCallExpand(`${entry.key}-tool-${toolIndex}`)"
                                  >
                                    {{ expandedToolCalls.has(`${entry.key}-tool-${toolIndex}`) ? t('pages.chat.structured.hideArgs') : t('pages.chat.structured.viewArgs') }}
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
                                <summary>{{ t('pages.chat.structured.viewPartialJson') }}</summary>
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
                                  <NTag size="small" type="success" :bordered="false" round>{{ t('pages.chat.structured.toolResult') }}</NTag>
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
                                    {{ expandedToolResults.has(`${entry.key}-result-${resultIndex}`) ? t('pages.chat.structured.hideArgs') : t('pages.chat.structured.viewArgs') }}
                                  </NButton>
                                </NSpace>
                              </NSpace>

                              <div v-if="expandedToolResults.has(`${entry.key}-result-${resultIndex}`)" class="tool-call-grid">
                                <span class="tool-call-label">{{ t('pages.chat.structured.callId') }}</span>
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
                                <span class="tool-call-label">{{ t('pages.chat.structured.content') }}</span>
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

                          <div v-if="entry.structured.validationErrors.length" class="validation-error-list">
                            <div
                              v-for="(validation, validationIndex) in entry.structured.validationErrors"
                              :key="`${entry.key}-validation-${validationIndex}`"
                              class="validation-error-card"
                            >
                                <NSpace align="center" justify="space-between">
                                  <NSpace align="center" :size="6">
                                  <NTag size="small" type="warning" :bordered="false" round>{{ t('pages.chat.structured.validationFailed') }}</NTag>
                                  <NText strong>{{ validation.toolName }}</NText>
                                </NSpace>
                                <NText depth="3" style="font-size: 12px;">
                                  {{ t('pages.chat.structured.issuesCount', { count: validation.issues.length }) }}
                                </NText>
                              </NSpace>

                              <div class="tool-call-grid">
                                <span class="tool-call-label">{{ t('pages.chat.structured.issues') }}</span>
                                <div class="validation-issues">
                                  <div v-if="validation.issues.length === 0">-</div>
                                  <div v-for="(issue, issueIndex) in validation.issues" :key="issueIndex">
                                    - {{ issue }}
                                  </div>
                                </div>
                              </div>

                              <details v-if="validation.argumentsText" class="tool-call-details">
                                <summary>{{ t('pages.chat.structured.viewArgs') }}</summary>
                                <pre>{{ validation.argumentsText }}</pre>
                              </details>
                            </div>
                          </div>

                          <div
                            v-if="entry.structured.plainTexts.length"
                            class="chat-bubble-content-wrapper"
                          >
                            <div class="chat-bubble-content structured-plain-text chat-markdown"
                              v-html="renderChatMarkdown(entry.structured.plainTexts.join('\n'), entry.item.role)"
                            ></div>
                            <div class="chat-content-copy-btn">
                              <NTooltip>
                                <template #trigger>
                                  <NButton quaternary size="tiny" @click="copyMessageContent(entry)">
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
                                {{ playingMessageId === entry.item.id ? t('pages.chat.tts.stop') : t('pages.chat.tts.play') }}
                              </NTooltip>
                            </div>
                          </div>

                          <div v-if="entry.structured.images.length" class="chat-images-container">
                            <div
                              v-for="(img, imgIndex) in entry.structured.images"
                              :key="`${entry.key}-img-${imgIndex}`"
                              class="chat-image-wrapper"
                            >
                              <img
                                v-if="img.url"
                                :src="img.url"
                                class="chat-image"
                                loading="lazy"
                                @click="openImagePreview(img.url)"
                              />
                              <span v-else class="chat-image-placeholder">{{ t('pages.chat.image.unavailable') }}</span>
                            </div>
                          </div>
                        </div>

                        <div v-else class="chat-bubble-content-wrapper">
                          <div
                            class="chat-bubble-content chat-markdown"
                            v-html="renderChatMarkdown(entry.item.content, entry.item.role)"
                          ></div>
                          <div class="chat-content-copy-btn">
                            <NTooltip>
                              <template #trigger>
                                <NButton quaternary size="tiny" @click="copyMessageContent(entry)">
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
                              {{ playingMessageId === entry.item.id ? t('pages.chat.tts.stop') : t('pages.chat.tts.play') }}
                            </NTooltip>
                          </div>
                        </div>
                      </div>
                    </template>

                    <NEmpty
                      v-else
                      :description="visibleMessageEntries.length ? t('pages.chat.messages.emptyFiltered') : t('common.noMessages')"
                      style="padding: 72px 0;"
                    />
                  </div>
                </NSpin>
              </div>
            </NCard>

            <NCard embedded :bordered="false" class="chat-compose-card">
              <NSpace vertical :size="10">
                <NInput
                  v-model:value="draft"
                  type="textarea"
                  :autosize="{ minRows: 3, maxRows: 8 }"
                  :placeholder="t('pages.chat.input.placeholder')"
                  @keydown="handleDraftKeydown"
                />

                <div v-if="slashMode" class="chat-slash-panel">
                  <div class="chat-slash-head">
                    <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.slash.title') }}</NText>
                    <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.slash.hint') }}</NText>
                  </div>
                  <div v-if="slashSuggestions.length" class="chat-slash-list">
                    <button
                      v-for="(item, index) in slashSuggestions"
                      :key="item.key"
                      class="chat-slash-item"
                      :class="{ 'is-active': index === selectedSlashCommandIndex }"
                      type="button"
                      @mouseenter="selectedSlashCommandIndex = index"
                      @mousedown.prevent
                      @click="applySlashSuggestion(item)"
                    >
                      <div v-if="item.kind === 'command' && item.preset">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">{{ item.preset.command }}</span>
                          <span v-if="item.preset.usage" class="chat-slash-usage">{{ item.preset.usage }}</span>
                          <NTag size="tiny" :bordered="false" round>{{ item.preset.category }}</NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.preset.description }}</span>
                          <span v-if="item.preset.requiresFlag" class="chat-slash-flag">
                            {{ t('pages.chat.slash.requiresFlag', { flag: item.preset.requiresFlag }) }}
                          </span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'skill' && item.skill">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">/skill {{ item.skill.name }}</span>
                          <NTag size="tiny" type="success" :bordered="false" round>
                            {{ skillSourceLabel(item.skill.source) }}
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.skill.description || t('common.noDescription') }}</span>
                          <span v-if="item.skill.version" class="chat-slash-flag">v{{ item.skill.version }}</span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'model' && item.model">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">/model {{ item.model.modelRef }}</span>
                          <NTag size="tiny" type="info" :bordered="false" round>
                            {{ item.model.providerId }}
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.model.modelId }}</span>
                          <span class="chat-slash-flag">{{ t('pages.chat.slash.fromConfig') }}</span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'new-model' && item.model">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">/new {{ item.model.modelRef }}</span>
                          <NTag size="tiny" type="info" :bordered="false" round>
                            {{ item.model.providerId }}
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.model.modelId }}</span>
                          <span class="chat-slash-flag">{{ t('pages.chat.slash.fromConfig') }}</span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'subagents-subcommand' && item.subagentsSubcommand">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">/subagents {{ item.subagentsSubcommand.subcommand }}</span>
                          <span v-if="item.subagentsSubcommand.usage" class="chat-slash-usage">{{ item.subagentsSubcommand.usage }}</span>
                          <NTag size="tiny" type="info" :bordered="false" round>
                            subagents
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.subagentsSubcommand.description }}</span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'subagents-agent' && item.agent">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">{{ item.agent.id }}</span>
                          <NTag size="tiny" type="info" :bordered="false" round>
                            {{ t('pages.chat.slash.subagents.agentTag') }}
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ item.agent.model?.primary || '-' }}</span>
                          <span class="chat-slash-flag">{{ t('pages.chat.slash.fromConfig') }}</span>
                        </div>
                      </div>
                      <div v-else-if="item.kind === 'new-default'">
                        <div class="chat-slash-line">
                          <span class="chat-slash-command">/new</span>
                          <NTag size="tiny" type="default" :bordered="false" round>
                            {{ t('pages.chat.slash.commands.new.defaultLabel') }}
                          </NTag>
                        </div>
                        <div class="chat-slash-line chat-slash-desc">
                          <span>{{ t('pages.chat.slash.commands.new.defaultDesc') }}</span>
                        </div>
                      </div>
                    </button>
                  </div>
                  <div v-else class="chat-slash-empty">
                    <template v-if="slashSkillMode">
                      {{ skillStore.loading ? t('pages.chat.slash.skills.loading') : t('pages.chat.slash.skills.noMatch') }}
                    </template>
                    <template v-else-if="slashSubagentsMode">
                      {{ configStore.loading ? t('pages.chat.slash.subagents.loading') : t('pages.chat.slash.subagents.noMatch') }}
                    </template>
                    <template v-else-if="slashModelMode || slashNewMode">
                      {{ configStore.loading ? t('pages.chat.slash.models.loading') : t('pages.chat.slash.models.noMatch') }}
                    </template>
                    <template v-else>
                      {{ t('pages.chat.slash.commands.noMatch') }}
                    </template>
                  </div>
                </div>

                <div class="chat-compose-status-line">
                  <NSpace align="center" justify="space-between" style="width: 100%;">
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
                  </NSpace>
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

                      <details v-if="currentToolProgress.argsPreview" class="chat-tool-progress__details">
                        <summary>{{ t('pages.chat.structured.viewArgs') }}</summary>
                        <pre>{{ currentToolProgress.argsPreview }}</pre>
                      </details>

                      <details v-if="currentToolProgress.partialPreview" class="chat-tool-progress__details">
                        <summary>{{ t('pages.chat.agentDetails.viewPartialResult') }}</summary>
                        <pre>{{ currentToolProgress.partialPreview }}</pre>
                      </details>

                      <details v-if="currentToolProgress.resultPreview" class="chat-tool-progress__details">
                        <summary>{{ t('pages.chat.agentDetails.viewResult') }}</summary>
                        <pre>{{ currentToolProgress.resultPreview }}</pre>
                      </details>

                      <NText
                        v-if="currentToolProgress.isError === true"
                        depth="3"
                        style="font-size: 12px; color: var(--danger-color);"
                      >
                        {{ t('pages.chat.agentDetails.toolFailed') }}
                      </NText>
                    </div>
                  </NSpace>
                </div>

                <NSpace justify="space-between" align="center">
                  <NText depth="3" style="font-size: 12px;">
                    {{ t('pages.chat.input.sendHint', { key: normalizedSessionKey }) }}
                  </NText>
                  <NSpace :size="8">
                    <NButton size="small" secondary :disabled="!draft" @click="draft = ''">
                      {{ t('pages.chat.actions.clearInput') }}
                    </NButton>
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
                    <NButton size="small" type="primary" :loading="agentBusy" :disabled="agentBusy" @click="handleSend">
                      <template #icon><NIcon :component="SendOutline" /></template>
                      {{ t('pages.chat.actions.send') }}
                    </NButton>
                  </NSpace>
                </NSpace>
              </NSpace>
            </NCard>
          </div>
        </NGridItem>
      </NGrid>

      <NAlert v-if="chatStore.lastError" type="error" :show-icon="true" style="margin-top: 12px; border-radius: var(--radius);">
        {{ chatStore.lastError }}
      </NAlert>
    </NCard>

    <NModal
      v-model:show="showQuickReplyModal"
      preset="card"
      :title="quickReplyModalMode === 'edit'
        ? t('pages.chat.quickReplies.modal.editTitle')
        : t('pages.chat.quickReplies.modal.createTitle')"
      style="width: 640px; max-width: calc(100vw - 28px);"
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
  </div>
</template>

<style scoped>
.chat-page {
  min-height: 0;
}

/* 桌面端：让聊天区尽量占满可用高度，提升 transcript 可视面积 */
@media (min-width: 1024px) {
  .chat-page {
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

  /* 折叠按钮样式 */
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

  /* 展开按钮样式（主内容区域左侧） */
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

  /* 侧边栏折叠状态 */
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

.chat-token-chip--loading.n-tag {
  border: 1px dashed var(--border-color);
}

.chat-token-chip__label {
  color: var(--text-secondary);
  margin-right: 4px;
}

.chat-token-chip__value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

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

.chat-agent-details {
  padding: 10px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius);
  background: var(--bg-secondary);
}

.chat-agent-steps {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 160px;
  overflow: auto;
  padding-right: 2px;
}

.chat-agent-step {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.chat-agent-step__time {
  min-width: 74px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-variant-numeric: tabular-nums;
  opacity: 0.9;
}

.chat-agent-step__label {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.chat-quick-footnote code {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--bg-secondary);
  word-break: break-all;
}

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

.chat-compose-card {
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
}

.chat-slash-panel {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.chat-slash-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px dashed var(--border-color);
}

.chat-slash-list {
  max-height: 240px;
  overflow-y: auto;
}

.chat-slash-item {
  width: 100%;
  text-align: left;
  border: 0;
  border-bottom: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  padding: 8px 10px;
  cursor: pointer;
}

.chat-slash-item:last-child {
  border-bottom: 0;
}

.chat-slash-item:hover,
.chat-slash-item.is-active {
  background: rgba(24, 144, 255, 0.1);
}

.chat-slash-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.chat-slash-command {
  font-family: 'JetBrains Mono', 'SF Mono', Monaco, monospace;
  font-size: 13px;
  line-height: 1.45;
}

.chat-slash-usage {
  color: var(--text-secondary);
  font-size: 12px;
}

.chat-slash-desc {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  justify-content: space-between;
}

.chat-slash-flag {
  color: var(--warning-color);
  white-space: nowrap;
}

.chat-slash-empty {
  padding: 12px 10px;
  color: var(--text-secondary);
  font-size: 12px;
}

.chat-bubble {
  position: relative;
  width: fit-content;
  max-width: min(840px, 88%);
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.chat-bubble-content-wrapper {
  position: relative;
}

.chat-content-copy-btn {
  position: absolute;
  top: 0;
  right: 0;
  opacity: 0;
  transition: opacity 0.2s ease;
  z-index: 10;
}

.chat-bubble-content-wrapper:hover .chat-content-copy-btn {
  opacity: 1;
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

.chat-bubble-content {
  white-space: pre-wrap;
  line-height: 1.65;
  word-break: break-word;
}

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

/* —— 标题 —— */
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

/* —— 段落 —— */
.chat-markdown :deep(p) {
  margin: 4px 0;
  line-height: 1.72;
}

/* —— 表格（GFM） —— */
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

/* —— 无序列表 —— */
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

/* 嵌套列表 */
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

/* 三级列表 */
.chat-markdown :deep(ul ul ul > li::before) {
  width: 3px;
  height: 3px;
  border: none;
  background: var(--md-bullet-nested-color);
  border-radius: 0;
}

/* —— 有序列表 —— */
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

/* —— 链接 —— */
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

/* —— 引用块 —— */
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

/* —— 代码 —— */
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

/* —— 代码块容器（带行号） —— */
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

/* —— 分割线 —— */
.chat-markdown :deep(hr) {
  border: 0;
  height: 1px;
  background: var(--border-color);
  margin: 10px 0;
}

/* —— 加粗/强调 —— */
.chat-markdown :deep(strong) {
  font-weight: 600;
}

.chat-markdown :deep(em) {
  font-style: italic;
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
}

.tool-call-args {
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
}

.validation-error-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.validation-error-card {
  border: 1px solid rgba(250, 173, 20, 0.45);
  border-radius: 8px;
  background: rgba(250, 173, 20, 0.08);
  padding: 10px;
}

.validation-issues {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
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

.tool-call-grid code {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  line-height: 1.5;
  word-break: break-all;
}

.tool-call-value-wrapper {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.tool-value-copy-btn {
  opacity: 0;
  transition: opacity 0.2s ease;
  flex-shrink: 0;
}

.tool-call-value-wrapper:hover .tool-value-copy-btn {
  opacity: 1;
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

body.wide-mode .chat-grid {
  display: grid !important;
  grid-template-columns: 460px 1fr !important;
  grid-template-rows: 1fr !important;
}

body.wide-mode .chat-grid--collapsed {
  grid-template-columns: 1fr !important;
}

body.wide-mode .chat-grid > div {
  grid-row: 1 !important;
}

body.wide-mode .chat-grid-side {
  max-width: 460px;
  flex-shrink: 0;
}

body.wide-mode .chat-grid-main {
  flex: 1;
  min-width: 0;
}

body.wide-mode .chat-bubble {
  max-width: min(1600px, 92%);
}

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

  .chat-slash-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .chat-bubble {
    max-width: 96%;
  }

  .tool-call-grid {
    grid-template-columns: 1fr;
  }
}

.chat-images-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.chat-image-wrapper {
  max-width: 300px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
}

.chat-image {
  display: block;
  max-width: 100%;
  max-height: 300px;
  object-fit: contain;
  cursor: pointer;
  transition: transform 0.2s ease;
}

.chat-image:hover {
  transform: scale(1.02);
}

.chat-image-placeholder {
  display: block;
  padding: 16px;
  color: var(--text-secondary);
  font-size: 12px;
  text-align: center;
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
