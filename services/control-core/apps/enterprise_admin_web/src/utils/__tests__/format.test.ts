import { describe, it, expect } from 'vitest'
import { formatTime } from '../format'

describe('formatTime', () => {
  it('returns formatted date string for valid input', () => {
    const result = formatTime('2026-01-15T10:30:00Z')
    expect(result).toBeTruthy()
    expect(result).not.toBe('-')
  })

  it('returns "-" for empty string', () => {
    expect(formatTime('')).toBe('-')
  })

  it('returns "-" for null-ish input cast to string', () => {
    expect(formatTime(null as unknown as string)).toBe('-')
    expect(formatTime(undefined as unknown as string)).toBe('-')
  })
})
