/**
 * Hermes Provider Helpers — Provider 配置相关的纯函数和半纯函数
 * 提取自 HermesModelsPage.vue
 */
import type { HermesProviderConfig, HermesEnvVar } from '@/api/hermes/types'

// ─── Provider ID 映射 ─────────────────────────────────────

export const PROVIDER_ID_TO_HERMES_NAME: Record<string, string> = {
  openrouter: 'openrouter',
  openai: 'openai',
  anthropic: 'anthropic',
  google: 'gemini',
  zhipu: 'zai',
  kimi: 'kimi-coding',
  minimax: 'minimax',
  deepseek: 'deepseek',
  huggingface: 'huggingface',
  nous: 'nous_portal',
}

// ─── 环境变量查找 ──────────────────────────────────────────

/** 从环境变量列表中查找 Provider 的 API Key 变量 */
export function getProviderEnvVar(
  provider: HermesProviderConfig,
  envVars: HermesEnvVar[] | undefined
): HermesEnvVar | undefined {
  if (!Array.isArray(envVars)) return undefined
  return envVars.find((v) => v.key === provider.envKey)
}

/** 从环境变量列表中查找 Provider 的 Base URL 变量 */
export function getProviderBaseUrlVar(
  provider: HermesProviderConfig,
  envVars: HermesEnvVar[] | undefined
): HermesEnvVar | undefined {
  if (!provider.baseUrlKey) return undefined
  if (!Array.isArray(envVars)) return undefined
  return envVars.find((v) => v.key === provider.baseUrlKey)
}

// ─── 配置状态判断 ──────────────────────────────────────────

/** 判断 Provider 是否已配置（API Key 已设置） */
export function isProviderConfigured(
  provider: HermesProviderConfig,
  envVars: HermesEnvVar[] | undefined,
  rawEnvVars: Record<string, { is_set?: boolean; redacted_value?: string }> | null,
  configProviders?: Record<string, { base_url?: string }>
): boolean {
  const envVar = getProviderEnvVar(provider, envVars)
  if (envVar) {
    if (envVar.value && envVar.value.trim()) return true
    if (envVar.masked) return true
  }
  if (rawEnvVars && rawEnvVars[provider.envKey]?.is_set === true) return true
  if (provider.id === 'custom') {
    if (configProviders?.openai?.base_url) return true
  }
  return false
}

// ─── API Key 掩码 ──────────────────────────────────────────

/** 掩码 API Key，保留前6位和后4位 */
export function maskApiKey(value: string): string {
  if (!value || value.length < 8) return '****'
  const prefix = value.slice(0, 6)
  const suffix = value.slice(-4)
  return `${prefix}****${suffix}`
}

/** 获取 Provider 的显示用 API Key（考虑 reveal 状态） */
export function getProviderDisplayApiKey(
  provider: HermesProviderConfig,
  envVars: HermesEnvVar[] | undefined,
  rawEnvVars: Record<string, { is_set?: boolean; redacted_value?: string }> | null,
  revealedKeys: Set<string>
): string {
  const envVar = getProviderEnvVar(provider, envVars)
  if (!envVar) {
    if (rawEnvVars && rawEnvVars[provider.envKey]?.is_set === true) {
      return rawEnvVars[provider.envKey]!.redacted_value as string || '********'
    }
    return ''
  }
  if (!envVar.value || !envVar.value.trim()) {
    if (envVar.masked) return '********'
    if (rawEnvVars && rawEnvVars[provider.envKey]?.is_set === true) {
      return rawEnvVars[provider.envKey]!.redacted_value as string || '********'
    }
    return ''
  }
  if (revealedKeys.has(provider.envKey)) {
    return envVar.value
  }
  if (envVar.masked) return '********'
  return maskApiKey(envVar.value)
}

// ─── Base URL 显示 ─────────────────────────────────────────

/** 获取 Provider 的 Base URL 显示值 */
export function getProviderDisplayBaseUrlValue(
  provider: HermesProviderConfig,
  envVars: HermesEnvVar[] | undefined,
  rawEnvVars: Record<string, { is_set?: boolean; redacted_value?: string }> | null,
  revealedKeys: Set<string>,
  configProviders?: Record<string, { base_url?: string }>
): string {
  const envVar = getProviderBaseUrlVar(provider, envVars)
  if (!envVar) {
    if (rawEnvVars && provider.baseUrlKey && rawEnvVars[provider.baseUrlKey]?.is_set === true) {
      return rawEnvVars[provider.baseUrlKey]!.redacted_value as string || provider.defaultBaseUrl || ''
    }
    if (provider.id === 'custom') {
      if (configProviders?.openai?.base_url) return configProviders.openai.base_url
    }
    return provider.defaultBaseUrl || ''
  }
  if (!envVar.value || !envVar.value.trim()) {
    if (rawEnvVars && provider.baseUrlKey && rawEnvVars[provider.baseUrlKey]?.is_set === true) {
      return rawEnvVars[provider.baseUrlKey]!.redacted_value as string || provider.defaultBaseUrl || ''
    }
    if (provider.id === 'custom') {
      if (configProviders?.openai?.base_url) return configProviders.openai.base_url
    }
    return provider.defaultBaseUrl || ''
  }
  if (revealedKeys.has(provider.baseUrlKey!) && !envVar.masked) {
    return envVar.value
  }
  return envVar.value
}
