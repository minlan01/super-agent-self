/**
 * useHermesProviderConfig — Hermes Provider 配置表单管理
 * 提取自 HermesModelsPage.vue
 */
import { ref, shallowRef, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import { useHermesModelStore } from '@/stores/hermes/model'
import { useHermesConfigStore } from '@/stores/hermes/connection'
import type { HermesProviderConfig } from '@/api/hermes/types'
import {
  getProviderEnvVar,
  getProviderBaseUrlVar,
  getProviderDisplayBaseUrlValue,
} from '@/utils/hermes-provider-helpers'

interface UseHermesProviderConfigDeps {
  currentModelFromConfig: Ref<string>
  fetchModelsFromEndpoint: (baseUrl: string, apiKey?: string, providerConfig?: Record<string, unknown>) => Promise<{ id: string; name?: string }[]>
}

export function useHermesProviderConfig(deps: UseHermesProviderConfigDeps) {
  const { t } = useI18n()
  const message = useMessage()
  const modelStore = useHermesModelStore()
  const configStore = useHermesConfigStore()

  // ─── 配置表单状态 ────────────────────────────────────────
  const revealedKeys = shallowRef<Set<string>>(new Set())
  const editingProvider = ref<HermesProviderConfig | null>(null)
  const showConfigForm = ref(false)
  const configFormApiKey = ref('')
  const configFormBaseUrl = ref('')
  const configFormModel = ref('')
  const configFormSaving = ref(false)
  const configFormModels = shallowRef<{ id: string; name?: string }[]>([])
  const configFormModelsLoading = ref(false)

  // ─── 配置表单操作 ────────────────────────────────────────

  async function handleOpenConfig(provider: HermesProviderConfig) {
    editingProvider.value = provider
    configFormApiKey.value = ''
    configFormBaseUrl.value = provider.defaultBaseUrl || ''
    configFormModel.value = ''
    configFormModels.value = []
    showConfigForm.value = true
  }

  async function handleEditConfig(provider: HermesProviderConfig) {
    editingProvider.value = provider
    configFormApiKey.value = ''
    configFormBaseUrl.value = getProviderDisplayBaseUrlValue(
      provider,
      modelStore.envVars,
      modelStore.rawEnvVars as Record<string, { is_set?: boolean; redacted_value?: string }> | null,
      revealedKeys.value,
      configStore.config?.providers as Record<string, { base_url?: string }> | undefined,
    )
    configFormModel.value = deps.currentModelFromConfig.value || ''
    configFormModels.value = []
    const rawVars = modelStore.rawEnvVars as Record<string, { is_set?: boolean; redacted_value?: string }> | null
    if (rawVars && provider.baseUrlKey && rawVars[provider.baseUrlKey]?.redacted_value) {
      configFormBaseUrl.value = rawVars[provider.baseUrlKey]!.redacted_value as string
    }
    showConfigForm.value = true
  }

  async function fetchConfigFormModels() {
    const baseUrl = configFormBaseUrl.value.trim() || editingProvider.value?.defaultBaseUrl
    if (!baseUrl) {
      message.warning(t('pages.hermesModels.availableModels.noEndpoint'))
      return
    }

    configFormModelsLoading.value = true
    configFormModels.value = []

    try {
      const providerConfig = editingProvider.value ? {
        modelsApiPath: editingProvider.value.modelsApiPath,
        modelsApiAuthType: editingProvider.value.modelsApiAuthType,
        modelsApiExtraHeaders: editingProvider.value.modelsApiExtraHeaders,
        modelsApiQueryParam: editingProvider.value.modelsApiQueryParam,
        defaultBaseUrl: editingProvider.value.defaultBaseUrl,
      } : undefined

      const models = await deps.fetchModelsFromEndpoint(
        baseUrl,
        configFormApiKey.value.trim() || undefined,
        providerConfig as Record<string, unknown>
      )
      configFormModels.value = models
      if (models.length > 0 && !configFormModel.value) {
        configFormModel.value = models[0]!.id
      }
      message.success(t('pages.hermesModels.customProvider.modelsFound', { count: models.length }))
    } catch (error) {
      console.error('[HermesModelsPage] fetchConfigFormModels failed:', error)
      const errorMsg = error instanceof Error ? error.message : String(error)
      message.error(t('pages.hermesModels.availableModels.fetchFailed') + ': ' + errorMsg)
    } finally {
      configFormModelsLoading.value = false
    }
  }

  function handleCancelConfig() {
    editingProvider.value = null
    showConfigForm.value = false
    configFormApiKey.value = ''
    configFormBaseUrl.value = ''
    configFormModel.value = ''
  }

  async function handleSaveConfig() {
    if (!editingProvider.value) return

    configFormSaving.value = true
    try {
      if (configFormApiKey.value.trim()) {
        await modelStore.setEnvVar(editingProvider.value.envKey, configFormApiKey.value.trim())
      }
      if (editingProvider.value.baseUrlKey && configFormBaseUrl.value.trim()) {
        await modelStore.setEnvVar(editingProvider.value.baseUrlKey, configFormBaseUrl.value.trim())
      }
      
      if (configFormModel.value.trim()) {
        const modelConfig: Record<string, unknown> = {
          default: configFormModel.value.trim(),
          provider: editingProvider.value.id,
        }
        
        if (editingProvider.value.id === 'custom' && configFormBaseUrl.value.trim()) {
          modelConfig.base_url = configFormBaseUrl.value.trim()
          if (configFormApiKey.value.trim()) {
            modelConfig.api_key = configFormApiKey.value.trim()
          }
        }
        
        await configStore.updateConfig({ model: modelConfig } as any)
      }
      message.success(t('pages.hermesModels.providerConfig.saveSuccess'))
      handleCancelConfig()
      await configStore.fetchConfig()
    } catch {
      message.error(t('pages.hermesModels.providerConfig.saveFailed'))
    } finally {
      configFormSaving.value = false
    }
  }

  async function handleDeleteConfig(provider: HermesProviderConfig) {
    try {
      const envVar = getProviderEnvVar(provider, modelStore.envVars)
      const rawVars = modelStore.rawEnvVars as Record<string, { is_set?: boolean; redacted_value?: string }> | null
      const isSet = envVar?.value?.trim() || envVar?.masked || rawVars?.[provider.envKey]?.is_set === true
      
      if (isSet) {
        await modelStore.deleteEnvVar(provider.envKey)
      }
      
      if (provider.baseUrlKey) {
        const baseUrlVar = getProviderBaseUrlVar(provider, modelStore.envVars)
        const baseUrlIsSet = baseUrlVar?.value?.trim() || rawVars?.[provider.baseUrlKey]?.is_set === true
        if (baseUrlVar && baseUrlIsSet) {
          await modelStore.deleteEnvVar(provider.baseUrlKey)
        }
      }
      
      const newRevealed = new Set(revealedKeys.value)
      newRevealed.delete(provider.envKey)
      if (provider.baseUrlKey) {
        newRevealed.delete(provider.baseUrlKey)
      }
      revealedKeys.value = newRevealed
      
      await modelStore.fetchEnvVars()
      message.success(t('pages.hermesModels.providerConfig.deleteSuccess'))
    } catch (error) {
      console.error('[HermesModelsPage] handleDeleteConfig failed:', error)
      message.error(t('pages.hermesModels.providerConfig.deleteFailed'))
    }
  }

  async function handleRevealKey(provider: HermesProviderConfig) {
    try {
      const value = await modelStore.revealEnvVar(provider.envKey)
      revealedKeys.value = new Set([...revealedKeys.value, provider.envKey])
      const vars = modelStore.envVars
      if (Array.isArray(vars)) {
        const idx = vars.findIndex((v) => v.key === provider.envKey)
        if (idx >= 0) {
          vars[idx] = { ...vars[idx]!, value, masked: false }
        }
      }
    } catch {
      message.error(t('pages.hermesModels.providerConfig.revealFailed'))
    }
  }

  async function handleRevealBaseUrl(provider: HermesProviderConfig) {
    if (!provider.baseUrlKey) return
    try {
      const value = await modelStore.revealEnvVar(provider.baseUrlKey)
      revealedKeys.value = new Set([...revealedKeys.value, provider.baseUrlKey])
      const vars = modelStore.envVars
      if (Array.isArray(vars)) {
        const idx = vars.findIndex((v) => v.key === provider.baseUrlKey)
        if (idx >= 0) {
          vars[idx] = { ...vars[idx]!, value, masked: false }
        }
      }
    } catch {
      message.error(t('pages.hermesModels.providerConfig.revealFailed'))
    }
  }

  return {
    // 状态
    revealedKeys,
    editingProvider,
    showConfigForm,
    configFormApiKey,
    configFormBaseUrl,
    configFormModel,
    configFormSaving,
    configFormModels,
    configFormModelsLoading,
    // 操作
    handleOpenConfig,
    handleEditConfig,
    fetchConfigFormModels,
    handleCancelConfig,
    handleSaveConfig,
    handleDeleteConfig,
    handleRevealKey,
    handleRevealBaseUrl,
  }
}
