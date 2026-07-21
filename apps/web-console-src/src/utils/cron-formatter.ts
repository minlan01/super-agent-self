// Cron expression formatting utilities
// Pure functions for parsing and formatting cron schedules in Chinese and English
import type { CronJob } from '@/api/types'
import { formatDate, formatRelativeTime } from '@/utils/format'

// ---- Parsing helpers ----

export function parseCronSource(text: string): { expr: string; tz?: string } {
  const value = text.trim()
  const match = value.match(/^(.*?)\s*\(([^()]+)\)\s*$/)
  if (!match) return { expr: value }
  return {
    expr: match[1]?.trim() || value,
    tz: match[2]?.trim() || undefined,
  }
}

export function parseNumberList(value: string, min: number, max: number): number[] | null {
  if (!/^\d+(,\d+)+$/.test(value)) return null
  const list = value
    .split(',')
    .map((item) => Number(item))
    .filter((num) => Number.isInteger(num) && num >= min && num <= max)
  if (list.length === 0) return null
  return Array.from(new Set(list)).sort((a, b) => a - b)
}

export function parseNumberRange(value: string, min: number, max: number): { start: number; end: number } | null {
  const match = value.match(/^(\d+)-(\d+)$/)
  if (!match) return null
  const start = Number(match[1])
  const end = Number(match[2])
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null
  if (start < min || start > max || end < min || end > max || start > end) return null
  return { start, end }
}

export function isHalfHourMinuteRule(minute: string, minuteList: number[] | null): boolean {
  if (minute.trim() === '*/30') return true
  return !!minuteList && minuteList.length === 2 && minuteList[0] === 0 && minuteList[1] === 30
}

// ---- Internal helpers ----

type Pad2Fn = (value: number) => string
type IsNumberFn = (value: string) => boolean
type AsNumFn = (value: string) => number

function makeParseHelpers() {
  const pad2: Pad2Fn = (value) => String(value).padStart(2, '0')
  const isNumber: IsNumberFn = (value) => /^\d+$/.test(value)
  const asNum: AsNumFn = (value) => (isNumber(value) ? Number(value) : NaN)
  return { pad2, isNumber, asNum }
}

function parseScheduleParts(expr: string) {
  const compactExpr = expr.trim().replace(/\s+/g, ' ')
  const parts = compactExpr.split(' ')
  return { compactExpr, parts }
}

// ---- Chinese formatter ----

export function formatCronAsCn(expr: string, tz?: string): string {
  const { compactExpr, parts } = parseScheduleParts(expr)
  const tzSuffix = tz ? `（${tz}）` : ''
  if (parts.length !== 5) return `${compactExpr}${tzSuffix}`

  const { pad2, isNumber, asNum } = makeParseHelpers()
  const minute = parts[0] ?? ''
  const hour = parts[1] ?? ''
  const dayOfMonth = parts[2] ?? ''
  const month = parts[3] ?? ''
  const dayOfWeek = parts[4] ?? ''

  const minuteList = parseNumberList(minute, 0, 59)
  const hourRange = parseNumberRange(hour, 0, 23)
  const minuteMarks = minuteList?.map((num) => `${pad2(num)} 分`).join('、') || ''
  const isHalfHour = isHalfHourMinuteRule(minute, minuteList)

  if (isHalfHour && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `每半小时${tzSuffix}`
  }
  if (/^\*\/\d+$/.test(minute) && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `每 ${minute.slice(2)} 分钟${tzSuffix}`
  }
  if (minuteList && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `每小时的 ${minuteMarks}${tzSuffix}`
  }
  if (minute === '0' && /^\*\/\d+$/.test(hour) && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `每 ${hour.slice(2)} 小时${tzSuffix}`
  }
  if (isNumber(minute) && /^\*\/\d+$/.test(hour) && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `每 ${hour.slice(2)} 小时的 ${pad2(asNum(minute))} 分${tzSuffix}`
  }
  if (/^\*\/\d+$/.test(minute) && hourRange && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    if (isHalfHour) {
      return `每天 ${pad2(hourRange.start)} 点到 ${pad2(hourRange.end)} 点，每半小时${tzSuffix}`
    }
    return `每天 ${pad2(hourRange.start)} 点到 ${pad2(hourRange.end)} 点，每 ${minute.slice(2)} 分钟${tzSuffix}`
  }
  if (minuteList && hourRange && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    if (isHalfHour) {
      return `每天 ${pad2(hourRange.start)} 点到 ${pad2(hourRange.end)} 点，每半小时${tzSuffix}`
    }
    return `每天 ${pad2(hourRange.start)} 点到 ${pad2(hourRange.end)} 点，每小时的 ${minuteMarks}${tzSuffix}`
  }

  const cnWeekdayMap: Record<string, string> = {
    '0': '周日', '7': '周日', '1': '周一', '2': '周二', '3': '周三',
    '4': '周四', '5': '周五', '6': '周六',
    SUN: '周日', MON: '周一', TUE: '周二', WED: '周三', THU: '周四', FRI: '周五', SAT: '周六',
  }
  const dowText = resolveDowText(dayOfWeek, cnWeekdayMap, '至', '、')
  if (isNumber(minute) && isNumber(hour)) {
    const timeText = `${pad2(asNum(hour))}:${pad2(asNum(minute))}`
    if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*') return `每天 ${timeText}${tzSuffix}`
    if (dayOfMonth === '*' && month === '*' && dowText) return `每周${dowText} ${timeText}${tzSuffix}`
    if (isNumber(dayOfMonth) && month === '*' && dayOfWeek === '*') return `每月 ${asNum(dayOfMonth)} 日 ${timeText}${tzSuffix}`
    if (isNumber(dayOfMonth) && isNumber(month) && dayOfWeek === '*') return `每年 ${asNum(month)} 月 ${asNum(dayOfMonth)} 日 ${timeText}${tzSuffix}`
  }

  return `${compactExpr}${tzSuffix}`
}

