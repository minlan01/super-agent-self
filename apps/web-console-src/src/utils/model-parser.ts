// ============================================================
// 模型配置解析引擎 — 从 ModelsPage.vue 提取的纯函数
// 无 Vue 依赖，无副作用
// ============================================================

import type { ModelProviderConfig } from '@/api/types'

// ── 类型定义 ─────────────────────────────────────────────────────────────────

export type ModelInputType = 'text' | 'image'

export const DEFAULT_MODEL_INPUT_TYPES: ModelInputType[] = ['text']

export type ModelRefSource =
  | 'models.primary'
  | 'models.fallback'
  | 'agents.defaults.models'
  | 'agents.defaults.model.primary'
  | 'agents.defaults.model.fallback'

// ── ID 规范化 ────────────────────────────────────────────────────────────────

export function normalizeProviderId(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, '-')
}

// ── Model Ref 解析 ───────────────────────────────────────────────────────────

export function splitModelRef(value: string): { providerId: string; modelId: string } | null {
  const modelRef = value.trim()
  const slashIndex = modelRef.indexOf('/')
  if (slashIndex <= 0 || slashIndex >= modelRef.length - 1) {
    return null
  }

  const providerId = modelRef.slice(0, slashIndex).trim()
  const modelId = modelRef.slice(slashIndex + 1).trim()
  if (!providerId || !modelId) {
    return null
  }

  return { providerId, modelId }
}

export function normalizeProviderIdForMatch(value: string): string {
  const normalized = normalizeProviderId(value)
  if (normalized === 'z.ai' || normalized === 'z-ai') return 'zai'
  if (normalized === 'opencode-zen') return 'opencode'
  if (normalized === 'qwen') return 'qwen-portal'
  if (normalized === 'kimi-code') return 'kimi-coding'
  return normalized
}

export function isModelRefFromProvider(modelRef: string, providerId: string): boolean {
  const parsed = splitModelRef(modelRef)
  if (!parsed) return false
  return normalizeProviderIdForMatch(parsed.providerId) === normalizeProviderIdForMatch(providerId)
}

// ── Provider 识别 ────────────────────────────────────────────────────────────

export function looksLikeProviderConfig(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const row = value as Record<string, unknown>
  return (
    'api' in row ||
    'baseUrl' in row ||
    'baseURL' in row ||
    'base_url' in row ||
    'apiKey' in row ||
    'api_key' in row ||
    'token' in row ||
    'models' in row ||
    'modelIds' in row ||
    'availableModels' in row ||
    'whitelist' in row
  )
}

export function extractProviderEntries(config: unknown): Array<{
  id: string
  pathPrefix: 'models.providers' | 'models'
  provider: Record<string, unknown>
}> {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return []
  const root = config as Record<string, unknown>
  const modelsRaw = root.models
  if (!modelsRaw || typeof modelsRaw !== 'object' || Array.isArray(modelsRaw)) return []
  const models = modelsRaw as Record<string, unknown>

  const registry = new Map<string, { id: string; pathPrefix: 'models.providers' | 'models'; provider: Record<string, unknown> }>()
  const addEntry = (
    id: string,
    pathPrefix: 'models.providers' | 'models',
    provider: unknown
  ) => {
    if (!id || !looksLikeProviderConfig(provider)) return
    const existing = registry.get(id)
    if (existing && existing.pathPrefix === 'models.providers' && pathPrefix === 'models') {
      return
    }
    registry.set(id, {
      id,
      pathPrefix,
      provider: provider as Record<string, unknown>,
    })
  }

  const providersRaw = models.providers
  if (providersRaw && typeof providersRaw === 'object' && !Array.isArray(providersRaw)) {
    for (const [id, provider] of Object.entries(providersRaw as Record<string, unknown>)) {
      addEntry(id, 'models.providers', provider)
    }
  }

  const reservedKeys = new Set(['primary', 'fallback', 'mode', 'providers'])
  for (const [id, provider] of Object.entries(models)) {
    if (reservedKeys.has(id)) continue
    addEntry(id, 'models', provider)
  }

  return Array.from(registry.values())
}

// ── Provider 属性读取 ────────────────────────────────────────────────────────

export function readProviderText(
  provider: ModelProviderConfig | Record<string, unknown> | undefined,
  keys: string[]
): string {
  if (!provider) return ''
  const row = provider as Record<string, unknown>
  for (const key of keys) {
    const value = row[key]
    if (typeof value === 'string' && value.trim()) {
      return value
    }
  }
  return ''
}

// ── Model Input 类型规范化 ───────────────────────────────────────────────────

export function normalizeModelInputTypes(value: unknown): ModelInputType[] {
  if (!Array.isArray(value)) return []
  const allowed = new Set<ModelInputType>(['text', 'image'])
  const normalized = value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim().toLowerCase())
    .filter((item): item is ModelInputType => allowed.has(item as ModelInputType))
  return Array.from(new Set(normalized)) as ModelInputType[]
}

export function normalizeModelInputTypeSelection(types: ModelInputType[] | string[]): ModelInputType[] {
  const normalized = normalizeModelInputTypes(types)
  if (normalized.length > 0) {
    return normalized
  }
  return [...DEFAULT_MODEL_INPUT_TYPES]
}

// ── Provider Model ID 读取 ──────────────────────────────────────────────────

