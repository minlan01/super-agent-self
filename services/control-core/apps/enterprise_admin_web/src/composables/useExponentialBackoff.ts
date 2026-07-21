/**
 * Exponential backoff with jitter for WebSocket reconnection.
 * Formula: min(base * 2^attempt + random(-jitter, +jitter), maxDelay)
 */
export interface BackoffConfig {
  baseDelay: number    // ms, default 1000
  maxDelay: number     // ms, default 30000
  multiplier: number   // default 2
  jitter: number       // ms, default 500
  maxRetries: number   // default 10
}

const DEFAULT_CONFIG: BackoffConfig = {
  baseDelay: 1000,
  maxDelay: 30000,
  multiplier: 2,
  jitter: 500,
  maxRetries: 10,
}

export function createBackoffTimer(config: Partial<BackoffConfig> = {}) {
  const cfg = { ...DEFAULT_CONFIG, ...config }
  let attempt = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  function getDelay(): number {
    const exponential = cfg.baseDelay * Math.pow(cfg.multiplier, attempt)
    const jittered = exponential + (Math.random() * 2 - 1) * cfg.jitter
    return Math.min(Math.max(jittered, cfg.baseDelay), cfg.maxDelay)
  }

  function schedule(callback: () => void): boolean {
    if (attempt >= cfg.maxRetries) {
      return false // max retries reached
    }
    const delay = getDelay()
    attempt++
    timer = setTimeout(callback, delay)
    return true
  }

  function reset(): void {
    attempt = 0
    cancel()
  }

  function cancel(): void {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function getAttempt(): number {
    return attempt
  }

  return { schedule, reset, cancel, getAttempt, getConfig: () => cfg }
}
