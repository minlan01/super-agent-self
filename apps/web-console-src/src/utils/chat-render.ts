/**
 * Chat message rendering helpers — pure functions for converting message content to HTML.
 * No Vue reactivity, no component state, no side effects.
 */
import type { ChatMessage } from '@/api/types'
import { looksLikeMarkdown } from '@/utils/chat-parser'
import { renderSimpleMarkdown, escapeHtml } from '@/utils/markdown'

export function renderPlainText(content: string): string {
  const escaped = escapeHtml(content || '')
  return `<p>${escaped.replace(/\n/g, '<br />')}</p>`
}

export function renderChatMarkdown(content: string, role?: ChatMessage['role']): string {
  const text = content || ''
  if (!looksLikeMarkdown(text)) {
    return renderPlainText(text)
  }
  const autoNestList = role === 'assistant' || role === 'tool' || role === 'system'
  return renderSimpleMarkdown(text, { autoNestList })
}
