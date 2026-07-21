// ============================================================
// Provider 同步引擎 — 从 ModelsPage.vue 提取的同步/修补函数
// 无 Vue 依赖，config 通过参数传入
// ============================================================

import type { ConfigPatch, OpenClawConfig } from '@/api/types'
import {
  splitModelRef,
  isModelRefFromProvider,
  collectModelRefsFromUnknown,
  normalizeProviderId,
} from '@/utils/model-parser'

// ── 类型定义 ─────────────────────────────────────────────────────────────────

export type ProviderSummary = {
  id: string
  api: string
  baseUrl: string
  modelIds: string[]
  sources: string[]
}

export type DefaultsModelsCatalogSnapshot = {
  catalog: Record<string, unknown> | null
  normalized: boolean
}

// ── 纯工具函数 ──────────────────────────────────────────────────────────────

export function sanitizeProviderForDisplay(provider: Record<string, unknown>): Record<string, unknown> {
  const clone: Record<string, unknown> = { ...provider }
  for (const key of ['apiKey', 'api_key', 'key', 'token', 'accessToken', 'access_token']) {
    const value = clone[key]
    if (typeof value === 'string' && value.trim()) {
      clone[key] = '********'
    }
  }
  return clone
}

export function normalizeUniqueIds(ids: string[]): string[] {
  return Array.from(
    new Set(
      ids
        .map((id) => id.trim())
        .filter(Boolean)
    )
  ).sort((a, b) => a.localeCompare(b))
}

export function pickProviderModelIds(ids: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const raw of ids) {
    const id = raw.trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    result.push(id)
  }
  return result
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return null
}

export function normalizeDefaultsModelCatalogEntry(
  entry: unknown,
  fallbackAlias: string
): Record<string, unknown> {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    return fallbackAlias ? { alias: fallbackAlias } : {}
  }

  const row = entry as Record<string, unknown>
  const normalized: Record<string, unknown> = {}

  if (typeof row.alias === 'string' && row.alias.trim()) {
    normalized.alias = row.alias.trim()
  } else if (fallbackAlias) {
    normalized.alias = fallbackAlias
  }
  if (row.params && typeof row.params === 'object' && !Array.isArray(row.params)) {
    normalized.params = row.params
  }
  if (typeof row.streaming === 'boolean') {
    normalized.streaming = row.streaming
  }

  return normalized
}

export function isJsonValueEqual(before: unknown, after: unknown): boolean {
  return JSON.stringify(before ?? null) === JSON.stringify(after ?? null)
}

export function dedupeConfigPatchesByPath(patches: ConfigPatch[]): ConfigPatch[] {
  const map = new Map<string, ConfigPatch>()
  for (const patch of patches) {
    const path = patch.path.trim()
    if (!path) continue
    map.set(path, { path, value: patch.value })
  }
  return Array.from(map.values())
}

// ── Model Ref 解析 ───────────────────────────────────────────────────────────

export function resolveModelRefFromConfigValue(
  value: unknown,
  defaultsModelsCatalog: Record<string, unknown> | null
): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  if (!trimmed) return null

  const parsed = splitModelRef(trimmed)
  if (parsed) {
    return `${parsed.providerId}/${parsed.modelId}`
  }

  if (!defaultsModelsCatalog) return null

  const aliasKey = trimmed.toLowerCase()
  for (const [modelRef, entry] of Object.entries(defaultsModelsCatalog)) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue
    const aliasRaw = (entry as Record<string, unknown>).alias
    const alias = typeof aliasRaw === 'string' ? aliasRaw.trim() : ''
    if (alias && alias.toLowerCase() === aliasKey) {
      return modelRef
    }
  }

  return null
}

// ── Defaults Models Catalog 操作 ─────────────────────────────────────────────

