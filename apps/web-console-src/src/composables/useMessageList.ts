import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '@/stores/chat'
import type { SelectOption } from 'naive-ui'
import type { RenderMessage } from '@/api/types'
import {
  isThinkingOnlyStructuredMessage,
  parseRawContent,
  parseStructuredMessage,
  parseToolResultMessage,
} from '@/utils/chat-parser'

export function useMessageList() {
  const { t } = useI18n()
  const chatStore = useChatStore()

  const roleFilter = ref<'all' | 'user' | 'assistant' | 'system'>('all')

  const roleFilterOptions = computed<SelectOption[]>(() => [
    { label: t('pages.chat.filters.roles.all'), value: 'all' },
    { label: t('pages.chat.filters.roles.user'), value: 'user' },
    { label: t('pages.chat.filters.roles.assistant'), value: 'assistant' },
    { label: t('pages.chat.filters.roles.system'), value: 'system' },
  ])

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
        if (structured && (structured.toolCalls.length > 0 || structured.thinkings.length > 0 || structured.toolResults.length > 0 || structured.plainTexts.length > 0 || structured.images.length > 0)) {
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

  const renderedMessages = computed<RenderMessage[]>(() => {
    const role = roleFilter.value
    if (role === 'all') return visibleMessageEntries.value
    return visibleMessageEntries.value.filter((entry) => entry.item.role === role)
  })

  return {
    roleFilter,
    roleFilterOptions,
    messageList,
    visibleMessageEntries,
    renderedMessages,
  }
}
