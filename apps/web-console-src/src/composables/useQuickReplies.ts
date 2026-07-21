import { computed, reactive, ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MessageApi } from 'naive-ui'
import { asNumber, asString } from '@/utils/chat-parser'

export interface QuickReplyItem {
  id: string
  title: string
  content: string
  updatedAt: number
}

export interface QuickRepliesOptions {
  /** localStorage key, defaults to 'openclaw_chat_quick_replies_v1' */
  storageKey?: string
  /** i18n prefix for messages, defaults to 'pages.chat.quickReplies' */
  i18nPrefix?: string
}

const DEFAULT_STORAGE_KEY = 'openclaw_chat_quick_replies_v1'
const DEFAULT_I18N_PREFIX = 'pages.chat.quickReplies'

export function useQuickReplies(draft: Ref<string>, message: MessageApi, options?: QuickRepliesOptions) {
  const { t } = useI18n()
  const storageKey = options?.storageKey ?? DEFAULT_STORAGE_KEY
  const i18nPrefix = options?.i18nPrefix ?? DEFAULT_I18N_PREFIX

  const quickReplySearch = ref('')
  const showQuickReplyModal = ref(false)
  const quickReplyModalMode = ref<'create' | 'edit'>('create')
  const editingQuickReplyId = ref('')
  const quickReplyForm = reactive({
    title: '',
    content: '',
  })
  const quickReplies = ref<QuickReplyItem[]>([])

  const filteredQuickReplies = computed(() => {
    const query = quickReplySearch.value.trim().toLowerCase()
    const list = [...quickReplies.value].sort((a, b) => b.updatedAt - a.updatedAt)
    if (!query) return list
    return list.filter((item) =>
      [item.title, item.content].some((field) => field.toLowerCase().includes(query))
    )
  })

  function loadQuickReplies() {
    try {
      const raw = localStorage.getItem(storageKey)
      if (!raw) {
        quickReplies.value = []
        return
      }
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) {
        quickReplies.value = []
        return
      }
      quickReplies.value = parsed
        .map((item) => {
          if (!item || typeof item !== 'object' || Array.isArray(item)) return null
          const row = item as Record<string, unknown>
          const title = asString(row.title).trim()
          const content = asString(row.content).trim()
          if (!title || !content) return null
          const id = asString(row.id).trim() || `quick-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
          const updatedAt = asNumber(row.updatedAt) || Date.now()
          return { id, title, content, updatedAt }
        })
        .filter((item): item is QuickReplyItem => !!item)
    } catch {
      quickReplies.value = []
    }
  }

  function persistQuickReplies() {
    localStorage.setItem(storageKey, JSON.stringify(quickReplies.value))
  }

  function resetQuickReplyForm() {
    quickReplyForm.title = ''
    quickReplyForm.content = ''
  }

  function openCreateQuickReply() {
    quickReplyModalMode.value = 'create'
    editingQuickReplyId.value = ''
    resetQuickReplyForm()
    showQuickReplyModal.value = true
  }

  function openEditQuickReply(item: QuickReplyItem) {
    quickReplyModalMode.value = 'edit'
    editingQuickReplyId.value = item.id
    quickReplyForm.title = item.title
    quickReplyForm.content = item.content
    showQuickReplyModal.value = true
  }

  function handleDeleteQuickReply(id: string) {
    quickReplies.value = quickReplies.value.filter((item) => item.id !== id)
    persistQuickReplies()
    message.success(t(`${i18nPrefix}.messages.deleted`))
  }

  function handleInsertQuickReply(item: QuickReplyItem) {
    const text = item.content.trim()
    if (!text) return
    draft.value = draft.value.trim() ? `${draft.value}\n${text}` : text
    message.success(t(`${i18nPrefix}.messages.inserted`, { title: item.title }))
  }

  async function handleSendQuickReply(item: QuickReplyItem, onSend: () => Promise<void>) {
    draft.value = item.content
    await onSend()
  }

  function handleSaveQuickReply() {
    const title = quickReplyForm.title.trim()
    const content = quickReplyForm.content.trim()
    if (!title) {
      message.warning(t(`${i18nPrefix}.messages.titleRequired`))
      return
    }
    if (!content) {
      message.warning(t(`${i18nPrefix}.messages.contentRequired`))
      return
    }

    if (quickReplyModalMode.value === 'edit' && editingQuickReplyId.value) {
      quickReplies.value = quickReplies.value.map((item) =>
        item.id === editingQuickReplyId.value
          ? { ...item, title, content, updatedAt: Date.now() }
          : item
      )
      message.success(t(`${i18nPrefix}.messages.updated`))
    } else {
      quickReplies.value = [
        {
          id: `quick-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          title,
          content,
          updatedAt: Date.now(),
        },
        ...quickReplies.value,
      ]
      message.success(t(`${i18nPrefix}.messages.created`))
    }

    persistQuickReplies()
    showQuickReplyModal.value = false
  }

  return {
    quickReplySearch,
    showQuickReplyModal,
    quickReplyModalMode,
    editingQuickReplyId,
    quickReplyForm,
    quickReplies,
    filteredQuickReplies,
    loadQuickReplies,
    persistQuickReplies,
    resetQuickReplyForm,
    openCreateQuickReply,
    openEditQuickReply,
    handleDeleteQuickReply,
    handleInsertQuickReply,
    handleSendQuickReply,
    handleSaveQuickReply,
  }
}
