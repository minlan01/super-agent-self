import { computed, type Ref } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'

const SESSION_KEY_STORAGE_KEY = 'openclaw_chat_selected_session_v1'

export function useSessionManagement(sessionKeyInput: Ref<string>) {
  const chatStore = useChatStore()
  const sessionStore = useSessionStore()

  function ensureSessionKey(): string {
    const normalized = sessionKeyInput.value.trim() || 'main'
    sessionKeyInput.value = normalized
    return normalized
  }

  function readStoredSessionKey(): string {
    try {
      return localStorage.getItem(SESSION_KEY_STORAGE_KEY)?.trim() || ''
    } catch (error) {
      console.warn('[useSessionManagement] 读取上次会话失败:', error)
      return ''
    }
  }

  function writeStoredSessionKey(key: string) {
    const normalized = key.trim()
    if (!normalized) return
    try {
      localStorage.setItem(SESSION_KEY_STORAGE_KEY, normalized)
    } catch (error) {
      console.warn('[useSessionManagement] 保存上次会话失败:', error)
    }
  }

  function normalizeSessionSelectValue(value: string | number | null | undefined): string {
    if (typeof value === 'string') return value.trim()
    if (typeof value === 'number') return String(value).trim()
    return ''
  }

  const refreshingChatData = computed(() => sessionStore.loading || chatStore.loading)

  return {
    ensureSessionKey,
    readStoredSessionKey,
    writeStoredSessionKey,
    normalizeSessionSelectValue,
    refreshingChatData,
  }
}
