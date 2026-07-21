/**
 * Unified logger — replaces raw console.* calls with a structured logger.
 * In production, these can be swapped to a remote logging service.
 *
 * Usage:
 *   import { logger } from '@/utils/logger'
 *   logger.info('Agent connected', { agentId: 'foo' })
 *   logger.warn('Slow poll detected', { elapsed: 5000 })
 *   logger.error('Snapshot failed', e)
 */

const LOG_LEVELS = { debug: 0, info: 1, warn: 2, error: 3 } as const
type LogLevel = keyof typeof LOG_LEVELS

const currentLevel: LogLevel = (import.meta.env.VITE_LOG_LEVEL as LogLevel) || 'warn'

function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[currentLevel]
}

function formatPrefix(level: LogLevel, context?: string): string {
  const tag = context ? `[${context}]` : ''
  return `[${level.toUpperCase()}]${tag}`
}

export const logger = {
  debug(msg: string, ...args: unknown[]) {
    if (shouldLog('debug')) console.debug(formatPrefix('debug'), msg, ...args)
  },
  info(msg: string, ...args: unknown[]) {
    if (shouldLog('info')) console.info(formatPrefix('info'), msg, ...args)
  },
  warn(msg: string, ...args: unknown[]) {
    if (shouldLog('warn')) console.warn(formatPrefix('warn'), msg, ...args)
  },
  error(msg: string, ...args: unknown[]) {
    if (shouldLog('error')) console.error(formatPrefix('error'), msg, ...args)
  },
}

/**
 * Create a scoped logger for a module.
 * Usage: const log = createLogger('ChatStore')
 *        log.info('Message sent')
 */
export function createLogger(context: string) {
  return {
    debug(msg: string, ...args: unknown[]) {
      if (shouldLog('debug')) console.debug(formatPrefix('debug', context), msg, ...args)
    },
    info(msg: string, ...args: unknown[]) {
      if (shouldLog('info')) console.info(formatPrefix('info', context), msg, ...args)
    },
    warn(msg: string, ...args: unknown[]) {
      if (shouldLog('warn')) console.warn(formatPrefix('warn', context), msg, ...args)
    },
    error(msg: string, ...args: unknown[]) {
      if (shouldLog('error')) console.error(formatPrefix('error', context), msg, ...args)
    },
  }
}
