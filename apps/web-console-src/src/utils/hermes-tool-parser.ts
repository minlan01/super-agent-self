// ============================================================
// Hermes Chat 工具消息解析引擎
// 从 HermesChatPage.vue 提取 — 纯函数，无 Vue 依赖
// ============================================================

import type {
  ParsedToolMessage,
  StructuredMessageView,
  ToolCallItemView,
  ThinkingItemView,
  ToolResultItemView,
} from '@/api/hermes/chat-types'

// ── 工具名称映射表 ───────────────────────────────────────────────────────────

export const HERMES_TOOL_NAMES: Record<string, string> = {
  // Web tools
  web_search: 'Web 搜索',
  web_extract: 'Web 提取',

  // Terminal & File tools
  terminal: '终端',
  process: '进程管理',
  read_file: '读取文件',
  write_file: '写入文件',
  patch: '文件编辑',
  search_files: '文件搜索',

  // Browser tools
  browser_navigate: '浏览器导航',
  browser_snapshot: '页面快照',
  browser_vision: '页面截图',
  browser_click: '点击元素',
  browser_type: '输入文本',
  browser_press: '按键',
  browser_scroll: '滚动页面',
  browser_back: '后退',
  browser_get_images: '获取图片',
  browser_console: '控制台',

  // Media tools
  vision_analyze: '图像分析',
  image_generate: '图像生成',
  text_to_speech: '语音合成',

  // Agent orchestration
  todo: '任务管理',
  clarify: '澄清问题',
  execute_code: '代码执行',
  delegate_task: '任务委托',

  // Memory & recall
  memory: '记忆管理',
  session_search: '会话搜索',

  // Automation & delivery
  cronjob: '定时任务',
  send_message: '发送消息',

  // Skills
  skill_manage: '技能管理',
}

// ── 工具名称格式化 ───────────────────────────────────────────────────────────

export function getToolDisplayName(toolName: string): string {
  if (!toolName) return '工具'
  // 直接匹配
  if (HERMES_TOOL_NAMES[toolName]) {
    return HERMES_TOOL_NAMES[toolName]
  }
  // 检查是否是 MCP 工具 (格式: server_toolname)
  if (toolName.includes('_')) {
    const parts = toolName.split('_')
    // 尝试匹配后半部分
    const suffix = parts.slice(1).join('_')
    if (HERMES_TOOL_NAMES[suffix]) {
      return HERMES_TOOL_NAMES[suffix]
    }
    // 返回格式化的名称
    return toolName.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  }
  return toolName
}

// ── 基础类型转换 ─────────────────────────────────────────────────────────────

function asString(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return String(value)
}

