<script setup lang="ts">
import {
  NButton,
  NIcon,
  NSpace,
  NTag,
  NText,
  NTooltip,
} from 'naive-ui'
import { CopyOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { formatDate } from '@/utils/format'
import type { ChatMessage } from '@/api/types'
import { looksLikeMarkdown, roleType } from '@/utils/chat-parser'
import { renderPlainText, renderChatMarkdown } from '@/utils/chat-render'

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

export interface RenderMessage {
  key: string
  item: ChatMessage
  structured: StructuredMessageView | null
}

const props = defineProps<{
  entry: RenderMessage
  expandedToolCalls: Set<string>
  expandedToolResults: Set<string>
}>()

const emit = defineEmits<{
  (e: 'toggle-tool-call', key: string): void
  (e: 'toggle-tool-result', key: string): void
  (e: 'copy-message', entry: RenderMessage): void
  (e: 'copy-text', text: string): void
  (e: 'preview-image', url: string): void
}>()

const { t } = useI18n()

function roleLabel(role: string): string {
  if (role === 'user') return t('pages.chat.roles.user')
  if (role === 'assistant') return t('pages.chat.roles.assistant')
  if (role === 'tool') return t('pages.chat.roles.tool')
  if (role === 'system') return t('pages.chat.roles.system')
  return role
}
</script>

<template>
  <div
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
                @click="emit('toggle-tool-call', `${entry.key}-tool-${toolIndex}`)"
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
                @click="emit('toggle-tool-result', `${entry.key}-result-${resultIndex}`)"
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
                  <NButton quaternary size="tiny" class="tool-value-copy-btn" @click="emit('copy-text', result.id || '-')">
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
                  <NButton quaternary size="tiny" class="tool-value-copy-btn" @click="emit('copy-text', result.content)">
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

      <div v-if="entry.structured.plainTexts.length" class="chat-bubble-content-wrapper">
        <div
          class="chat-bubble-content structured-plain-text chat-markdown"
          v-html="renderChatMarkdown(entry.structured.plainTexts.join('\n'), entry.item.role)"
        ></div>
        <div class="chat-content-copy-btn">
          <NTooltip>
            <template #trigger>
              <NButton quaternary size="tiny" @click="emit('copy-message', entry)">
                <template #icon>
                  <NIcon :component="CopyOutline" />
                </template>
              </NButton>
            </template>
            {{ t('common.copy') }}
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
            @click="emit('preview-image', img.url)"
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
            <NButton quaternary size="tiny" @click="emit('copy-message', entry)">
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
</template>

<style scoped>
.chat-bubble {
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
}

.chat-bubble.is-user {
  background: rgba(24, 160, 88, 0.08);
}

.chat-bubble.is-assistant {
  background: rgba(32, 128, 240, 0.06);
}

.chat-bubble.is-tool {
  background: rgba(245, 158, 11, 0.06);
}

.chat-bubble-meta {
  margin-bottom: 8px;
}

.chat-bubble-content-wrapper {
  position: relative;
}

.chat-bubble-content {
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.chat-bubble-content.structured-plain-text {
  margin-top: 8px;
}

.chat-content-copy-btn {
  position: absolute;
  top: 0;
  right: 0;
  opacity: 0;
  transition: opacity 0.2s;
}

.chat-bubble-content-wrapper:hover .chat-content-copy-btn {
  opacity: 1;
}

.structured-message-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-call-list,
.tool-result-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tool-call-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}

.tool-call-args {
  margin-top: 8px;
}

.tool-call-details {
  margin-top: 8px;
  font-size: 12px;
}

.tool-call-details summary {
  cursor: pointer;
  color: var(--text-secondary);
}

.tool-call-details pre {
  font-size: 11px;
  margin: 8px 0 0;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  overflow-x: auto;
  max-height: 200px;
}

.tool-call-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 12px;
  margin-top: 8px;
  font-size: 12px;
}

.tool-call-label {
  color: var(--text-secondary);
}

.tool-call-value-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}

.tool-call-value-wrapper code {
  font-size: 11px;
  word-break: break-all;
}

.tool-value-copy-btn {
  flex-shrink: 0;
}

.tool-result-content-wrapper {
  grid-column: 1 / -1;
}

.tool-result-content {
  font-size: 11px;
  margin: 0;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  overflow-x: auto;
  max-height: 300px;
  white-space: pre-wrap;
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

.chat-markdown :deep(p) {
  margin: 4px 0;
  line-height: 1.72;
}

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

.chat-markdown :deep(ul ul ul > li::before) {
  width: 3px;
  height: 3px;
  border: none;
  background: var(--md-bullet-nested-color);
  border-radius: 0;
}

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

.chat-markdown :deep(hr) {
  border: 0;
  height: 1px;
  background: var(--border-color);
  margin: 10px 0;
}

.chat-markdown :deep(strong) {
  font-weight: 600;
}

.chat-markdown :deep(em) {
  font-style: italic;
}

.structured-plain-text {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px dashed var(--border-color);
  background: var(--bg-primary);
}

.tool-call-card {
  border: 1px solid rgba(250, 173, 20, 0.35);
  border-radius: 8px;
  background: rgba(250, 173, 20, 0.08);
  padding: 10px;
}

.tool-result-card {
  border: 1px solid rgba(24, 160, 88, 0.35);
  border-radius: 8px;
  background: rgba(24, 160, 88, 0.08);
  padding: 10px;
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

.tool-call-meta__code {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--bg-primary);
  line-height: 1.5;
  word-break: break-all;
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
</style>