export function readProviderModelIds(provider: ModelProviderConfig | Record<string, unknown> | undefined): string[] {
  if (!provider) return []
  const row = provider as Record<string, unknown>

  const collectFromCollection = (value: unknown): string[] => {
    if (!value) return []

    const collectFromArray = (items: unknown[]): string[] => {
      const ids: string[] = []
      for (const item of items) {
        if (typeof item === 'string' && item.trim()) {
          ids.push(item.trim())
          continue
        }
        if (item && typeof item === 'object' && !Array.isArray(item)) {
          const model = item as Record<string, unknown>
          const id =
            (typeof model.id === 'string' && model.id.trim()) ||
            (typeof model.name === 'string' && model.name.trim()) ||
            ''
          if (id) ids.push(id)
        }
      }
      return ids
    }

    if (Array.isArray(value)) {
      return collectFromArray(value)
    }

    if (typeof value === 'object') {
      const ids: string[] = []
      for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
        const candidateKey = key.trim()
        if (!candidateKey) continue

        if (typeof item === 'string' && item.trim()) {
          ids.push(item.trim())
          continue
        }
        if (item && typeof item === 'object' && !Array.isArray(item)) {
          const model = item as Record<string, unknown>
          const id =
            (typeof model.id === 'string' && model.id.trim()) ||
            (typeof model.name === 'string' && model.name.trim()) ||
            ''
          ids.push(id || candidateKey)
          continue
        }
        ids.push(candidateKey)
      }
      return ids
    }

    return []
  }

  const candidates: unknown[] = [
    row.models,
    row.modelIds,
    row.availableModels,
    row.whitelist,
  ]
  const collected: string[] = []
  for (const candidate of candidates) {
    collected.push(...collectFromCollection(candidate))
  }
  return Array.from(new Set(collected))
}

export function readProviderModels(
  provider: ModelProviderConfig | Record<string, unknown> | undefined
): Array<{ id: string; input?: ModelInputType[]; raw?: Record<string, unknown> }> {
  if (!provider) return []
  const row = provider as Record<string, unknown>

  const modelsArray = row.models
  if (!Array.isArray(modelsArray)) {
    return readProviderModelIds(provider).map((id) => ({ id, input: ['text'] as ModelInputType[] }))
  }

  return modelsArray
    .map((item): { id: string; input?: ModelInputType[]; raw?: Record<string, unknown> } => {
      if (typeof item === 'string') {
        return { id: item.trim(), input: ['text'] }
      }
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const model = item as Record<string, unknown>
        const id =
          (typeof model.id === 'string' && model.id.trim()) ||
          (typeof model.name === 'string' && model.name.trim()) ||
          ''
        const input = Array.isArray(model.input)
          ? model.input.filter((v): v is ModelInputType => v === 'text' || v === 'image')
          : (['text'] as ModelInputType[])
        return { id, input, raw: model }
      }
      return { id: '', input: ['text'] }
    })
    .filter((m) => m.id)
}

// ── Model Ref 收集 ───────────────────────────────────────────────────────────

export function collectModelRefsFromUnknown(
  value: unknown,
  source: ModelRefSource
): Array<{ modelRef: string; source: ModelRefSource }> {
  const refs = new Map<string, ModelRefSource>()

  const addRef = (modelRef: string) => {
    if (!refs.has(modelRef)) {
      refs.set(modelRef, source)
    }
  }

  const collect = (input: unknown) => {
    if (!input) return

    if (typeof input === 'string') {
      const parsed = splitModelRef(input)
      if (parsed) addRef(`${parsed.providerId}/${parsed.modelId}`)
      return
    }

    if (Array.isArray(input)) {
      for (const item of input) {
        collect(item)
      }
      return
    }

    if (typeof input === 'object') {
      const row = input as Record<string, unknown>
      const possibleRefs = [row.id, row.model, row.ref, row.primary]
      for (const candidate of possibleRefs) {
        if (typeof candidate === 'string') {
          const parsed = splitModelRef(candidate)
          if (parsed) addRef(`${parsed.providerId}/${parsed.modelId}`)
        }
      }

      for (const [key, item] of Object.entries(row)) {
        const parsedKey = splitModelRef(key)
        if (parsedKey) addRef(`${parsedKey.providerId}/${parsedKey.modelId}`)

        if (typeof item === 'string') {
          const parsedValue = splitModelRef(item)
          if (parsedValue) addRef(`${parsedValue.providerId}/${parsedValue.modelId}`)
        }
      }
    }
  }

  collect(value)
  return Array.from(refs.entries()).map(([modelRef, modelRefSource]) => ({
    modelRef,
    source: modelRefSource,
  }))
}

export function extractConfiguredModelRefs(config: unknown): Array<{ modelRef: string; source: ModelRefSource }> {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return []
  const root = config as Record<string, unknown>
  const refs = new Map<string, ModelRefSource>()
  const addRefs = (value: unknown, source: ModelRefSource) => {
    for (const item of collectModelRefsFromUnknown(value, source)) {
      if (!refs.has(item.modelRef)) {
        refs.set(item.modelRef, item.source)
      }
    }
  }

  const models = root.models as Record<string, unknown> | undefined
  addRefs(models?.primary, 'models.primary')
  addRefs(models?.fallback, 'models.fallback')

  const agents = root.agents as Record<string, unknown> | undefined
  const defaults = agents?.defaults as Record<string, unknown> | undefined
  addRefs(defaults?.models, 'agents.defaults.models')

  const defaultModel = defaults?.model as Record<string, unknown> | undefined
  addRefs(defaultModel?.primary, 'agents.defaults.model.primary')
  addRefs(defaultModel?.fallback, 'agents.defaults.model.fallback')
  addRefs(defaultModel?.fallbacks, 'agents.defaults.model.fallback')

  return Array.from(refs.entries()).map(([modelRef, source]) => ({
    modelRef,
    source,
  }))
}