function asNumber(value: unknown): number | undefined {
  if (value === null || value === undefined) return undefined
  if (typeof value === 'number') return value
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

function unwrapJsonValue(value: unknown): unknown {
  if (typeof value === 'string') {
    try {
      return JSON.parse(value)
    } catch {
      return value
    }
  }
  return value
}

// ── 工具消息解析 ─────────────────────────────────────────────────────────────

export function parseToolMessage(content: string): ParsedToolMessage | null {
  try {
    const parsed = JSON.parse(content)

    if (parsed.error || parsed.isError) {
      return {
        isError: true,
        output: parsed.error || parsed.message || parsed.errorMessage || content,
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
      }
    }

    if (parsed.output !== undefined) {
      return {
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
        output: typeof parsed.output === 'string' ? parsed.output : JSON.stringify(parsed.output, null, 2),
        metadata: parsed.metadata || parsed.meta,
      }
    }

    if (parsed.result !== undefined) {
      return {
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
        output: typeof parsed.result === 'string' ? parsed.result : JSON.stringify(parsed.result, null, 2),
      }
    }

    if (parsed.content !== undefined) {
      return {
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
        output: typeof parsed.content === 'string' ? parsed.content : JSON.stringify(parsed.content, null, 2),
      }
    }

    if (parsed.files || parsed.total_count !== undefined) {
      const parts: string[] = []
      if (parsed.total_count !== undefined) {
        parts.push(`Total: ${parsed.total_count}${parsed.truncated ? ' (truncated)' : ''}`)
      }
      if (parsed.files && Array.isArray(parsed.files)) {
        parts.push(`Files:\n${parsed.files.slice(0, 20).map((f: string) => `  ${f}`).join('\n')}`)
        if (parsed.files.length > 20) {
          parts.push(`  ... and ${parsed.files.length - 20} more`)
        }
      }
      if (parsed.matches && Array.isArray(parsed.matches)) {
        parts.push(`Matches:\n${parsed.matches.slice(0, 20).map((m: unknown) => `  ${String(m)}`).join('\n')}`)
        if (parsed.matches.length > 20) {
          parts.push(`  ... and ${parsed.matches.length - 20} more`)
        }
      }
      return {
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
        output: parts.join('\n') || JSON.stringify(parsed, null, 2),
        metadata: { total_count: parsed.total_count, truncated: parsed.truncated },
      }
    }

    if (parsed.stdout !== undefined || parsed.stderr !== undefined) {
      const parts: string[] = []
      if (parsed.stdout) parts.push(parsed.stdout)
      if (parsed.stderr) parts.push(`[stderr] ${parsed.stderr}`)
      if (parsed.exit_code !== undefined) parts.push(`[exit code: ${parsed.exit_code}]`)
      return {
        toolName: parsed.tool_name || parsed.name || parsed.toolName,
        output: parts.join('\n') || '(empty)',
        metadata: { exit_code: parsed.exit_code },
      }
    }

    return {
      toolName: parsed.tool_name || parsed.name || parsed.toolName,
      output: JSON.stringify(parsed, null, 2),
    }
  } catch {
    return {
      output: content,
    }
  }
}

// ── JSON 行解析 ──────────────────────────────────────────────────────────────

function parseJsonItems(content: string): { items: unknown[]; plainLines: string[] } | null {
  const lines = content.split('\n').filter((line) => line.trim())
  const items: unknown[] = []
  const plainLines: string[] = []

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        const parsed = JSON.parse(trimmed)
        items.push(parsed)
      } catch {
        plainLines.push(line)
      }
    } else {
      plainLines.push(line)
    }
  }

  return { items, plainLines }
}

// ── 结构化消息解析 ───────────────────────────────────────────────────────────

export function parseStructuredMessage(content: string): StructuredMessageView | null {
  if (!content || !content.trim()) return null

  const parsed = parseJsonItems(content)
  if (!parsed || parsed.items.length === 0) {
    return {
      toolCalls: [],
      thinkings: [],
      toolResults: [],
      plainTexts: parsed?.plainLines || [],
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

    // 检测 Hermes 风格的工具结果格式: {"output": "..."} 或 {"result": "..."}
    const hasHermesOutput = 'output' in row || 'result' in row
    const hasToolCallId = 'tool_call_id' in row || 'toolCallId' in row || 'call_id' in row || 'id' in row

    const type =
      typeRaw ||
      ('thinking' in row || 'thinkingSignature' in row
        ? 'thinking'
        : 'arguments' in row && ('name' in row || 'tool' in row)
          ? 'toolcall'
          : (hasToolCallId && ('content' in row || 'output' in row || 'result' in row)) ||
              (hasHermesOutput && !('name' in row) && !('tool' in row))
            ? 'toolresult'
            : '')

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
        name: getToolDisplayName(
          asString(row.name || row.tool || row.toolName || row.tool_name) || 'unknown',
        ),
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
      const text = asString(row.thinking ?? row.text ?? row.message).trim()
      if (!text) continue
      thinkings.push({
        text,
        hasEncryptedSignature: false,
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
          contentText = asString(rawContent)
        }
      } else {
        contentText = asString(rawContent)
      }

      if (!contentText.trim()) continue
      toolResults.push({
        id: asString(row.id || row.tool_call_id || row.toolCallId || row.call_id) || undefined,
        name: getToolDisplayName(
          asString(row.name || row.tool || row.toolName || row.tool_name) || '工具结果',
        ),
        status: asString(row.status || row.state || row.error) || undefined,
        content: contentText,
      })
      recognized += 1
      continue
    }
  }

  const plainTexts: string[] = []
  for (const line of parsed.plainLines) {
    const trimmedLine = line.trim()
    if (trimmedLine) {
      plainTexts.push(line)
    }
  }

  if (!recognized && plainTexts.length === 0) return null
  return {
    toolCalls,
    thinkings,
    toolResults,
    plainTexts,
  }
}

// ── 工具耗时格式化 ───────────────────────────────────────────────────────────

export function formatToolDuration(duration?: number): string {
  if (!duration) return ''
  if (duration < 1000) return `${duration}ms`
  const seconds = (duration / 1000).toFixed(1)
  return `${seconds}s`
}
