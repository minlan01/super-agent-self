import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createBackoffTimer, type BackoffConfig } from '../useExponentialBackoff'

describe('useExponentialBackoff', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns expected interface', () => {
    const backoff = createBackoffTimer()
    expect(backoff).toHaveProperty('schedule')
    expect(backoff).toHaveProperty('reset')
    expect(backoff).toHaveProperty('cancel')
    expect(backoff).toHaveProperty('getAttempt')
    expect(backoff).toHaveProperty('getConfig')
    expect(typeof backoff.schedule).toBe('function')
    expect(typeof backoff.reset).toBe('function')
    expect(typeof backoff.cancel).toBe('function')
    expect(typeof backoff.getAttempt).toBe('function')
    expect(typeof backoff.getConfig).toBe('function')
  })

  it('schedule calls callback after delay', () => {
    const backoff = createBackoffTimer({ baseDelay: 500, jitter: 0 })
    const callback = vi.fn()
    const result = backoff.schedule(callback)
    expect(result).toBe(true)
    expect(callback).not.toHaveBeenCalled()
    vi.advanceTimersByTime(500)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('getDelay increases exponentially', () => {
    const backoff = createBackoffTimer({ baseDelay: 1000, multiplier: 2, jitter: 0, maxDelay: 60000 })
    const callback = vi.fn()

    // First attempt: 1000 * 2^0 = 1000
    backoff.schedule(callback)
    expect(backoff.getAttempt()).toBe(1)
    vi.advanceTimersByTime(1000)
    expect(callback).toHaveBeenCalledTimes(1)

    // Second attempt: 1000 * 2^1 = 2000
    callback.mockClear()
    backoff.schedule(callback)
    expect(backoff.getAttempt()).toBe(2)
    vi.advanceTimersByTime(2000)
    expect(callback).toHaveBeenCalledTimes(1)

    // Third attempt: 1000 * 2^2 = 4000
    callback.mockClear()
    backoff.schedule(callback)
    expect(backoff.getAttempt()).toBe(3)
    vi.advanceTimersByTime(4000)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('maxDelay is respected', () => {
    const backoff = createBackoffTimer({ baseDelay: 1000, maxDelay: 3000, multiplier: 2, jitter: 0, maxRetries: 20 })
    const callback = vi.fn()

    // Attempt 0: 1000 * 2^0 = 1000
    backoff.schedule(callback)
    vi.advanceTimersByTime(1000)
    callback.mockClear()

    // Attempt 1: 1000 * 2^1 = 2000
    backoff.schedule(callback)
    vi.advanceTimersByTime(2000)
    callback.mockClear()

    // Attempt 2: 1000 * 2^2 = 4000, capped at 3000
    backoff.schedule(callback)
    expect(backoff.getAttempt()).toBe(3)
    // Advance 3000 — callback should fire
    vi.advanceTimersByTime(3000)
    expect(callback).toHaveBeenCalledTimes(1)
  })

  it('maxRetries stops scheduling', () => {
    const backoff = createBackoffTimer({ baseDelay: 1, maxRetries: 3, jitter: 0 })
    const callback = vi.fn()

    const r1 = backoff.schedule(callback)
    expect(r1).toBe(true)
    vi.advanceTimersByTime(1)

    const r2 = backoff.schedule(callback)
    expect(r2).toBe(true)
    vi.advanceTimersByTime(1)

    const r3 = backoff.schedule(callback)
    expect(r3).toBe(true)
    vi.advanceTimersByTime(1)

    // 4th attempt should fail
    const r4 = backoff.schedule(callback)
    expect(r4).toBe(false)
  })

  it('reset clears attempt counter', () => {
    const backoff = createBackoffTimer({ baseDelay: 1, maxRetries: 3, jitter: 0 })
    const callback = vi.fn()

    backoff.schedule(callback)
    vi.advanceTimersByTime(1)
    backoff.schedule(callback)
    vi.advanceTimersByTime(1)
    expect(backoff.getAttempt()).toBe(2)

    backoff.reset()
    expect(backoff.getAttempt()).toBe(0)

    // Should be able to schedule again after reset
    const result = backoff.schedule(callback)
    expect(result).toBe(true)
  })

  it('cancel clears pending timer', () => {
    const backoff = createBackoffTimer({ baseDelay: 5000, jitter: 0 })
    const callback = vi.fn()

    backoff.schedule(callback)
    backoff.cancel()
    vi.advanceTimersByTime(10000)
    expect(callback).not.toHaveBeenCalled()
  })

  it('reset both cancels timer and resets attempt count', () => {
    const backoff = createBackoffTimer({ baseDelay: 100, jitter: 0, maxRetries: 5 })
    const callback = vi.fn()

    backoff.schedule(callback)
    vi.advanceTimersByTime(100)
    expect(callback).toHaveBeenCalledTimes(1)

    backoff.schedule(callback)
    vi.advanceTimersByTime(200)  // 100 * 2^1 = 200
    expect(callback).toHaveBeenCalledTimes(2)
    expect(backoff.getAttempt()).toBe(2)

    backoff.reset()
    expect(backoff.getAttempt()).toBe(0)

    // Should schedule again as if fresh
    const result = backoff.schedule(callback)
    expect(result).toBe(true)
    vi.advanceTimersByTime(100)  // base delay again
    expect(callback).toHaveBeenCalledTimes(3) // 2 before reset + 1 after
  })

  it('getConfig returns merged config with defaults', () => {
    const backoff = createBackoffTimer({ baseDelay: 2000 })
    const cfg = backoff.getConfig()
    expect(cfg.baseDelay).toBe(2000)
    expect(cfg.maxDelay).toBe(30000)
    expect(cfg.multiplier).toBe(2)
    expect(cfg.jitter).toBe(500)
    expect(cfg.maxRetries).toBe(10)
  })

  it('getConfig returns fully custom config', () => {
    const backoff = createBackoffTimer({
      baseDelay: 500,
      maxDelay: 10000,
      multiplier: 3,
      jitter: 100,
      maxRetries: 5,
    })
    const cfg = backoff.getConfig()
    expect(cfg.baseDelay).toBe(500)
    expect(cfg.maxDelay).toBe(10000)
    expect(cfg.multiplier).toBe(3)
    expect(cfg.jitter).toBe(100)
    expect(cfg.maxRetries).toBe(5)
  })

  it('getDelay with jitter stays within baseDelay and maxDelay bounds', () => {
    // Run many times to exercise jitter randomness
    const backoff = createBackoffTimer({ baseDelay: 1000, maxDelay: 30000, jitter: 500, multiplier: 2, maxRetries: 100 })
    const callback = vi.fn()

    // With jitter of 500 and base of 1000, at attempt 0 the raw delay is 1000
    // jittered range: [500, 1500], clamped to [1000, 30000]
    // So effective range is [1000, 1500]
    for (let i = 0; i < 50; i++) {
      backoff.reset()
      backoff.schedule(callback)
      vi.advanceTimersByTime(1500) // advance past max possible delay at attempt 0
    }
    // All 50 should have fired
    expect(callback).toHaveBeenCalledTimes(50)
  })

  it('schedule returns false after maxRetries and callback is not called', () => {
    const backoff = createBackoffTimer({ baseDelay: 1, maxRetries: 2, jitter: 0 })
    const callback = vi.fn()

    backoff.schedule(callback)
    vi.advanceTimersByTime(1)
    backoff.schedule(callback)
    vi.advanceTimersByTime(1)

    // Now at max
    const result = backoff.schedule(callback)
    expect(result).toBe(false)
    vi.advanceTimersByTime(1000)
    expect(callback).toHaveBeenCalledTimes(2) // only the first 2
  })
})