export function readExistingDefaultsModelsCatalog(
  config: OpenClawConfig | null | undefined
): DefaultsModelsCatalogSnapshot {
  const agents = asRecord(config?.agents)
  const defaults = asRecord(agents?.defaults)
  const modelsRaw = defaults?.models

  if (!modelsRaw) {
    return { catalog: null, normalized: false }
  }

  if (Array.isArray(modelsRaw)) {
    const next: Record<string, unknown> = {}
    for (const item of collectModelRefsFromUnknown(modelsRaw, 'agents.defaults.models')) {
      const parsed = splitModelRef(item.modelRef)
      if (!parsed) continue
      const modelRef = `${parsed.providerId}/${parsed.modelId}`
      if (next[modelRef]) continue
      next[modelRef] = { alias: parsed.modelId }
    }
    return { catalog: next, normalized: true }
  }

  const models = asRecord(modelsRaw)
  if (!models) {
    return { catalog: {}, normalized: true }
  }

  const next: Record<string, unknown> = {}
  let normalized = false

  for (const [rawModelRef, entry] of Object.entries(models)) {
    const modelRef = rawModelRef.trim()
    if (!modelRef) {
      normalized = true
      continue
    }
    const parsed = splitModelRef(modelRef)
    const fallbackAlias = parsed?.modelId || modelRef
    const normalizedEntry = normalizeDefaultsModelCatalogEntry(entry, fallbackAlias)
    next[modelRef] = normalizedEntry

    if (modelRef !== rawModelRef) {
      normalized = true
      continue
    }
    if (JSON.stringify(normalizedEntry) !== JSON.stringify(entry ?? {})) {
      normalized = true
    }
  }

  return { catalog: next, normalized }
}

export function buildBootstrapDefaultsModelsCatalog(
  providers: Array<{ id: string; modelIds: string[] }>
): Record<string, unknown> {
  const next: Record<string, unknown> = {}
  for (const provider of providers) {
    for (const modelId of provider.modelIds) {
      const modelRef = `${provider.id}/${modelId}`.trim()
      if (!modelRef) continue
      next[modelRef] = {
        alias: modelId || modelRef,
      }
    }
  }
  return next
}

export function buildMergedDefaultsModelsCatalog(
  entries: Array<{ modelRef: string; alias: string }>,
  config: OpenClawConfig | null | undefined,
  options?: { createWhenMissing?: boolean }
): Record<string, unknown> | null {
  const existingSnapshot = readExistingDefaultsModelsCatalog(config)
  const existing = existingSnapshot.catalog
  if (!existing && !options?.createWhenMissing) return null

  const next: Record<string, unknown> = existing
    ? { ...existing }
    : buildBootstrapDefaultsModelsCatalog([])
  let changed = existingSnapshot.normalized || (!existing && Object.keys(next).length > 0)

  for (const entry of entries) {
    const modelRef = entry.modelRef.trim()
    if (!modelRef) continue
    if (Object.prototype.hasOwnProperty.call(next, modelRef)) continue

    next[modelRef] = {
      alias: entry.alias.trim() || modelRef,
    }
    changed = true
  }

  return changed ? next : null
}

// ── Provider 辅助 ────────────────────────────────────────────────────────────

export function buildAllowlistEntriesFromProvider(
  providerId: string,
  modelIds: string[]
): Array<{ modelRef: string; alias: string }> {
  return normalizeUniqueIds(modelIds).map((modelId) => ({
    modelRef: `${providerId}/${modelId}`,
    alias: modelId,
  }))
}

export function buildProviderModelRefSet(providerId: string, modelIds: string[]): Set<string> {
  const refs = new Set<string>()
  for (const modelId of normalizeUniqueIds(modelIds)) {
    refs.add(`${providerId}/${modelId}`)
  }
  return refs
}

// ── 同步核心 ─────────────────────────────────────────────────────────────────

