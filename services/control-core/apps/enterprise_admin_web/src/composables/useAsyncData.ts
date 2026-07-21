/**
 * Generic async data loader composable.
 * Replaces the repeated loading/try/finally pattern in views.
 */
import { ref, type Ref } from 'vue'

export function useAsyncData<T>(fetcher: () => Promise<T>, defaultValue: T): {
  data: Ref<T>
  loading: Ref<boolean>
  error: Ref<string | null>
  execute: () => Promise<T | null>
}

export function useAsyncData<T>(fetcher: () => Promise<T>, defaultValue?: T): {
  data: Ref<T | null>
  loading: Ref<boolean>
  error: Ref<string | null>
  execute: () => Promise<T | null>
}

export function useAsyncData<T>(fetcher: () => Promise<T>, defaultValue?: T) {
  const data = ref<T | null>(defaultValue ?? null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function execute(): Promise<T | null> {
    loading.value = true
    error.value = null
    try {
      const result = await fetcher()
      data.value = result
      return result
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      error.value = msg
      return null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, execute }
}
