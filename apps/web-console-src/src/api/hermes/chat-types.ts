// ============================================================
// Hermes Chat 页面专用类型定义
// 从 HermesChatPage.vue 提取
// ============================================================

import type { HermesMessage } from './types'

export interface QuickReply {
  id: string
  title: string
  content: string
  updatedAt: number
}

export interface CommandItem {
  key: string
  label: string
  description: string
  category: string
  argsHint: string
  hasArgs: boolean
  action: (args?: string) => void
}

export interface ToolCallItemView {
  id?: string
  name: string
  argumentsJson?: string
  command?: string
  workdir?: string
  partialJson?: string
  timeout?: number
}

export interface ThinkingItemView {
  text: string
  hasEncryptedSignature: boolean
}

export interface ToolResultItemView {
  id?: string
  name?: string
  status?: string
  content: string
}

export interface StructuredMessageView {
  toolCalls: ToolCallItemView[]
  thinkings: ThinkingItemView[]
  toolResults: ToolResultItemView[]
  plainTexts: string[]
}

export interface RenderMessage {
  key: string
  item: HermesMessage
  structured: StructuredMessageView | null
}

export interface ParsedToolMessage {
  toolName?: string
  output?: string
  isError?: boolean
  metadata?: Record<string, unknown>
}