export function buildDefaultsModelsCatalogSyncedForProvider(
  providerId: string,
  modelIds: string[],
  config: OpenClawConfig | null | undefined,
  options?: { createWhenMissing?: boolean }
): Record<string, unknown> | null {
  const existingSnapshot = readExistingDefaultsModelsCatalog(config)
  const existing = existingSnapshot.catalog
  if (!existing && !options?.createWhenMissing) return null

  const incomingEntries = buildAllowlistEntriesFromProvider(providerId, modelIds)
  const incomingEntryMap = new Map(incomingEntries.map((entry) => [entry.modelRef, entry]))

  const patch: Record<string, unknown> = {}
  let changed = false

  if (existing) {
    for (const [modelRef, entry] of Object.entries(existing)) {
      if (!isModelRefFromProvider(modelRef, providerId)) continue

      const incoming = incomingEntryMap.get(modelRef)
      if (!incoming) {
        // JSON Merge Patch: null means remove outdated provider model ref.
        patch[modelRef] = null
        changed = true
        continue
      }

      const normalizedEntry = normalizeDefaultsModelCatalogEntry(entry, incoming.alias)
      if (!isJsonValueEqual(entry ?? {}, normalizedEntry)) {
        patch[modelRef] = normalizedEntry
        changed = true
      }
      incomingEntryMap.delete(modelRef)
    }
  }

  for (const incoming of incomingEntryMap.values()) {
    patch[incoming.modelRef] = {
      alias: incoming.alias.trim() || incoming.modelRef,
    }
    changed = true
  }

  if (!changed && !existing && options?.createWhenMissing) {
    for (const entry of incomingEntries) {
      patch[entry.modelRef] = {
        alias: entry.alias.trim() || entry.modelRef,
      }
    }
    changed = Object.keys(patch).length > 0
  }

  if (!changed) return null
  return patch
}

export function filterModelRefArrayByProviderSync(
  value: unknown,
  options: {
    providerId: string
    allowedModelRefs: Set<string>
    defaultsModelsCatalog: Record<string, unknown> | null
  }
): { changed: boolean; value: string[] } {
  if (!Array.isArray(value)) {
    return { changed: false, value: [] }
  }

  const next: string[] = []
  let changed = false

  for (const rawItem of value) {
    if (typeof rawItem !== 'string') {
      changed = true
      continue
    }

    const item = rawItem.trim()
    if (!item) {
      changed = true
      continue
    }
    if (item !== rawItem) {
      changed = true
    }

    const resolvedModelRef = resolveModelRefFromConfigValue(item, options.defaultsModelsCatalog)
    if (
      resolvedModelRef &&
      isModelRefFromProvider(resolvedModelRef, options.providerId) &&
      !options.allowedModelRefs.has(resolvedModelRef)
    ) {
      changed = true
      continue
    }
    next.push(item)
  }

  return { changed, value: next }
}

export function syncSingleModelConfigForProvider(
  modelConfig: Record<string, unknown>,
  options: {
    providerId: string
    replacementPrimary: string | null
    allowedModelRefs: Set<string>
    defaultsModelsCatalog: Record<string, unknown> | null
  }
): { changed: boolean; model: Record<string, unknown> } {
  const nextModel = { ...modelConfig }
  let changed = false

  const primaryModelRef = resolveModelRefFromConfigValue(modelConfig.primary, options.defaultsModelsCatalog)
  if (
    primaryModelRef &&
    isModelRefFromProvider(primaryModelRef, options.providerId) &&
    !options.allowedModelRefs.has(primaryModelRef)
  ) {
    nextModel.primary = options.replacementPrimary
    changed = true
  }

  const fallbacks = filterModelRefArrayByProviderSync(modelConfig.fallbacks, {
    providerId: options.providerId,
    allowedModelRefs: options.allowedModelRefs,
    defaultsModelsCatalog: options.defaultsModelsCatalog,
  })
  if (fallbacks.changed) {
    nextModel.fallbacks = fallbacks.value.length > 0 ? fallbacks.value : null
    changed = true
  }

  const legacyFallback = filterModelRefArrayByProviderSync(modelConfig.fallback, {
    providerId: options.providerId,
    allowedModelRefs: options.allowedModelRefs,
    defaultsModelsCatalog: options.defaultsModelsCatalog,
  })
  if (legacyFallback.changed) {
    nextModel.fallback = legacyFallback.value.length > 0 ? legacyFallback.value : null
    changed = true
  }

  return {
    changed,
    model: nextModel,
  }
}