// ---- English formatter ----

export function formatCronAsEn(
  expr: string,
  tz: string | undefined,
  t: (key: string, params?: Record<string, unknown>) => string,
): string {
  const { compactExpr, parts } = parseScheduleParts(expr)
  const tzSuffix = tz ? ` (${tz})` : ''
  if (parts.length !== 5) return `${compactExpr}${tzSuffix}`

  const { pad2, isNumber, asNum } = makeParseHelpers()
  const minute = parts[0] ?? ''
  const hour = parts[1] ?? ''
  const dayOfMonth = parts[2] ?? ''
  const month = parts[3] ?? ''
  const dayOfWeek = parts[4] ?? ''

  const minuteList = parseNumberList(minute, 0, 59)
  const hourRange = parseNumberRange(hour, 0, 23)
  const minuteMarks = minuteList?.map((num) => `${pad2(num)}`).join(', ') || ''
  const isHalfHour = isHalfHourMinuteRule(minute, minuteList)

  if (isHalfHour && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `Every half hour${tzSuffix}`
  }
  if (/^\*\/\d+$/.test(minute) && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return t('pages.cron.schedule.every', { value: Number(minute.slice(2)), unit: t('pages.cron.units.minutes') }) + tzSuffix
  }
  if (minuteList && hour === '*' && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return `Every hour at ${minuteMarks} min${tzSuffix}`
  }
  if (minute === '0' && /^\*\/\d+$/.test(hour) && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return t('pages.cron.schedule.every', { value: Number(hour.slice(2)), unit: t('pages.cron.units.hours') }) + tzSuffix
  }
  if (isNumber(minute) && /^\*\/\d+$/.test(hour) && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    return t('pages.cron.schedule.everyHoursAtMinute', { value: Number(hour.slice(2)), minute: pad2(asNum(minute)) }) + tzSuffix
  }
  if (/^\*\/\d+$/.test(minute) && hourRange && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    if (isHalfHour) {
      return `Every half hour between ${pad2(hourRange.start)}:00-${pad2(hourRange.end)}:59 daily${tzSuffix}`
    }
    return `Every ${Number(minute.slice(2))} minutes between ${pad2(hourRange.start)}:00-${pad2(hourRange.end)}:59 daily${tzSuffix}`
  }
  if (minuteList && hourRange && dayOfMonth === '*' && month === '*' && dayOfWeek === '*') {
    if (isHalfHour) {
      return `Every half hour between ${pad2(hourRange.start)}:00-${pad2(hourRange.end)}:59 daily${tzSuffix}`
    }
    return `Every hour at ${minuteMarks} min between ${pad2(hourRange.start)}:00-${pad2(hourRange.end)}:59 daily${tzSuffix}`
  }

  const enWeekdayMap: Record<string, string> = {
    '0': 'Sun', '7': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed',
    '4': 'Thu', '5': 'Fri', '6': 'Sat',
    SUN: 'Sun', MON: 'Mon', TUE: 'Tue', WED: 'Wed', THU: 'Thu', FRI: 'Fri', SAT: 'Sat',
  }
  const dowText = resolveDowText(dayOfWeek, enWeekdayMap, '-', ', ')
  if (isNumber(minute) && isNumber(hour)) {
    const timeText = `${pad2(asNum(hour))}:${pad2(asNum(minute))}`
    if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*') return t('pages.cron.schedule.dailyAt', { time: timeText }) + tzSuffix
    if (dayOfMonth === '*' && month === '*' && dowText) return t('pages.cron.schedule.weeklyAt', { weekdays: dowText, time: timeText }) + tzSuffix
    if (isNumber(dayOfMonth) && month === '*' && dayOfWeek === '*') return t('pages.cron.schedule.monthlyAt', { day: asNum(dayOfMonth), time: timeText }) + tzSuffix
    if (isNumber(dayOfMonth) && isNumber(month) && dayOfWeek === '*') return t('pages.cron.schedule.yearlyAt', { month: asNum(month), day: asNum(dayOfMonth), time: timeText }) + tzSuffix
  }

  return `${compactExpr}${tzSuffix}`
}

