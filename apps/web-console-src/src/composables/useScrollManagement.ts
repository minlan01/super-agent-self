import { ref, type Ref } from 'vue'

const BOTTOM_GAP = 32

export function useScrollManagement(
  transcriptRef: Ref<HTMLElement | null>,
  autoFollowBottom: Ref<boolean>,
) {
  let pendingForceScroll = false
  let pendingScroll = false
  let destroyed = false

  function isNearBottom(): boolean {
    const el = transcriptRef.value
    if (!el) return true
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    return distance <= BOTTOM_GAP
  }

  function handleTranscriptScroll() {
    autoFollowBottom.value = isNearBottom()
  }

  function scrollToBottom(options?: { force?: boolean }) {
    const el = transcriptRef.value
    if (!el) return

    const force = options?.force ?? false
    if (!force && !autoFollowBottom.value) return

    el.scrollTop = el.scrollHeight
  }

  function requestScrollToBottom(options?: { force?: boolean }) {
    const force = options?.force ?? false
    if (!force && !autoFollowBottom.value) return
    if (force) pendingForceScroll = true
    if (pendingScroll) return

    pendingScroll = true
    const schedule =
      typeof queueMicrotask === 'function' ? queueMicrotask : (fn: () => void) => Promise.resolve().then(fn)
    schedule(() => {
      pendingScroll = false
      if (destroyed) return
      const forceNow = pendingForceScroll
      pendingForceScroll = false
      scrollToBottom({ force: forceNow })
    })
  }

  function cancelPendingScroll() {
    destroyed = true
    pendingForceScroll = false
    pendingScroll = false
  }

  return {
    isNearBottom,
    handleTranscriptScroll,
    scrollToBottom,
    requestScrollToBottom,
    cancelPendingScroll,
  }
}