// ── 修补生成 ─────────────────────────────────────────────────────────────────

export function buildAgentModelReferenceSyncPatches(
  providerId: string,
  modelIds: string[],
  defaultsModelsCatalog: Record<string, unknown> | null,
  config: OpenClawConfig | null | undefined
): ConfigPatch[] {
  const patches: ConfigPatch[] = []
  const normalizedModelIds = normalizeUniqueIds(modelIds)
  const replacementPrimary = normalizedModelIds[0] ? `${providerId}/${normalizedModelIds[0]}` : null
  const allowedModelRefs = buildProviderModelRefSet(providerId, normalizedModelIds)

  const agents = asRecord(config?.agents)
  const defaults = asRecord(agents?.defaults)
  const defaultModel = asRecord(defaults?.model)
  if (defaultModel) {
    const synced = syncSingleModelConfigForProvider(defaultModel, {
      providerId,
      replacementPrimary,
      allowedModelRefs,
      defaultsModelsCatalog,
    })
    if (!isJsonValueEqual(defaultModel.primary, synced.model.primary)) {
      patches.push({
        path: 'agents.defaults.model.primary',
        value: synced.model.primary ?? null,
      })
    }
    if (!isJsonValueEqual(defaultModel.fallbacks, synced.model.fallbacks)) {
      patches.push({
        path: 'agents.defaults.model.fallbacks',
        value: synced.model.fallbacks ?? null,
      })
    }
    if (!isJsonValueEqual(defaultModel.fallback, synced.model.fallback)) {
      patches.push({
        path: 'agents.defaults.model.fallback',
        value: synced.model.fallback ?? null,
      })
    }
  }

  const listRaw = Array.isArray(agents?.list) ? agents.list : []
  if (listRaw.length > 0) {
    let listChanged = false
    const nextList = listRaw.map((agentRaw) => {
      if (!agentRaw || typeof agentRaw !== 'object' || Array.isArray(agentRaw)) {
        return agentRaw
      }

      const agent = agentRaw as Record<string, unknown>
      const model = asRecord(agent.model)
      if (!model) {
        return agentRaw
      }

      const synced = syncSingleModelConfigForProvider(model, {
        providerId,
        replacementPrimary,
        allowedModelRefs,
        defaultsModelsCatalog,
      })
      if (!synced.changed) {
        return agentRaw
      }

      listChanged = true
      return {
        ...agent,
        model: synced.model,
      }
    })

    if (listChanged) {
      patches.push({
        path: 'agents.list',
        value: nextList,
      })
    }
  }

  return patches
}

export function buildLegacyModelsReferenceSyncPatches(
  providerId: string,
  modelIds: string[],
  defaultsModelsCatalog: Record<string, unknown> | null,
  config: OpenClawConfig | null | undefined
): ConfigPatch[] {
  const patches: ConfigPatch[] = []
  const normalizedModelIds = normalizeUniqueIds(modelIds)
  const replacementPrimary = normalizedModelIds[0] ? `${providerId}/${normalizedModelIds[0]}` : null
  const allowedModelRefs = buildProviderModelRefSet(providerId, normalizedModelIds)

  const models = asRecord(config?.models)
  if (!models) return patches

  const primaryModelRef = resolveModelRefFromConfigValue(models.primary, defaultsModelsCatalog)
  if (
    primaryModelRef &&
    isModelRefFromProvider(primaryModelRef, providerId) &&
    !allowedModelRefs.has(primaryModelRef)
  ) {
    patches.push({
      path: 'models.primary',
      value: replacementPrimary,
    })
  }

  const fallback = filterModelRefArrayByProviderSync(models.fallback, {
    providerId,
    allowedModelRefs,
    defaultsModelsCatalog,
  })
  if (fallback.changed) {
    patches.push({
      path: 'models.fallback',
      value: fallback.value.length > 0 ? fallback.value : null,
    })
  }

  return patches
}