// ---- Shared day-of-week resolver ----

function normalizeDow(value: string, weekdayMap: Record<string, string>): string | null {
  return weekdayMap[value.toUpperCase()] || null
}

function parseDowPart(value: string, weekdayMap: Record<string, string>, rangeSep: string): string | null {
  if (value.includes('-')) {
    const [start, end] = value.split('-')
    const startText = start ? normalizeDow(start, weekdayMap) : null
    const endText = end ? normalizeDow(end, weekdayMap) : null
    return startText && endText ? `${startText}${rangeSep}${endText}` : null
  }
  return normalizeDow(value, weekdayMap)
}

function resolveDowText(dayOfWeek: string, weekdayMap: Record<string, string>, rangeSep: string, listSep: string): string | null {
  if (dayOfWeek === '*') return null
  const partsText = dayOfWeek.split(',').map((item) => parseDowPart(item.trim(), weekdayMap, rangeSep)).filter(Boolean) as string[]
  if (!partsText.length) return null
  return partsText.join(listSep)
}

// ---- Schedule text resolution ----

export type EveryUnit = 'minutes' | 'hours' | 'days'

export function resolveEveryForm(everyMs: number): { value: number; unit: EveryUnit } {
  if (everyMs % 86_400_000 === 0) {
    return { value: everyMs / 86_400_000, unit: 'days' }
  }
  if (everyMs % 3_600_000 === 0) {
    return { value: everyMs / 3_600_000, unit: 'hours' }
  }
  return { value: Math.max(1, Math.round(everyMs / 60_000)), unit: 'minutes' }
}

export function resolveScheduleText(
  job: CronJob,
  locale: string,
  t: (key: string, params?: Record<string, unknown>) => string,
): string {
  if (job.scheduleObj?.kind === 'cron') {
    return locale === 'zh-CN'
      ? formatCronAsCn(job.scheduleObj.expr, job.scheduleObj.tz)
      : formatCronAsEn(job.scheduleObj.expr, job.scheduleObj.tz, t)
  }
  if (job.scheduleObj?.kind === 'every') {
    const every = resolveEveryForm(job.scheduleObj.everyMs)
    const unitText =
      every.unit === 'minutes'
        ? t('pages.cron.units.minutes')
        : every.unit === 'hours'
          ? t('pages.cron.units.hours')
          : t('pages.cron.units.days')
    return t('pages.cron.schedule.every', { value: every.value, unit: unitText })
  }
  if (job.scheduleObj?.kind === 'at') {
    return t('pages.cron.schedule.at', { time: formatDate(job.scheduleObj.at) })
  }
  if (job.schedule) {
    const schedule = parseCronSource(job.schedule)
    const tzVal = schedule.tz || job.timezone
    return locale === 'zh-CN'
      ? formatCronAsCn(schedule.expr, tzVal)
      : formatCronAsEn(schedule.expr, tzVal, t)
  }
  return '-'
}

export function nextRunText(job: CronJob): string {
  if (job.state?.nextRunAtMs) {
    return formatRelativeTime(job.state.nextRunAtMs)
  }
  if (job.nextRun) {
    return formatRelativeTime(job.nextRun)
  }
  return '-'
}

export function lastRunText(job: CronJob): string {
  if (job.state?.lastRunAtMs) {
    return formatRelativeTime(job.state.lastRunAtMs)
  }
  if (job.lastRun) {
    return formatRelativeTime(job.lastRun)
  }
  return '-'
}

export function toDatetimeLocal(value?: string): string {
  if (!value) return ''
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return ''
  const date = new Date(timestamp - new Date(timestamp).getTimezoneOffset() * 60_000)
  return date.toISOString().slice(0, 16)
}
