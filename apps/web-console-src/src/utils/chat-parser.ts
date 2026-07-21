/**
 * Chat message parsing engine — pure functions extracted from ChatPage/AgentChatPanel.
 * No Vue reactivity, no component state, no side effects.
 */
import type {
  ChatMessage,
  ChatMessageContent,
  ImageItemView,
  RenderMessage,
  StructuredMessageView,
  ThinkingItemView,
  ToolCallItemView,
  ToolResultItemView,
  ToolValidationErrorItemView,
} from '@/api/types'

// ── Type guard helpers ───────────────────────────────────────────────────────

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

export function asString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

export function asText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value
      .map((item) => asText(item))
      .filter((item) => !!item.trim())
      .join('\n')
  }
  const row = asRecord(value)
  if (row) {
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
  return ''
}

export function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

// ── Math / misc helpers ──────────────────────────────────────────────────────

export function normalizeTokenValue(value: unknown): number {
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

// ── JSON / string parsers ────────────────────────────────────────────────────

export function stripCodeFence(text: string): string {
  const value = text.trim()
  if (!value.startsWith('```') || !value.endsWith('```')) return value
  const lines = value.split('\n')
  if (lines.length < 2) return value
  return lines.slice(1, -1).join('\n').trim()
}

export function decodeEscapedJsonText(text: string): string | null {
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

export function looksLikeJsonString(value: string): boolean {
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

export function unwrapJsonValue(value: unknown, depth = 0): unknown {
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

export function parseSingleJsonValue(text: string): unknown | null {
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

export function splitLeadingJsonValue(line: string): { parsed: unknown; rest: string } | null {
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
      if (ch === '\\\\') {
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

export function parseJsonItems(content: string): { items: unknown[]; plainLines: string[] } | null {
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

export function parseThinkingSignature(value: unknown): {
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

export function parseToolValidationError(content: string): ToolValidationErrorItemView | null {
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

// ── Media helpers ────────────────────────────────────────────────────────────

export function normalizeMediaPath(path: string): string {
  if (path.startsWith('MEDIA:')) {
    path = path.slice(6)
  }

  if (path.startsWith('file://')) {
    const mediaIndex = path.indexOf('.openclaw/media/')
    if (mediaIndex !== -1) {
      return path.slice(mediaIndex + '.openclaw/media/'.length)
    }
    const lastSlash = path.lastIndexOf('/')
    if (lastSlash !== -1) {
      return `browser/${path.slice(lastSlash + 1)}`
    }
  }

  return path
}

export function buildImageUrl(part: ChatMessageContent): string | undefined {
  if (part.data) {
    const mimeType = part.mimeType || 'image/png'
    return `data:${mimeType};base64,${part.data}`
  }
  if (part.mediaPath) {
    let mediaPath = part.mediaPath
    if (mediaPath.startsWith('MEDIA:')) {
      mediaPath = mediaPath.slice(6)
    }
    if (mediaPath.startsWith('file://')) {
      const mediaIndex = mediaPath.indexOf('.openclaw/media/')
      if (mediaIndex !== -1) {
        mediaPath = mediaPath.slice(mediaIndex + '.openclaw/media/'.length)
      } else {
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

export function extractImageFromText(text: string): { images: ImageItemView[]; cleanedText: string } {
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

// ── Structured message parsers ───────────────────────────────────────────────

export function isThinkingOnlyStructuredMessage(structured: StructuredMessageView | null): boolean {
  if (!structured) return false
  if (structured.thinkings.length === 0) return false
  return (
    structured.toolCalls.length === 0 &&
    structured.toolResults.length === 0 &&
    structured.validationErrors.length === 0 &&
    structured.plainTexts.length === 0
  )
}

export function parseToolResultMessage(item: ChatMessage): StructuredMessageView | null {
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

export function parseRawContent(rawContent: ChatMessageContent[]): StructuredMessageView | null {
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
        const imagePath = trimmedText.includes('/') ? trimmedText : `browser/${trimmedText}`
        const imageUrl = `/api/media?path=${encodeURIComponent(imagePath)}`
        images.push({
          mimeType: `image/${trimmedText.split('.').pop()?.toLowerCase() || 'png'}`,
          url: imageUrl,
        })
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
      const rawContentValue = part.content
      if (rawContentValue && typeof rawContentValue === 'object' && !Array.isArray(rawContentValue)) {
        try {
          contentText = JSON.stringify(rawContentValue, null, 2)
        } catch {
          contentText = String(rawContentValue)
        }
      } else if (typeof rawContentValue === 'string') {
        contentText = rawContentValue
      } else {
        contentText = String(rawContentValue || '')
      }

      const { images: extractedImages, cleanedText } = extractImageFromText(contentText)
      images.push(...extractedImages)

      toolResults.push({
        id: part.id,
        name: part.name || 'unknown',
        status: part.isError ? 'error' : undefined,
        content: cleanedText,
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

export function parseStructuredMessage(content: string): StructuredMessageView | null {
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
  const images: ImageItemView[] = []
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
      const rawContentValue = row.content ?? row.output ?? row.result ?? row.message ?? row.response

      if (rawContentValue && typeof rawContentValue === 'object' && !Array.isArray(rawContentValue)) {
        try {
          contentText = JSON.stringify(rawContentValue, null, 2)
        } catch {
          contentText = asText(rawContentValue)
        }
      } else {
        contentText = asText(rawContentValue)
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

  const imagePlainTexts: string[] = []
  for (const line of parsed.plainLines) {
    const { images: extractedImages, cleanedText } = extractImageFromText(line)
    images.push(...extractedImages)

    const trimmedLine = cleanedText.trim()
    if (trimmedLine.match(/\.(png|jpg|jpeg|gif|webp|bmp)$/i)) {
      const imageUrl = `/api/media?path=${encodeURIComponent(trimmedLine)}`
      images.push({
        mimeType: `image/${trimmedLine.split('.').pop()?.toLowerCase() || 'png'}`,
        url: imageUrl,
      })
    } else if (trimmedLine) {
      imagePlainTexts.push(cleanedText)
    }
  }

  if (!recognized && images.length === 0) return null
  return {
    toolCalls,
    thinkings,
    toolResults,
    validationErrors: [],
    plainTexts: imagePlainTexts,
    images,
  }
}

// ── Content detection ────────────────────────────────────────────────────────

export function looksLikeMarkdown(value: string): boolean {
  const text = value.replace(/\r\n/g, '\n')
  if (!text.trim()) return false
  if (/```[\s\S]*```/.test(text)) return true
  if (/`[^`\n]+`/.test(text)) return true
  if (/\[[^\]]+]\((https?:\/\/[^)\s]+)\)/.test(text)) return true
  if (/\*\*[^*\n]+\*\*/.test(text)) return true
  if (/(^|[\s(（\[{【'"“‘])\*[^*\n]+\*(?=$|[\s)\]）}】'".,!?，。！？：:、”’])/u.test(text)) return true
  if (/^\s{0,3}#{1,6}\s+\S+/m.test(text)) return true
  if (/^\s{0,3}>\s+\S+/m.test(text)) return true
  if (/^\s{0,3}[-*+]\s+\S+/m.test(text)) return true
  if (/^\s{0,3}\d{1,9}[.)]\s+\S+/m.test(text)) return true
  if (/\|\s*[-:]{3,}\s*\|/.test(text)) return true
  if (/^\s*\|?.+\|.+\n\s*\|?\s*[-:]{3,}\s*\|/m.test(text)) return true
  if (/^\s{0,3}(?:[-*_]\s*){3,}$/m.test(text)) return true
  if (/^\s{0,3}[-*_]{3,}\s*$/m.test(text)) return true
  return false
}

export function looksLikeStreamingPayload(payload: unknown): boolean {
  const queue: Array<{ value: unknown; depth: number }> = [{ value: payload, depth: 0 }]
  const visited = new Set<unknown>()
  const maxDepth = 4

  while (queue.length > 0) {
    const current = queue.shift()
    if (!current) continue
    if (current.depth > maxDepth) continue

    const value = current.value
    if (!value || typeof value !== 'object') continue
    if (visited.has(value)) continue
    visited.add(value)

    if (!Array.isArray(value)) {
      const row = value as Record<string, unknown>
      if (
        'delta' in row ||
        'chunk' in row ||
        'partial' in row ||
        'stream' in row ||
        'streaming' in row
      ) {
        return true
      }
      const kind = typeof row.type === 'string' ? row.type.toLowerCase() : ''
      if (kind.includes('delta') || kind.includes('chunk') || kind.includes('stream')) {
        return true
      }

      for (const child of Object.values(row)) {
        if (child && typeof child === 'object') {
          queue.push({ value: child, depth: current.depth + 1 })
        }
      }
      continue
    }

    for (const child of value) {
      if (child && typeof child === 'object') {
        queue.push({ value: child, depth: current.depth + 1 })
      }
    }
  }

  return false
}

// ── Message content helpers ──────────────────────────────────────────────────

export function getMessageContent(entry: RenderMessage): string {
  if (entry.structured) {
    return entry.structured.plainTexts.join('\n')
  }
  return entry.item.content || ''
}

// ── Duration / time formatting ───────────────────────────────────────────────

export function formatDurationMs(ms: number): string {
  const safe = Math.max(0, Math.floor(ms))
  const totalSec = Math.floor(safe / 1000)
  const min = Math.floor(totalSec / 60)
  const sec = totalSec % 60
  if (min <= 0) return `${sec}s`
  return `${min}m${String(sec).padStart(2, '0')}s`
}

// ── Role helpers ─────────────────────────────────────────────────────────────

export function roleType(role: string): 'default' | 'success' | 'info' | 'warning' {
  if (role === 'user') return 'info'
  if (role === 'assistant') return 'success'
  if (role === 'tool') return 'warning'
  return 'default'
}
