/**
 * Chat module shared type definitions.
 * Extracted from ChatPage.vue and AgentChatPanel.vue to avoid duplication.
 */
import type { AgentInstance, ChatMessage, Skill } from '@/api/types'

// ── Token Usage ──────────────────────────────────────────────────────────────

export interface SessionTokenUsage {
  input: number
  output: number
  cacheRead: number
  cacheWrite: number
  total: number
}

// ── Structured Message View ──────────────────────────────────────────────────

export interface ToolCallItemView {
  id?: string
  name: string
  command?: string
  workdir?: string
  timeout?: number
  partialJson?: string
  argumentsJson?: string
}

export interface ThinkingItemView {
  type?: string
  text: string
  signatureId?: string
  summaryText?: string
  hasEncryptedSignature: boolean
}

export interface ToolResultItemView {
  id?: string
  name?: string
  status?: string
  content: string
}

export interface ToolValidationErrorItemView {
  toolName: string
  issues: string[]
  argumentsText?: string
}

export interface ImageItemView {
  mimeType?: string
  bytes?: number
  data?: string
  mediaPath?: string
  url?: string
}

export interface StructuredMessageView {
  toolCalls: ToolCallItemView[]
  thinkings: ThinkingItemView[]
  toolResults: ToolResultItemView[]
  validationErrors: ToolValidationErrorItemView[]
  plainTexts: string[]
  images: ImageItemView[]
}

export interface RenderMessage {
  key: string
  item: ChatMessage
  structured: StructuredMessageView | null
}

// ── Slash Commands ───────────────────────────────────────────────────────────

export interface SlashCommandPreset {
  command: string
  usage?: string
  description: string
  category: string
  aliases?: string[]
  expectArgs?: boolean
  requiresFlag?: string
}

export type SubagentsSubcommand = 'list' | 'kill' | 'log' | 'info' | 'send' | 'steer' | 'spawn'

export interface SubagentsSubcommandPreset {
  subcommand: SubagentsSubcommand
  usage?: string
  description: string
}

export interface ConfiguredModelOption {
  modelRef: string
  providerId: string
  modelId: string
}

export interface SlashSuggestionItem {
  kind: 'command' | 'skill' | 'model' | 'new-model' | 'new-default' | 'subagents-subcommand' | 'subagents-agent'
  key: string
  preset?: SlashCommandPreset
  subagentsSubcommand?: SubagentsSubcommandPreset
  agent?: AgentInstance
  skill?: Skill
  model?: ConfiguredModelOption
}
