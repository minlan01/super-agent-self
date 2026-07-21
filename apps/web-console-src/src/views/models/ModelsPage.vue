<script setup lang="ts">
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NCode,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NIcon,
  NInput,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NTabPane,
  NTag,
  NTabs,
  NText,
  useMessage,
} from 'naive-ui'
import { AddOutline, CheckmarkCircleOutline, CloseOutline, CreateOutline, RefreshOutline, SaveOutline, TrashOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useConfigStore } from '@/stores/config'
import { useWebSocketStore } from '@/stores/websocket'
import type { DataTableColumns } from 'naive-ui'
import type { ConfigPatch, ModelProviderConfig, ModelProviderModel, OpenClawConfig } from '@/api/types'
import {
  normalizeProviderId,
  splitModelRef,
  isModelRefFromProvider,
  extractProviderEntries,
  readProviderText,
  normalizeModelInputTypes,
  normalizeModelInputTypeSelection,
  readProviderModelIds,
  readProviderModels,
  collectModelRefsFromUnknown,
  extractConfiguredModelRefs,
  type ModelInputType,
  DEFAULT_MODEL_INPUT_TYPES,
} from '@/utils/model-parser'
import {
  sanitizeProviderForDisplay,
  normalizeUniqueIds,
  pickProviderModelIds,
  asRecord,
  normalizeDefaultsModelCatalogEntry,
  readExistingDefaultsModelsCatalog,
  resolveModelRefFromConfigValue,
  buildBootstrapDefaultsModelsCatalog,
  buildMergedDefaultsModelsCatalog,
  buildAllowlistEntriesFromProvider,
  isJsonValueEqual,
  buildProviderModelRefSet,
  buildDefaultsModelsCatalogSyncedForProvider,
  filterModelRefArrayByProviderSync,
  syncSingleModelConfigForProvider,
  buildAgentModelReferenceSyncPatches,
  buildLegacyModelsReferenceSyncPatches,
  dedupeConfigPatchesByPath,
  type ProviderSummary,
  type DefaultsModelsCatalogSnapshot,
} from '@/utils/provider-sync'

const configStore = useConfigStore()
const wsStore = useWebSocketStore()
const message = useMessage()
const { t, locale } = useI18n()

function joinDisplayList(values: string[]): string {
  const separator = locale.value === 'zh-CN' ? '、' : ', '
  return values.join(separator)
}

const primaryModel = ref('')
const selectedProviderId = ref('')
const providerSearch = ref('')
const showEditProviderModal = ref(false)
const showCreateProviderModal = ref(false)
const showSaveConfirmModal = ref(false)
const confirmActionType = ref<'edit' | 'create'>('edit')
const editActiveTab = ref<'basic' | 'models' | 'preview'>('basic')
const createActiveTab = ref<'basic' | 'models' | 'preview'>('basic')


type ModelConfig = {
  id: string
  input: ModelInputType[]
  raw?: Record<string, unknown>
}

const modelInputTypeOptions = [
  { label: 'text', value: 'text' },
  { label: 'image', value: 'image' },
]

type QuickProviderKey = 'zhipu' | 'kimi' | 'minimax' | 'bailian'

type QuickProviderPreset = {
  key: QuickProviderKey
  providerId: string
  api: string
  baseUrl: string
  modelId: string
  modelName: string
  input: ModelInputType[]
  docsUrl: string
}

const QUICK_PROVIDER_PRESETS: Record<QuickProviderKey, QuickProviderPreset> = {
  zhipu: {
    key: 'zhipu',
    providerId: 'zai',
    api: 'openai-completions',
    baseUrl: 'https://open.bigmodel.cn/api/coding/paas/v4',
    modelId: 'glm-5',
    modelName: 'GLM-5',
    input: ['text'],
    docsUrl: 'https://docs.bigmodel.cn/cn/coding-plan/faq',
  },
  kimi: {
    key: 'kimi',
    providerId: 'moonshot',
    api: 'openai-completions',
    baseUrl: 'https://api.moonshot.cn/v1',
    modelId: 'kimi-k2.5',
    modelName: 'Kimi K2.5',
    input: ['text'],
    docsUrl: 'https://platform.moonshot.cn/docs/introduction',
  },
  minimax: {
    key: 'minimax',
    providerId: 'minimax',
    api: 'openai-completions',
    baseUrl: 'https://api.minimaxi.com/v1',
    modelId: 'MiniMax-M2.5',
    modelName: 'MiniMax-M2.5',
    input: ['text'],
    docsUrl: 'https://platform.minimaxi.com/docs/api-reference/text-openai-api',
  },
  bailian: {
    key: 'bailian',
    providerId: 'bailian',
    api: 'openai-completions',
    baseUrl: 'https://coding.dashscope.aliyuncs.com/v1',
    modelId: 'qwen3.5-plus',
    modelName: 'qwen3.5-plus',
    input: ['text', 'image'],
    docsUrl: 'https://help.aliyun.com/zh/model-studio/coding-plan',
  },
}

const quickProviderList = Object.values(QUICK_PROVIDER_PRESETS)
const quickProviderApiKeys = reactive<Record<QuickProviderKey, string>>({
  zhipu: '',
  kimi: '',
  minimax: '',
  bailian: '',
})
const quickProviderSaving = reactive<Record<QuickProviderKey, boolean>>({
  zhipu: false,
  kimi: false,
  minimax: false,
  bailian: false,
})

const providerForm = reactive({
  id: '',
  api: 'openai-completions',
  baseUrl: '',
  apiKey: '',
  models: [] as ModelConfig[],
  pendingPrimaryModel: '',
})

const createProviderForm = reactive({
  id: '',
  api: 'openai-completions',
  baseUrl: '',
  apiKey: '',
  models: [] as ModelConfig[],
  pendingPrimaryModel: '',
})

const apiOptions = [
  { label: 'OpenAI Completions', value: 'openai-completions' },
  { label: 'OpenAI Responses', value: 'openai-responses' },
  { label: 'Anthropic Messages', value: 'anthropic-messages' },
  { label: 'Google Generative AI', value: 'google-generative-ai' },
]



const providerEntries = computed(() => extractProviderEntries(configStore.config))
const configuredModelRefs = computed(() => extractConfiguredModelRefs(configStore.config))

const providerMap = computed<Record<string, ModelProviderConfig>>(() => {
  const map: Record<string, ModelProviderConfig> = {}
  for (const entry of providerEntries.value) {
    map[entry.id] = entry.provider as unknown as ModelProviderConfig
  }
  return map
})

const quickProviderConfiguredMap = computed<Record<QuickProviderKey, boolean>>(() => {
  const next = {} as Record<QuickProviderKey, boolean>
  for (const item of quickProviderList) {
    const provider = providerMap.value[item.providerId]
    if (!provider) {
      next[item.key] = false
      continue
    }
    next[item.key] = readProviderModelIds(provider).length > 0
  }
  return next
})

const providerPathPrefixMap = computed<Record<string, 'models.providers' | 'models'>>(() => {
  const map: Record<string, 'models.providers' | 'models'> = {}
  for (const entry of providerEntries.value) {
    map[entry.id] = entry.pathPrefix
  }
  return map
})

const managedProviderIdSet = computed(() => new Set(providerEntries.value.map((entry) => entry.id)))

const providerSummaries = computed(() => {
  const registry = new Map<
    string,
    {
      id: string
      api: string
      baseUrl: string
      modelIds: Set<string>
      sources: Set<string>
    }
  >()

  for (const entry of providerEntries.value) {
    const id = entry.id
    const provider = entry.provider as unknown as ModelProviderConfig
    const providerApi = readProviderText(provider, ['api', 'protocol', 'format']) || '-'
    const providerBaseUrl = readProviderText(provider, ['baseUrl', 'baseURL', 'base_url', 'url', 'endpoint']) || '-'
    registry.set(id, {
      id,
      api: providerApi,
      baseUrl: providerBaseUrl,
      modelIds: new Set(readProviderModelIds(provider)),
      sources: new Set([entry.pathPrefix]),
    })
  }

  for (const refItem of configuredModelRefs.value) {
    const parsed = splitModelRef(refItem.modelRef)
    if (!parsed) continue

    const provider = providerMap.value[parsed.providerId]
    const providerApi = readProviderText(provider, ['api', 'protocol', 'format']) || '-'
    const providerBaseUrl = readProviderText(provider, ['baseUrl', 'baseURL', 'base_url', 'url', 'endpoint']) || '-'

    const current = registry.get(parsed.providerId)
    if (current) {
      current.modelIds.add(parsed.modelId)
      current.sources.add(refItem.source)
      continue
    }

    registry.set(parsed.providerId, {
      id: parsed.providerId,
      api: providerApi,
      baseUrl: providerBaseUrl,
      modelIds: new Set([parsed.modelId]),
      sources: new Set([refItem.source]),
    })
  }

  return Array.from(registry.values())
    .map((item) => ({
      id: item.id,
      api: item.api,
      baseUrl: item.baseUrl,
      modelIds: Array.from(item.modelIds).sort((a, b) => a.localeCompare(b)),
      sources: Array.from(item.sources).sort((a, b) => a.localeCompare(b)),
    }))
    .sort((a, b) => a.id.localeCompare(b.id))
})

const filteredProviderSummaries = computed(() => {
  const q = providerSearch.value.trim().toLowerCase()
  if (!q) return providerSummaries.value
  return providerSummaries.value.filter((item) => {
    if (item.id.toLowerCase().includes(q)) return true
    if (item.api.toLowerCase().includes(q)) return true
    if (item.baseUrl.toLowerCase().includes(q)) return true
    return item.modelIds.some((modelId) => modelId.toLowerCase().includes(q))
  })
})


const selectedProviderHasKey = computed(() => {
  if (!selectedProviderId.value) return false
  const provider = providerMap.value[selectedProviderId.value] as unknown as Record<string, unknown> | undefined
  if (!provider) return false
  return !!readProviderText(provider, ['apiKey', 'api_key', 'key', 'token', 'accessToken', 'access_token'])
})

const selectedProviderRawText = computed(() => {
  if (!selectedProviderId.value) return ''
  const provider = providerMap.value[selectedProviderId.value]
  if (!provider) return ''
  try {
    return JSON.stringify(sanitizeProviderForDisplay(provider as unknown as Record<string, unknown>), null, 2)
  } catch {
    return ''
  }
})

const editingExistingProvider = computed(() => {
  const id = normalizeProviderId(providerForm.id || selectedProviderId.value)
  return !!id && !!providerMap.value[id]
})

const currentEditingProviderId = computed(() =>
  normalizeProviderId(providerForm.id || selectedProviderId.value)
)
const providerEditorTitle = computed(() =>
  editingExistingProvider.value
    ? t('pages.models.editor.titleEdit', { id: currentEditingProviderId.value })
    : selectedProviderId.value
      ? t('pages.models.editor.titleMissing', { id: normalizeProviderId(selectedProviderId.value) })
      : t('pages.models.editor.titleSelect')
)
const providerSubmitLabel = computed(() => t('pages.models.actions.saveChanges'))

const apiKeyPlaceholder = computed(() =>
  editingExistingProvider.value
    ? t('pages.models.form.apiKeyPlaceholderEdit')
    : t('pages.models.form.apiKeyPlaceholderCreate')
)

const currentModelIds = computed(() => normalizeUniqueIds(providerForm.models.map(m => m.id)))
const createCurrentModelIds = computed(() => normalizeUniqueIds(createProviderForm.models.map(m => m.id)))
const editChangePreview = computed(() => {
  if (!editingExistingProvider.value) return null
  const providerId = currentEditingProviderId.value
  const existingProvider = providerMap.value[providerId]
  if (!existingProvider) return null

  const providerPrefix = providerPathPrefixMap.value[providerId] || 'models.providers'
  const providerBasePath = `models.providers.${providerId}`
  const shouldMigrateLegacyProviderPath = providerPrefix === 'models'
  const existingApi = readProviderText(existingProvider, ['api', 'protocol', 'format']) || ''
  const nextApi = providerForm.api || '-'
  const existingBaseUrl = readProviderText(existingProvider, ['baseUrl', 'baseURL', 'base_url', 'url', 'endpoint']) || ''
  const nextBaseUrl = providerForm.baseUrl.trim()

  const existingModelIds = normalizeUniqueIds(readProviderModelIds(existingProvider))
  const nextModelIds = pickProviderModelIds(
    currentModelIds.value.length > 0 ? currentModelIds.value : existingModelIds
  )
  const addedModelIds = nextModelIds.filter((id) => !existingModelIds.includes(id))
  const removedModelIds = existingModelIds.filter((id) => !nextModelIds.includes(id))
  const modelsChanged =
    addedModelIds.length > 0 ||
    removedModelIds.length > 0 ||
    existingModelIds.length !== nextModelIds.length

  const apiKeyInput = providerForm.apiKey.trim()
  const maskedKey = /^[*•]+$/.test(apiKeyInput)
  const willPatchApiKey = !!apiKeyInput && !maskedKey

  const warnings: string[] = []
  const patchPaths = [
    'models.mode',
    `${providerBasePath}.api`,
    `${providerBasePath}.baseUrl`,
    `${providerBasePath}.models`,
  ]

  const apiChanged = existingApi !== nextApi
  const baseUrlChanged = existingBaseUrl !== nextBaseUrl
  if (willPatchApiKey) {
    warnings.push(t('pages.models.preview.warnings.overwriteApiKey'))
    patchPaths.push(`${providerBasePath}.apiKey`)
  }
  if (shouldMigrateLegacyProviderPath) {
    warnings.push(t('pages.models.preview.warnings.migrateLegacyPath'))
    patchPaths.push(`models.${providerId}`)
  }

  const currentPrimary = primaryModel.value.trim() || configStore.config?.agents?.defaults?.model?.primary || ''
  let inferredPrimary = ''
  if (providerForm.pendingPrimaryModel) {
    inferredPrimary = providerForm.pendingPrimaryModel
    patchPaths.push('agents.defaults.model.primary')
  } else if (!currentPrimary && nextModelIds[0]) {
    inferredPrimary = `${providerId}/${nextModelIds[0]}`
    patchPaths.push('agents.defaults.model.primary')
  }

  if (removedModelIds.length > 0) {
    warnings.push(t('pages.models.preview.warnings.removeModels'))
  }

  const defaultsCatalogSnapshot = readExistingDefaultsModelsCatalog(configStore.config)
  const modelReferenceSyncPatches = buildAgentModelReferenceSyncPatches(
    providerId,
    nextModelIds,
    defaultsCatalogSnapshot.catalog,
    configStore.config
  )
  for (const patch of modelReferenceSyncPatches) {
    if (!patchPaths.includes(patch.path)) {
      patchPaths.push(patch.path)
    }
  }

  const hasChanges =
    apiChanged ||
    baseUrlChanged ||
    modelsChanged ||
    willPatchApiKey ||
    !!inferredPrimary ||
    modelReferenceSyncPatches.length > 0

  return {
    providerId,
    hasChanges,
    warnings,
    patchPaths,
    apiDiff: {
      before: existingApi || '-',
      after: nextApi || '-',
      changed: apiChanged,
    },
    baseUrlDiff: {
      before: existingBaseUrl || '-',
      after: nextBaseUrl || '-',
      changed: baseUrlChanged,
    },
    modelDiff: {
      changed: modelsChanged,
      beforeCount: existingModelIds.length,
      afterCount: nextModelIds.length,
      added: addedModelIds,
      removed: removedModelIds,
    },
    apiKeyAction: willPatchApiKey ? 'overwrite' : 'keep',
    inferredPrimary: inferredPrimary || null,
  }
})

const createChangePreview = computed(() => {
  const providerId = normalizeProviderId(createProviderForm.id)
  const providerExists = !!providerMap.value[providerId]
  const api = createProviderForm.api
  const baseUrl = createProviderForm.baseUrl.trim()
  const apiKey = createProviderForm.apiKey.trim()
  const modelIds = pickProviderModelIds(createCurrentModelIds.value)
  const hasApiKey = !!apiKey

  const warnings: string[] = []
  const missingRequired: string[] = []
  const patchPaths: string[] = []

  if (!providerId) {
    warnings.push(t('pages.models.preview.warnings.providerIdMissing'))
    missingRequired.push(t('pages.models.fields.providerId'))
  } else {
    patchPaths.push(
      `models.providers.${providerId}.api`,
      `models.providers.${providerId}.baseUrl`,
      `models.providers.${providerId}.apiKey`,
      `models.providers.${providerId}.models`
    )
  }

  if (providerExists) {
    warnings.push(t('pages.models.preview.warnings.providerIdExists'))
  }

  if (baseUrl) {
  } else {
    warnings.push(t('pages.models.preview.warnings.baseUrlMissing'))
    missingRequired.push(t('pages.models.fields.baseUrl'))
  }

  if (modelIds.length === 0) {
    warnings.push(t('pages.models.preview.warnings.modelListMissing'))
    missingRequired.push(t('pages.models.fields.models'))
  }

  if (hasApiKey) {
  } else {
    warnings.push(t('pages.models.preview.warnings.apiKeyMissing'))
    missingRequired.push(t('pages.models.fields.apiKey'))
  }

  const currentPrimary = primaryModel.value.trim() || configStore.config?.agents?.defaults?.model?.primary || ''
  let inferredPrimary = ''
  if (createProviderForm.pendingPrimaryModel) {
    inferredPrimary = createProviderForm.pendingPrimaryModel
    patchPaths.push('agents.defaults.model.primary')
  } else if (!currentPrimary && providerId && modelIds[0]) {
    inferredPrimary = `${providerId}/${modelIds[0]}`
    patchPaths.push('agents.defaults.model.primary')
  }

  if (patchPaths.length > 0) {
    patchPaths.unshift('models.mode')
  }

  const ready =
    !!providerId &&
    !providerExists &&
    !!baseUrl &&
    hasApiKey &&
    modelIds.length > 0

  return {
    ready,
    warnings,
    missingRequired,
    patchPaths,
    providerId,
    providerExists,
    api,
    baseUrl: baseUrl || '-',
    modelIds,
    hasApiKey,
    inferredPrimary: inferredPrimary || null,
  }
})
const saveConfirmTitle = computed(() =>
  confirmActionType.value === 'edit'
    ? t('pages.models.confirm.titleEdit')
    : t('pages.models.confirm.titleCreate')
)
const saveConfirmButtonLabel = computed(() =>
  confirmActionType.value === 'edit'
    ? t('pages.models.confirm.buttonEdit')
    : t('pages.models.confirm.buttonCreate')
)
const canConfirmSave = computed(() =>
  confirmActionType.value === 'edit'
    ? !!editChangePreview.value?.hasChanges
    : createChangePreview.value.ready
)
const selectedProviderSummary = computed(() =>
  providerSummaries.value.find((item) => item.id === selectedProviderId.value) || null
)
const providerStats = computed(() => {
  const providerCount = providerSummaries.value.length
  const modelCount = providerSummaries.value.reduce((total, item) => total + item.modelIds.length, 0)
  return {
    providerCount,
    modelCount,
    selectedProvider: selectedProviderSummary.value?.id || '-',
  }
})

const primaryModelDisplay = computed(() => {
  const current = primaryModel.value.trim()
  if (current) return current
  const fromConfig = configStore.config?.models?.primary || configStore.config?.agents?.defaults?.model?.primary || ''
  return fromConfig || '-'
})

const currentPrimaryProviderId = computed(() => {
  const resolvedModelRef = resolveModelRefFromConfigValue(primaryModelDisplay.value)
  const parsed = resolvedModelRef ? splitModelRef(resolvedModelRef) : null
  return parsed?.providerId || ''
})

const providerColumns = computed<DataTableColumns<ProviderSummary>>(() => [
  {
    title: t('pages.models.table.providers.provider'),
    key: 'id',
    width: 136,
    ellipsis: { tooltip: true },
    render(row) {
      return h('code', { style: 'font-size: 12px;' }, row.id)
    },
  },
  {
    title: t('pages.models.table.providers.protocol'),
    key: 'api',
    width: 132,
    ellipsis: { tooltip: true },
    render(row) {
      return row.api || '-'
    },
  },
  {
    title: t('pages.models.table.providers.baseUrl'),
    key: 'baseUrl',
    width: 256,
    ellipsis: { tooltip: true },
    render(row) {
      return row.baseUrl || '-'
    },
  },
  {
    title: t('pages.models.table.providers.models'),
    key: 'models',
    width: 220,
    ellipsis: { tooltip: true },
    render(row) {
      return row.modelIds.join(', ') || '-'
    },
  },
  {
    title: t('pages.models.table.providers.actions'),
    key: 'actions',
    width: 320,
    align: 'right',
    titleAlign: 'right',
    render(row) {
      const isPrimaryProvider = row.id === currentPrimaryProviderId.value
      const isManagedProvider = managedProviderIdSet.value.has(row.id)
      return h('div', {
        class: 'models-provider-actions-wrap',
        style: {
          width: '100%',
          display: 'flex',
          justifyContent: 'flex-end',
        },
      }, [
        h(
          NSpace,
          {
            size: 6,
            wrap: false,
            justify: 'end',
            class: 'models-provider-actions',
            style: {
              width: '100%',
              justifyContent: 'flex-end',
            },
          },
          () => [
            ...(isManagedProvider
              ? [
                  h(
                    NButton,
                    {
                      size: 'small',
                      type: 'info',
                      secondary: true,
                      strong: true,
                      class: 'models-action-btn models-action-btn--edit',
                      onClick: () => handleLoadProvider(row.id)
                    },
                    {
                      icon: () => h(NIcon, { component: CreateOutline }),
                      default: () => t('common.edit'),
                    }
                  ),
                ]
              : []),
            h(
              NButton,
              {
                size: 'small',
                type: isPrimaryProvider ? 'default' : 'success',
                secondary: true,
                strong: true,
                class: isPrimaryProvider
                  ? 'models-action-btn models-action-btn--active'
                  : 'models-action-btn models-action-btn--primary',
                disabled: isPrimaryProvider,
                onClick: () => handleUseProviderAsPrimary(row.id, row.modelIds),
              },
              {
                icon: () => h(NIcon, { component: CheckmarkCircleOutline }),
                default: () => (isPrimaryProvider ? t('pages.models.default.active') : t('pages.models.default.set')),
              }
            ),
            ...(isManagedProvider
              ? [
                  h(
                    NPopconfirm,
                    {
                      onPositiveClick: () => handleDeleteProvider(row.id),
                      positiveText: t('common.delete'),
                      negativeText: t('common.cancel'),
                    },
                    {
                      trigger: () =>
                        h(
                          NButton,
                          {
                            size: 'small',
                            type: 'error',
                            secondary: true,
                            strong: true,
                            class: 'models-action-btn models-action-btn--delete',
                            disabled: isPrimaryProvider,
                            onClick: (e: MouseEvent) => e.stopPropagation(),
                          },
                          {
                            icon: () => h(NIcon, { component: TrashOutline }),
                            default: () => t('common.delete'),
                          }
                        ),
                      default: () =>
                        isPrimaryProvider
                          ? t('pages.models.confirm.deleteDefaultProviderBlocked')
                          : t('pages.models.confirm.deleteProvider', { id: row.id }),
                    }
                  ),
                ]
              : []),
          ]
        ),
      ])
    },
  },
])

function providerRowProps(row: ProviderSummary) {
  const isManagedProvider = managedProviderIdSet.value.has(row.id)
  const active = row.id === selectedProviderId.value
  if (!isManagedProvider) {
    return {
      style: active ? 'cursor: default; background: rgba(32, 128, 240, 0.08);' : 'cursor: default;',
    }
  }
  return {
    style: active ? 'cursor: pointer; background: rgba(32, 128, 240, 0.08);' : 'cursor: pointer;',
    onClick: () => handleLoadProvider(row.id),
  }
}

watch(
  () => configStore.config,
  (config) => {
    if (!config) return
    primaryModel.value = config.models?.primary || config.agents?.defaults?.model?.primary || ''

    const allProviders = providerEntries.value.map((item) => item.id)
    if (selectedProviderId.value && !allProviders.includes(selectedProviderId.value)) {
      selectedProviderId.value = ''
    }
    const firstProvider = allProviders[0]
    if (!selectedProviderId.value && firstProvider) {
      selectedProviderId.value = firstProvider
      loadProviderForm(firstProvider)
    }
  },
  { immediate: true }
)

watch(selectedProviderId, (value) => {
  if (!value) {
    resetEditorForm()
    return
  }
  loadProviderForm(value)
})

onMounted(async () => {
  await configStore.fetchConfig()
})


function resetEditorForm() {
  providerForm.id = ''
  providerForm.api = 'openai-completions'
  providerForm.baseUrl = ''
  providerForm.apiKey = ''
  providerForm.models = []
  providerForm.pendingPrimaryModel = ''
}

function resetCreateProviderForm() {
  createProviderForm.id = ''
  createProviderForm.api = 'openai-completions'
  createProviderForm.baseUrl = ''
  createProviderForm.apiKey = ''
  createProviderForm.models = []
  createProviderForm.pendingPrimaryModel = ''
}

function loadProviderForm(providerId: string) {
  const provider = providerMap.value[providerId]

  providerForm.id = providerId
  providerForm.api = readProviderText(provider, ['api', 'protocol', 'format']) || 'openai-completions'
  providerForm.baseUrl = readProviderText(provider, ['baseUrl', 'baseURL', 'base_url', 'url', 'endpoint']) || ''
  providerForm.apiKey = ''

  const models = readProviderModels(provider)
  providerForm.models = models.map(m => ({
    id: m.id || '',
    input: normalizeModelInputTypeSelection(m.input as ModelInputType[] || ['text']),
    raw: m.raw,
  })).filter(m => m.id)
}

function handleNewProvider() {
  resetCreateProviderForm()
  createActiveTab.value = 'basic'
  showCreateProviderModal.value = true
}

function openSaveConfirm(action: 'edit' | 'create') {
  confirmActionType.value = action
  showSaveConfirmModal.value = true
}

function handleLoadProvider(providerId: string) {
  selectedProviderId.value = providerId
  editActiveTab.value = 'basic'
  showEditProviderModal.value = true
}

function handleCloseEditProviderModal() {
  showEditProviderModal.value = false
  editActiveTab.value = 'basic'
}

async function savePrimaryModel(targetInput: string): Promise<void> {
  const target = targetInput.trim()
  if (!target) {
    message.warning(t('pages.models.messages.primaryModelRequired'))
    return
  }

  const parsedTarget = splitModelRef(target)
  const mergedDefaultsModels = parsedTarget
    ? buildMergedDefaultsModelsCatalog([
        {
          modelRef: `${parsedTarget.providerId}/${parsedTarget.modelId}`,
          alias: parsedTarget.modelId,
        },
      ], configStore.config, {
        createWhenMissing: true,
      })
    : null

  const patches: ConfigPatch[] = [
    { path: 'agents.defaults.model.primary', value: target },
  ]
  if (mergedDefaultsModels) {
    patches.push({ path: 'agents.defaults.models', value: mergedDefaultsModels })
  }

  try {
    await configStore.patchConfig(patches)
    primaryModel.value = target
    message.success(t('pages.models.messages.primaryModelSaved', { model: target }))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.saveFailed'))
  }
}

async function handleUseProviderAsPrimary(providerId: string, modelIds: string[]) {
  if (modelIds.length === 0) {
    message.warning(t('pages.models.messages.noModelsForProvider'))
    return
  }
  const primary = `${providerId}/${modelIds[0]}`
  await savePrimaryModel(primary)
}

function isCurrentPrimaryModel(providerId: string, modelId: string): boolean {
  if (!providerId || !modelId) return false
  const modelRef = `${providerId}/${modelId}`
  const currentPrimary = primaryModel.value.trim() || configStore.config?.agents?.defaults?.model?.primary || ''
  return currentPrimary === modelRef
}

function isPendingPrimaryModel(formType: 'edit' | 'create', providerId: string, modelId: string): boolean {
  if (!providerId || !modelId) return false
  const modelRef = `${providerId}/${modelId}`
  if (formType === 'edit') {
    return providerForm.pendingPrimaryModel === modelRef
  }
  return createProviderForm.pendingPrimaryModel === modelRef
}

function setAsPendingPrimaryModel(formType: 'edit' | 'create', providerId: string, modelId: string) {
  if (!providerId || !modelId) return
  const modelRef = `${providerId}/${modelId}`
  if (formType === 'edit') {
    providerForm.pendingPrimaryModel = modelRef
  } else {
    createProviderForm.pendingPrimaryModel = modelRef
  }
}

function getPrimaryModelStatus(formType: 'edit' | 'create', providerId: string, modelId: string): 'current' | 'pending' | 'none' {
  if (isCurrentPrimaryModel(providerId, modelId)) return 'current'
  if (isPendingPrimaryModel(formType, providerId, modelId)) return 'pending'
  return 'none'
}

async function handleDeleteProvider(providerIdInput: string): Promise<void> {
  const providerId = normalizeProviderId(providerIdInput)
  if (!providerId) return

  if (providerId === currentPrimaryProviderId.value) {
    message.warning(t('pages.models.messages.deleteDefaultProviderBlocked'))
    return
  }

  if (!providerMap.value[providerId]) {
    message.warning(t('pages.models.messages.deleteWhitelistProviderBlocked'))
    return
  }

  await configStore.fetchConfig()
  const currentConfig = configStore.config
  if (!currentConfig) {
    message.error('Config not loaded')
    return
  }

  const allProviders = currentConfig.models?.providers || {}
  const newProviders: Record<string, ModelProviderConfig> = { ...allProviders }
  delete newProviders[providerId]

  const existingDefaultsModels = currentConfig.agents?.defaults?.models || {}
  const newDefaultsModels: Record<string, { alias?: string }> = {}
  
  for (const [modelRef, entry] of Object.entries(existingDefaultsModels)) {
    if (!modelRef.startsWith(`${providerId}/`)) {
      newDefaultsModels[modelRef] = entry as { alias?: string }
    }
  }

  const newConfig: OpenClawConfig = {
    ...currentConfig,
    models: {
      ...currentConfig.models,
      mode: 'replace',
      providers: newProviders,
    },
    agents: {
      ...currentConfig.agents,
      defaults: {
        ...currentConfig.agents?.defaults,
        models: newDefaultsModels,
      },
    },
  }

  try {
    await wsStore.rpc.setConfig(newConfig)
    await configStore.fetchConfig()
    if (selectedProviderId.value === providerId) {
      selectedProviderId.value = ''
    }
    if (currentEditingProviderId.value === providerId) {
      showEditProviderModal.value = false
    }
    message.success(t('pages.models.messages.providerDeleted', { id: providerId }))
  } catch (error) {
    message.error(t('pages.models.messages.saveFailed', { reason: error instanceof Error ? error.message : String(error) }))
  }
}

async function handleSaveProvider(confirmed = false) {
  const providerId = normalizeProviderId(providerForm.id)
  const baseUrl = providerForm.baseUrl.trim()
  const apiKey = providerForm.apiKey.trim()
  const models = providerForm.models
  const existingProvider = providerMap.value[providerId]
  const existingModelIds = readProviderModelIds(existingProvider)
  const finalModelIds = pickProviderModelIds(models.length > 0 ? models.map(m => m.id) : existingModelIds)
  const maskedKey = /^[*•]+$/.test(apiKey)
  const shouldPatchApiKey = !!apiKey && !maskedKey

  if (!existingProvider) {
    message.warning(t('pages.models.messages.selectProviderToEdit'))
    return
  }
  if (!editChangePreview.value?.hasChanges) {
    message.info(t('pages.models.messages.noConfigChanges'))
    return
  }
  if (!confirmed) {
    openSaveConfirm('edit')
    return
  }
  if (!providerId) {
    message.warning(t('pages.models.validation.providerIdRequired'))
    return
  }
  if (!/^[a-z0-9_-]+$/.test(providerId)) {
    message.warning(t('pages.models.validation.providerIdInvalid'))
    return
  }
  if (!baseUrl) {
    message.warning(t('pages.models.validation.baseUrlRequired'))
    return
  }
  if (finalModelIds.length === 0) {
    message.warning(t('pages.models.validation.modelsRequired'))
    return
  }

  const modelsValue = models.map((m) => {
    const base: Record<string, unknown> = {
      id: m.id,
      name: m.id,
      input: [...m.input],
    }
    if (m.raw && typeof m.raw === 'object') {
      const merged = { ...m.raw }
      merged.id = m.id
      merged.name = m.id
      merged.input = [...m.input]
      return merged
    }
    return base
  })
  const fullProviderValue: Record<string, unknown> = {
    api: providerForm.api,
    baseUrl,
    models: modelsValue,
  }
  if (shouldPatchApiKey) {
    fullProviderValue.apiKey = apiKey
  } else if ((existingProvider as Record<string, unknown>)?.apiKey) {
    fullProviderValue.apiKey = (existingProvider as Record<string, unknown>).apiKey
  }
  
  await configStore.fetchConfig()
  const currentConfig = configStore.config
  if (!currentConfig) {
    message.error('Config not loaded')
    return
  }
  
  const allProviders = currentConfig.models?.providers || {}
  const newProviders: Record<string, unknown> = {
    ...allProviders,
    [providerId]: fullProviderValue,
  }
  
  const newConfig: OpenClawConfig = {
    ...currentConfig,
    models: {
      ...currentConfig.models,
      mode: 'replace',
      providers: newProviders as Record<string, ModelProviderConfig>,
    },
  }
  
  const existingDefaultsModels = currentConfig.agents?.defaults?.models || {}
  const newDefaultsModels: Record<string, { alias?: string }> = {}
  
  for (const [modelRef, entry] of Object.entries(existingDefaultsModels)) {
    if (!isModelRefFromProvider(modelRef, providerId)) {
      newDefaultsModels[modelRef] = entry
    }
  }
  
  for (const modelId of finalModelIds) {
    const modelRef = `${providerId}/${modelId}`
    const existingEntry = existingDefaultsModels[modelRef]
    newDefaultsModels[modelRef] = {
      alias: (existingEntry as { alias?: string })?.alias || modelId,
    }
  }
  
  newConfig.agents = {
    ...newConfig.agents,
    defaults: {
      ...newConfig.agents?.defaults,
      models: newDefaultsModels,
      model: {
        ...newConfig.agents?.defaults?.model,
      },
    },
  }
  
  const currentPrimary = (newConfig.agents?.defaults?.model as { primary?: string })?.primary || ''
  const currentPrimaryFromThisProvider = currentPrimary.startsWith(`${providerId}/`)
  const currentPrimaryExists = finalModelIds.some(id => `${providerId}/${id}` === currentPrimary)
  
  if (providerForm.pendingPrimaryModel) {
    ;(newConfig.agents!.defaults!.model as { primary?: string }).primary = providerForm.pendingPrimaryModel
  } else if (currentPrimaryFromThisProvider && !currentPrimaryExists) {
    if (finalModelIds[0]) {
      ;(newConfig.agents!.defaults!.model as { primary?: string }).primary = `${providerId}/${finalModelIds[0]}`
    }
  }
  
  try {
    await wsStore.rpc.setConfig(newConfig)
    showSaveConfirmModal.value = false
    showEditProviderModal.value = false
    await configStore.fetchConfig()
    selectedProviderId.value = providerId
    message.success(t('pages.models.messages.providerSaved'))
  } catch (error) {
    message.error(t('pages.models.messages.saveFailed', { reason: error instanceof Error ? error.message : String(error) }))
  }
  return
}

async function handleCreateProvider(confirmed = false) {
  const providerId = normalizeProviderId(createProviderForm.id)
  const baseUrl = createProviderForm.baseUrl.trim()
  const apiKey = createProviderForm.apiKey.trim()
  const models = createProviderForm.models
  const modelIds = pickProviderModelIds(models.map(m => m.id))

  if (!providerId) {
    message.warning(t('pages.models.validation.providerIdRequired'))
    return
  }
  if (!/^[a-z0-9_-]+$/.test(providerId)) {
    message.warning(t('pages.models.validation.providerIdInvalid'))
    return
  }
  if (providerMap.value[providerId]) {
    message.warning(t('pages.models.validation.providerIdExists'))
    return
  }
  if (!baseUrl) {
    message.warning(t('pages.models.validation.baseUrlRequired'))
    return
  }
  if (!apiKey) {
    message.warning(t('pages.models.validation.apiKeyRequiredForCreate'))
    return
  }
  if (modelIds.length === 0) {
    message.warning(t('pages.models.validation.modelsRequired'))
    return
  }
  if (!confirmed) {
    openSaveConfirm('create')
    return
  }

  const modelsValue = models.map((m) => ({ id: m.id, name: m.id, input: [...m.input] }))
  
  const fullProviderValue: Record<string, unknown> = {
    api: createProviderForm.api,
    baseUrl,
    models: modelsValue,
    apiKey,
  }
  
  await configStore.fetchConfig()
  const currentConfig = configStore.config
  if (!currentConfig) {
    message.error('Config not loaded')
    return
  }
  
  const allProviders = currentConfig.models?.providers || {}
  const newProviders: Record<string, unknown> = {
    ...allProviders,
    [providerId]: fullProviderValue,
  }
  
  const newConfig: OpenClawConfig = {
    ...currentConfig,
    models: {
      ...currentConfig.models,
      mode: 'replace',
      providers: newProviders as Record<string, ModelProviderConfig>,
    },
  }
  
  const existingDefaultsModels = currentConfig.agents?.defaults?.models || {}
  const newDefaultsModels: Record<string, { alias?: string }> = {}
  
  for (const [modelRef, entry] of Object.entries(existingDefaultsModels)) {
    newDefaultsModels[modelRef] = entry as { alias?: string }
  }
  
  for (const modelId of modelIds) {
    const modelRef = `${providerId}/${modelId}`
    newDefaultsModels[modelRef] = {
      alias: modelId,
    }
  }
  
  newConfig.agents = {
    ...newConfig.agents,
    defaults: {
      ...newConfig.agents?.defaults,
      models: newDefaultsModels,
      model: {
        ...newConfig.agents?.defaults?.model,
      },
    },
  }
  
  const currentPrimary = primaryModel.value.trim() || configStore.config?.agents?.defaults?.model?.primary || ''
  if (createProviderForm.pendingPrimaryModel) {
    ;(newConfig.agents!.defaults!.model as { primary?: string }).primary = createProviderForm.pendingPrimaryModel
  } else if (!currentPrimary && modelIds[0]) {
    ;(newConfig.agents!.defaults!.model as { primary?: string }).primary = `${providerId}/${modelIds[0]}`
  }

  try {
    await wsStore.rpc.setConfig(newConfig)
    showSaveConfirmModal.value = false
    showCreateProviderModal.value = false
    await configStore.fetchConfig()
    selectedProviderId.value = providerId
    loadProviderForm(providerId)
    message.success(t('pages.models.messages.providerCreated'))
  } catch (error) {
    message.error(t('pages.models.messages.saveFailed', { reason: error instanceof Error ? error.message : String(error) }))
  }
}

async function handleQuickProviderSetup(key: QuickProviderKey) {
  if (quickProviderConfiguredMap.value[key]) {
    return
  }
  const preset = QUICK_PROVIDER_PRESETS[key]
  const apiKey = quickProviderApiKeys[key].trim()
  if (!apiKey) {
    message.warning(t('pages.models.quick.messages.keyRequired'))
    return
  }

  quickProviderSaving[key] = true
  try {
    const providerId = normalizeProviderId(preset.providerId)
    const providerPath = `models.providers.${providerId}`
    
    // 为阿里云百炼提供完整模型列表
    let modelIds: string[]
    let modelsConfig: ModelProviderModel[]
    
    if (key === 'bailian') {
      // 阿里云百炼完整模型列表
      const bailianModels = [
        { id: 'qwen3.5-plus', name: 'qwen3.5-plus', reasoning: false, input: ['text', 'image'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 65536, compat: { thinkingFormat: 'qwen' } },
        { id: 'qwen3-max-2026-01-23', name: 'qwen3-max-2026-01-23', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 65536, compat: { thinkingFormat: 'qwen' } },
        { id: 'qwen3-coder-next', name: 'qwen3-coder-next', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 65536 },
        { id: 'qwen3-coder-plus', name: 'qwen3-coder-plus', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 1000000, maxTokens: 65536 },
        { id: 'MiniMax-M2.5', name: 'MiniMax-M2.5', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 196608, maxTokens: 32768 },
        { id: 'glm-5', name: 'glm-5', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 202752, maxTokens: 16384, compat: { thinkingFormat: 'qwen' } },
        { id: 'glm-4.7', name: 'glm-4.7', reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 202752, maxTokens: 16384, compat: { thinkingFormat: 'qwen' } },
        { id: 'kimi-k2.5', name: 'kimi-k2.5', reasoning: false, input: ['text', 'image'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 262144, maxTokens: 32768, compat: { thinkingFormat: 'qwen' } },
      ]
      modelIds = bailianModels.map(model => model.id)
      modelsConfig = bailianModels
    } else {
      // 其他提供商保持现有行为
      modelIds = [preset.modelId]
      modelsConfig = modelIds.map((id) => ({ id, name: preset.modelName || id, input: [...preset.input] }))
    }

    const patches: ConfigPatch[] = [
      { path: 'models.mode', value: 'merge' },
      { path: `${providerPath}.api`, value: preset.api },
      { path: `${providerPath}.baseUrl`, value: preset.baseUrl },
      { path: `${providerPath}.apiKey`, value: apiKey },
      {
        path: `${providerPath}.models`,
        value: modelsConfig,
      },
    ]

    const providerPrefix = providerPathPrefixMap.value[providerId] || 'models.providers'
    if (providerPrefix === 'models') {
      patches.push({ path: `models.${providerId}`, value: null })
    }

    const mergedDefaultsModels = buildDefaultsModelsCatalogSyncedForProvider(providerId, modelIds, configStore.config, {
      createWhenMissing: true,
    })
    if (mergedDefaultsModels) {
      patches.push({ path: 'agents.defaults.models', value: mergedDefaultsModels })
    }

    const defaultsCatalogSnapshot = readExistingDefaultsModelsCatalog(configStore.config)
    patches.push(
      ...buildAgentModelReferenceSyncPatches(providerId, modelIds, defaultsCatalogSnapshot.catalog, configStore.config),
      ...buildLegacyModelsReferenceSyncPatches(providerId, modelIds, defaultsCatalogSnapshot.catalog, configStore.config),
    )

    const currentPrimary = primaryModel.value.trim() || configStore.config?.agents?.defaults?.model?.primary || ''
    if (!currentPrimary) {
      patches.push({ path: 'agents.defaults.model.primary', value: `${providerId}/${preset.modelId}` })
    }

    const finalPatches = dedupeConfigPatchesByPath(patches)
    await configStore.patchConfig(finalPatches)
    quickProviderApiKeys[key] = ''
    selectedProviderId.value = providerId
    loadProviderForm(providerId)
    message.success(t('pages.models.quick.messages.saved', {
      provider: t(`pages.models.quick.providers.${key}.name`)
    }))
  } catch (error) {
    message.error(error instanceof Error ? error.message : t('common.saveFailed'))
  } finally {
    quickProviderSaving[key] = false
  }
}

async function handleConfirmSave() {
  if (confirmActionType.value === 'edit') {
    await handleSaveProvider(true)
    return
  }
  await handleCreateProvider(true)
}

function handleSaveProviderClick() {
  void handleSaveProvider()
}

function handleCreateProviderClick() {
  void handleCreateProvider()
}
</script>

<template>
  <div class="models-page">
    <NCard class="models-overview-card" :bordered="false">
      <template #header>
        <div class="models-overview-title">{{ t('pages.models.overview.title') }}</div>
      </template>
      <template #header-extra>
        <NButton size="small" :loading="configStore.loading" @click="configStore.fetchConfig()">
          <template #icon><NIcon :component="RefreshOutline" /></template>
          {{ t('pages.models.actions.refreshConfig') }}
        </NButton>
      </template>

      <NAlert type="info" :bordered="false" style="margin-bottom: 12px;">
        {{ t('pages.models.overview.hintPrefix') }}<code>provider/model</code>{{ t('pages.models.overview.hintMiddle') }}<code>models.providers</code>{{ t('pages.models.overview.hintSuffix') }}
      </NAlert>

      <NAlert v-if="configStore.lastError" type="error" :bordered="false" style="margin-bottom: 12px;">
        {{ configStore.lastError }}
      </NAlert>

      <div class="models-overview-metrics">
        <div class="models-metric-item">
          <NText depth="3">{{ t('pages.models.overview.metrics.providers') }}</NText>
          <div class="models-metric-value">{{ providerStats.providerCount }}</div>
        </div>
        <div class="models-metric-item">
          <NText depth="3">{{ t('pages.models.overview.metrics.modelRefs') }}</NText>
          <div class="models-metric-value">{{ providerStats.modelCount }}</div>
        </div>
        <div class="models-metric-item">
          <NText depth="3">{{ t('pages.models.overview.metrics.editing') }}</NText>
          <div class="models-metric-value">{{ providerStats.selectedProvider }}</div>
        </div>
        <div class="models-metric-item">
          <NText depth="3">{{ t('pages.models.overview.metrics.primaryModel') }}</NText>
          <div class="models-metric-value models-metric-code">{{ primaryModelDisplay }}</div>
        </div>
      </div>

    </NCard>

    <NCard :title="t('pages.models.workbench.title')" class="models-workbench-card">
      <NGrid cols="1 xl:12" responsive="screen" :x-gap="16" :y-gap="16">
        <NGridItem class="models-workbench-item" span="1 xl:12">
          <div class="models-panel">
            <NSpace justify="space-between" align="center" :size="8" class="models-panel-toolbar">
              <NInput
                v-model:value="providerSearch"
                size="small"
                :placeholder="t('pages.models.workbench.searchPlaceholder')"
                style="width: 100%; max-width: 340px;"
              />
              <NButton size="small" type="primary" @click="handleNewProvider">
                <template #icon><NIcon :component="AddOutline" /></template>
                {{ t('pages.models.actions.createProvider') }}
              </NButton>
            </NSpace>

            <NDataTable
              class="models-provider-table"
              :columns="providerColumns"
              :data="filteredProviderSummaries"
              :loading="configStore.loading"
              :bordered="false"
              :pagination="{ pageSize: 8 }"
              :row-key="(row: ProviderSummary) => row.id"
              :row-props="providerRowProps"
              striped
            />

            <NEmpty
              v-if="!configStore.loading && providerSummaries.length === 0"
              :description="t('pages.models.workbench.empty')"
              class="models-empty"
            >
              <template #extra>
                <NText depth="3">{{ t('pages.models.workbench.emptyHint') }}</NText>
              </template>
            </NEmpty>
          </div>
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard :title="t('pages.models.quick.title')" class="models-quick-card">
      <NAlert type="info" :bordered="false" style="margin-bottom: 12px;">
        {{ t('pages.models.quick.hint') }}
      </NAlert>
      <div class="models-quick-grid">
        <div
          v-for="item in quickProviderList"
          :key="`quick-provider-${item.key}`"
          class="models-quick-item"
        >
          <div class="models-quick-item-header">
            <NText strong>{{ t(`pages.models.quick.providers.${item.key}.name`) }}</NText>
            <NSpace :size="6" align="center">
              <NTag v-if="quickProviderConfiguredMap[item.key]" size="small" type="primary" :bordered="false">
                {{ t('pages.models.quick.configuredTag') }}
              </NTag>
              <NTag size="small" type="success" :bordered="false">
                {{ t('pages.models.quick.latestTag') }}
              </NTag>
            </NSpace>
          </div>
          <NSpace vertical :size="6">
            <NText depth="3" class="models-quick-meta">
              {{ t('pages.models.quick.providerId') }}：<code>{{ item.providerId }}</code>
            </NText>
            <NText depth="3" class="models-quick-meta">
              {{ t('pages.models.quick.defaultModel') }}：<code>{{ item.modelId }}</code>
            </NText>
            <NText depth="3" class="models-quick-meta">
              {{ t('pages.models.quick.endpoint') }}：<code>{{ item.baseUrl }}</code>
            </NText>
            <a
              class="models-quick-doc-link"
              :href="item.docsUrl"
              target="_blank"
              rel="noreferrer"
            >
              {{ t('pages.models.quick.docs') }}
            </a>
          </NSpace>
          <NSpace vertical :size="8" style="margin-top: 10px;">
            <NInput
              v-model:value="quickProviderApiKeys[item.key]"
              type="password"
              show-password-on="click"
              :placeholder="t('pages.models.quick.keyPlaceholder')"
            />
            <NButton
              type="primary"
              :loading="quickProviderSaving[item.key]"
              :disabled="quickProviderConfiguredMap[item.key]"
              @click="handleQuickProviderSetup(item.key)"
            >
              {{ quickProviderConfiguredMap[item.key]
                ? t('pages.models.quick.configuredTag')
                : t('pages.models.quick.action') }}
            </NButton>
          </NSpace>
        </div>
      </div>
    </NCard>

    <NModal
      v-model:show="showEditProviderModal"
      preset="card"
      :title="providerEditorTitle"
      style="max-width: 760px; width: 92vw;"
      :mask-closable="false"
    >
      <template v-if="editingExistingProvider">
        <NSpace vertical :size="12">
          <NSpace v-if="selectedProviderSummary" :size="6" style="flex-wrap: wrap;">
            <NTag size="small" :bordered="false">
              {{ t('pages.models.editor.modelsCount', { count: selectedProviderSummary.modelIds.length }) }}
            </NTag>
          </NSpace>

          <NTabs v-model:value="editActiveTab" type="line" animated>
            <NTabPane name="basic" :tab="t('pages.models.tabs.basic')">
              <NForm label-placement="left" label-width="100">
                <NFormItem :label="t('pages.models.form.providerId')">
                  <NInput
                    v-model:value="providerForm.id"
                    :disabled="true"
                    :placeholder="t('pages.models.form.providerIdPlaceholder')"
                  />
                </NFormItem>
                <NFormItem :label="t('pages.models.form.apiProtocol')">
                  <NSelect v-model:value="providerForm.api" :options="apiOptions" />
                </NFormItem>
                <NFormItem :label="t('pages.models.form.baseUrl')">
                  <NInput v-model:value="providerForm.baseUrl" :placeholder="t('pages.models.form.baseUrlPlaceholder')" />
                </NFormItem>
                <NFormItem :label="t('pages.models.form.apiKey')">
                  <NSpace vertical :size="6" style="width: 100%;">
                    <NInput
                      v-model:value="providerForm.apiKey"
                      type="password"
                      show-password-on="click"
                      :placeholder="apiKeyPlaceholder"
                    />
                    <NText depth="3" style="font-size: 12px;">
                      {{ t('pages.models.form.apiKeyHint') }}
                    </NText>
                  </NSpace>
                </NFormItem>
                <NFormItem :label="t('pages.models.form.apiKeyStatus')">
                  <NTag size="small" :bordered="false" :type="selectedProviderHasKey ? 'success' : 'default'">
                    {{ selectedProviderHasKey ? t('pages.models.form.apiKeyStatusConfigured') : t('pages.models.form.apiKeyStatusNotConfigured') }}
                  </NTag>
                </NFormItem>
                <NFormItem>
                  <NSpace justify="end" style="width: 100%;">
                    <NButton @click="editActiveTab = 'models'">{{ t('pages.models.actions.nextToModels') }}</NButton>
                  </NSpace>
                </NFormItem>
              </NForm>
            </NTabPane>

            <NTabPane name="models" :tab="t('pages.models.tabs.models')">
              <NForm label-placement="left" label-width="100">
                <NFormItem :label="t('pages.models.form.models')">
                  <NSpace vertical :size="8" style="width: 100%;">
                    <NButton
                      size="small"
                      type="primary"
                      dashed
                      @click="providerForm.models.push({ id: '', input: ['text'] })"
                    >
                      {{ t('pages.models.form.addModel') }}
                    </NButton>
                    <div
                      v-for="(model, index) in providerForm.models"
                      :key="index"
                      style="display: flex; gap: 8px; align-items: center; width: 100%;"
                    >
                      <NInput
                        v-model:value="model.id"
                        :placeholder="t('pages.models.form.modelIdPlaceholder')"
                        style="flex: 1;"
                      />
                      <NSelect
                        v-model:value="model.input"
                        :options="modelInputTypeOptions"
                        multiple
                        :placeholder="t('pages.models.form.modelInputTypesPlaceholder')"
                        style="width: 160px;"
                      />
                      <NButton
                        size="small"
                        :type="getPrimaryModelStatus('edit', providerForm.id, model.id) === 'current' ? 'success' : getPrimaryModelStatus('edit', providerForm.id, model.id) === 'pending' ? 'warning' : 'default'"
                        :disabled="!model.id || getPrimaryModelStatus('edit', providerForm.id, model.id) === 'current'"
                        @click="setAsPendingPrimaryModel('edit', providerForm.id, model.id)"
                      >
                        {{ getPrimaryModelStatus('edit', providerForm.id, model.id) === 'current' ? t('pages.models.form.isDefault') : getPrimaryModelStatus('edit', providerForm.id, model.id) === 'pending' ? t('pages.models.form.pendingDefault') : t('pages.models.form.setAsDefault') }}
                      </NButton>
                      <NButton
                        size="small"
                        quaternary
                        type="error"
                        @click="providerForm.models.splice(index, 1)"
                      >
                        <template #icon>
                          <NIcon><CloseOutline /></NIcon>
                        </template>
                      </NButton>
                    </div>
                    <NText depth="3" style="font-size: 12px;">
                      {{ t('pages.models.form.modelsHint') }}
                    </NText>
                  </NSpace>
                </NFormItem>
                <NFormItem>
                  <NSpace justify="end" style="width: 100%;">
                    <NSpace>
                      <NButton @click="editActiveTab = 'basic'">{{ t('pages.models.actions.prev') }}</NButton>
                      <NButton type="primary" @click="editActiveTab = 'preview'">{{ t('pages.models.actions.nextToPreview') }}</NButton>
                    </NSpace>
                  </NSpace>
                </NFormItem>
              </NForm>
            </NTabPane>

            <NTabPane name="preview" :tab="t('pages.models.tabs.preview')">
              <NSpace vertical :size="10">
                <div class="models-preview-grid">
                  <div class="models-preview-card" :class="{ 'is-changed': editChangePreview?.apiDiff.changed }">
                    <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.apiProtocol') }}</NText>
                    <div class="models-preview-diff">
                      <code>{{ editChangePreview?.apiDiff.before || '-' }}</code>
                      <span class="models-preview-arrow">→</span>
                      <code>{{ editChangePreview?.apiDiff.after || '-' }}</code>
                    </div>
                  </div>

                  <div class="models-preview-card" :class="{ 'is-changed': editChangePreview?.baseUrlDiff.changed }">
                    <NText depth="3" class="models-preview-label">Base URL</NText>
                    <div class="models-preview-diff models-preview-diff--block">
                      <code>{{ editChangePreview?.baseUrlDiff.before || '-' }}</code>
                      <span class="models-preview-arrow">→</span>
                      <code>{{ editChangePreview?.baseUrlDiff.after || '-' }}</code>
                    </div>
                  </div>

                  <div class="models-preview-card" :class="{ 'is-changed': editChangePreview?.modelDiff.changed }">
                    <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.models') }}</NText>
                    <div class="models-preview-diff">
                      <code>{{ editChangePreview?.modelDiff.beforeCount || 0 }}</code>
                      <span class="models-preview-arrow">→</span>
                      <code>{{ editChangePreview?.modelDiff.afterCount || 0 }}</code>
                    </div>
                  </div>

                  <div class="models-preview-card" :class="{ 'is-changed': editChangePreview?.apiKeyAction === 'overwrite' }">
                    <NText depth="3" class="models-preview-label">API Key</NText>
                    <NTag
                      size="small"
                      :type="editChangePreview?.apiKeyAction === 'overwrite' ? 'warning' : 'default'"
                      :bordered="false"
                    >
                      {{ editChangePreview?.apiKeyAction === 'overwrite'
                        ? t('pages.models.preview.apiKeyOverwrite')
                        : t('pages.models.preview.apiKeyKeep') }}
                    </NTag>
                  </div>

                  <div class="models-preview-card" :class="{ 'is-changed': !!editChangePreview?.inferredPrimary }">
                    <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.primaryModel') }}</NText>
                    <NTag size="small" :type="editChangePreview?.inferredPrimary ? 'warning' : 'default'" :bordered="false">
                      {{ editChangePreview?.inferredPrimary || t('pages.models.preview.unchanged') }}
                    </NTag>
                  </div>
                </div>

                <NCollapse v-if="editChangePreview?.modelDiff.changed">
                  <NCollapseItem
                    :title="t('pages.models.preview.modelDiffTitle', {
                      added: editChangePreview?.modelDiff.added.length || 0,
                      removed: editChangePreview?.modelDiff.removed.length || 0,
                    })"
                    name="edit-model-diff"
                  >
                    <NSpace vertical :size="8">
                      <div v-if="editChangePreview?.modelDiff.added.length">
                        <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.addedModels') }}</NText>
                        <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                          <NTag
                            v-for="id in editChangePreview?.modelDiff.added"
                            :key="`add-${id}`"
                            type="success"
                            size="small"
                            :bordered="false"
                          >
                            + {{ id }}
                          </NTag>
                        </NSpace>
                      </div>
                      <div v-if="editChangePreview?.modelDiff.removed.length">
                        <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.removedModels') }}</NText>
                        <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                          <NTag
                            v-for="id in editChangePreview?.modelDiff.removed"
                            :key="`remove-${id}`"
                            type="error"
                            size="small"
                            :bordered="false"
                          >
                            - {{ id }}
                          </NTag>
                        </NSpace>
                      </div>
                    </NSpace>
                  </NCollapseItem>
                </NCollapse>

                <div class="models-preview-paths">
                  <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.patchPaths') }}</NText>
                  <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                    <NTag
                      v-for="path in editChangePreview?.patchPaths || []"
                      :key="`edit-path-${path}`"
                      size="small"
                      :bordered="false"
                    >
                      {{ path }}
                    </NTag>
                  </NSpace>
                </div>

                <NAlert v-if="editChangePreview?.warnings.length" type="warning" :bordered="false">
                  <div v-for="(warning, index) in editChangePreview?.warnings" :key="index">
                    {{ warning }}
                  </div>
                </NAlert>

                <NAlert v-if="editChangePreview && !editChangePreview.hasChanges" type="info" :bordered="false">
                  {{ t('pages.models.preview.noChangesHint') }}
                </NAlert>

                <NSpace justify="space-between">
                  <NButton @click="editActiveTab = 'models'">{{ t('pages.models.actions.prev') }}</NButton>
                  <NButton
                    type="primary"
                    :loading="configStore.saving"
                    :disabled="!editChangePreview?.hasChanges"
                    @click="handleSaveProviderClick"
                  >
                    <template #icon><NIcon :component="SaveOutline" /></template>
                    {{ providerSubmitLabel }}
                  </NButton>
                </NSpace>
              </NSpace>
            </NTabPane>
          </NTabs>

          <NCollapse v-if="selectedProviderRawText">
            <NCollapseItem :title="t('pages.models.editor.rawConfigTitle')" name="provider-raw-json">
              <NCode :code="selectedProviderRawText" language="json" style="font-size: 12px;" />
            </NCollapseItem>
          </NCollapse>
        </NSpace>
      </template>

      <NEmpty v-else :description="t('pages.models.editor.empty')">
        <template #extra>
          <NButton size="small" type="primary" @click="handleNewProvider">
            <template #icon><NIcon :component="AddOutline" /></template>
            {{ t('pages.models.actions.createProvider') }}
          </NButton>
        </template>
      </NEmpty>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="handleCloseEditProviderModal">{{ t('common.cancel') }}</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal
      v-model:show="showCreateProviderModal"
      preset="card"
      :title="t('pages.models.createModal.title')"
      style="max-width: 720px; width: 92vw;"
      :mask-closable="false"
    >
      <NAlert type="default" :bordered="false" style="margin-bottom: 12px;">
        {{ t('pages.models.createModal.flowHint') }}
      </NAlert>

      <NTabs v-model:value="createActiveTab" type="line" animated>
        <NTabPane name="basic" :tab="t('pages.models.tabs.basic')">
          <NForm label-placement="left" label-width="100">
            <NFormItem :label="t('pages.models.form.providerId')">
              <NInput v-model:value="createProviderForm.id" :placeholder="t('pages.models.form.providerIdPlaceholder')" />
            </NFormItem>
            <NFormItem :label="t('pages.models.form.apiProtocol')">
              <NSelect v-model:value="createProviderForm.api" :options="apiOptions" />
            </NFormItem>
            <NFormItem :label="t('pages.models.form.baseUrl')">
              <NInput v-model:value="createProviderForm.baseUrl" :placeholder="t('pages.models.form.baseUrlPlaceholder')" />
            </NFormItem>
            <NFormItem :label="t('pages.models.form.apiKey')">
              <NInput
                v-model:value="createProviderForm.apiKey"
                type="password"
                show-password-on="click"
                :placeholder="t('pages.models.form.apiKeyPlaceholderCreateRequired')"
              />
            </NFormItem>
            <NFormItem>
              <NSpace justify="end" style="width: 100%;">
                <NButton type="primary" @click="createActiveTab = 'models'">{{ t('pages.models.actions.nextToModels') }}</NButton>
              </NSpace>
            </NFormItem>
          </NForm>
        </NTabPane>

        <NTabPane name="models" :tab="t('pages.models.tabs.models')">
          <NForm label-placement="left" label-width="100">
            <NFormItem :label="t('pages.models.form.models')">
              <NSpace vertical :size="8" style="width: 100%;">
                <NButton
                  size="small"
                  type="primary"
                  dashed
                  @click="createProviderForm.models.push({ id: '', input: ['text'] })"
                >
                  {{ t('pages.models.form.addModel') }}
                </NButton>
                <div
                  v-for="(model, index) in createProviderForm.models"
                  :key="index"
                  style="display: flex; gap: 8px; align-items: center; width: 100%;"
                >
                  <NInput
                    v-model:value="model.id"
                    :placeholder="t('pages.models.form.modelIdPlaceholder')"
                    style="flex: 1;"
                  />
                  <NSelect
                    v-model:value="model.input"
                    :options="modelInputTypeOptions"
                    multiple
                    :placeholder="t('pages.models.form.modelInputTypesPlaceholder')"
                    style="width: 160px;"
                  />
                  <NButton
                    size="small"
                    :type="getPrimaryModelStatus('create', createProviderForm.id, model.id) === 'current' ? 'success' : getPrimaryModelStatus('create', createProviderForm.id, model.id) === 'pending' ? 'warning' : 'default'"
                    :disabled="!model.id || getPrimaryModelStatus('create', createProviderForm.id, model.id) === 'current'"
                    @click="setAsPendingPrimaryModel('create', createProviderForm.id, model.id)"
                  >
                    {{ getPrimaryModelStatus('create', createProviderForm.id, model.id) === 'current' ? t('pages.models.form.isDefault') : getPrimaryModelStatus('create', createProviderForm.id, model.id) === 'pending' ? t('pages.models.form.pendingDefault') : t('pages.models.form.setAsDefault') }}
                  </NButton>
                  <NButton
                    size="small"
                    quaternary
                    type="error"
                    @click="createProviderForm.models.splice(index, 1)"
                  >
                    <template #icon>
                      <NIcon><CloseOutline /></NIcon>
                    </template>
                  </NButton>
                </div>
                <NText depth="3" style="font-size: 12px;">
                  {{ t('pages.models.form.modelsHint') }}
                </NText>
              </NSpace>
            </NFormItem>
            <NFormItem>
              <NSpace justify="space-between" style="width: 100%;">
                <NButton @click="createActiveTab = 'basic'">{{ t('pages.models.actions.prev') }}</NButton>
                <NSpace>
                  <NButton type="primary" @click="createActiveTab = 'preview'">{{ t('pages.models.actions.nextToPreview') }}</NButton>
                </NSpace>
              </NSpace>
            </NFormItem>
          </NForm>
        </NTabPane>

        <NTabPane name="preview" :tab="t('pages.models.tabs.preview')">
          <NSpace vertical :size="8">
            <div class="models-preview-grid">
              <div class="models-preview-card" :class="{ 'is-changed': !!createChangePreview.providerId }">
                <NText depth="3" class="models-preview-label">{{ t('pages.models.form.providerId') }}</NText>
                <NTag size="small" :type="createChangePreview.providerExists ? 'error' : 'info'" :bordered="false">
                  {{ createChangePreview.providerId || t('pages.models.preview.notProvided') }}
                </NTag>
              </div>

              <div class="models-preview-card">
                <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.apiProtocol') }}</NText>
                <code>{{ createChangePreview.api }}</code>
              </div>

              <div class="models-preview-card" :class="{ 'is-changed': createChangePreview.baseUrl !== '-' }">
                <NText depth="3" class="models-preview-label">Base URL</NText>
                <code>{{ createChangePreview.baseUrl }}</code>
              </div>

              <div class="models-preview-card" :class="{ 'is-changed': createChangePreview.modelIds.length > 0 }">
                <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.models') }}</NText>
                <code>{{ createChangePreview.modelIds.length }}</code>
              </div>

              <div class="models-preview-card" :class="{ 'is-changed': createChangePreview.hasApiKey }">
                <NText depth="3" class="models-preview-label">API Key</NText>
                <NTag size="small" :type="createChangePreview.hasApiKey ? 'warning' : 'error'" :bordered="false">
                  {{ createChangePreview.hasApiKey ? t('pages.models.preview.willWriteMasked') : t('pages.models.preview.notProvided') }}
                </NTag>
              </div>

              <div class="models-preview-card" :class="{ 'is-changed': !!createChangePreview.inferredPrimary }">
                <NText depth="3" class="models-preview-label">{{ t('pages.models.preview.primaryModel') }}</NText>
                <NTag size="small" :type="createChangePreview.inferredPrimary ? 'warning' : 'default'" :bordered="false">
                  {{ createChangePreview.inferredPrimary || t('pages.models.preview.unchanged') }}
                </NTag>
              </div>
            </div>

            <NCollapse v-if="createChangePreview.modelIds.length > 0">
              <NCollapseItem :title="t('pages.models.preview.modelsListTitle', { count: createChangePreview.modelIds.length })" name="create-model-list">
                <NSpace :size="6" style="flex-wrap: wrap;">
                  <NTag
                    v-for="id in createChangePreview.modelIds"
                    :key="`create-model-${id}`"
                    size="small"
                    :bordered="false"
                  >
                    {{ id }}
                  </NTag>
                </NSpace>
              </NCollapseItem>
            </NCollapse>

            <div class="models-preview-paths">
              <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.patchPaths') }}</NText>
              <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                <NTag
                  v-for="path in createChangePreview.patchPaths"
                  :key="`create-path-${path}`"
                  size="small"
                  :bordered="false"
                >
                  {{ path }}
                </NTag>
              </NSpace>
            </div>

            <NAlert v-if="createChangePreview.warnings.length" type="warning" :bordered="false">
              <div v-for="(warning, index) in createChangePreview.warnings" :key="index">
                {{ warning }}
              </div>
            </NAlert>

            <NAlert v-if="!createChangePreview.ready" type="info" :bordered="false">
              {{ t('pages.models.preview.missingRequired', {
                fields: joinDisplayList(createChangePreview.missingRequired) || t('pages.models.preview.none'),
              }) }}
            </NAlert>

            <NSpace justify="space-between">
              <NButton @click="createActiveTab = 'models'">{{ t('pages.models.actions.prev') }}</NButton>
              <NButton
                type="primary"
                :loading="configStore.saving"
                :disabled="!createChangePreview.ready"
                @click="handleCreateProviderClick"
              >
                <template #icon><NIcon :component="SaveOutline" /></template>
                {{ t('pages.models.actions.createProvider') }}
              </NButton>
            </NSpace>
          </NSpace>
        </NTabPane>
      </NTabs>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="showCreateProviderModal = false">{{ t('common.cancel') }}</NButton>
        </NSpace>
      </template>
    </NModal>

    <NModal
      v-model:show="showSaveConfirmModal"
      preset="card"
      :title="saveConfirmTitle"
      style="max-width: 760px; width: 92vw;"
      :mask-closable="false"
    >
      <NSpace vertical :size="12">
        <NAlert type="warning" :bordered="false">
          {{ t('pages.models.confirm.warningPrefix') }}<code>config.patch</code>{{ t('pages.models.confirm.warningSuffix') }}
        </NAlert>

        <template v-if="confirmActionType === 'edit' && editChangePreview">
          <NDescriptions bordered :column="1" size="small" label-placement="left">
            <NDescriptionsItem :label="t('pages.models.confirm.editProvider')">
              <NTag size="small" type="info" :bordered="false">
                {{ editChangePreview.providerId }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.apiProtocol')">
              {{ editChangePreview.apiDiff.before }} -> {{ editChangePreview.apiDiff.after }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.baseUrl')">
              {{ editChangePreview.baseUrlDiff.before }} -> {{ editChangePreview.baseUrlDiff.after }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.preview.models')">
              {{ editChangePreview.modelDiff.beforeCount }} -> {{ editChangePreview.modelDiff.afterCount }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.apiKey')">
              {{ editChangePreview.apiKeyAction === 'overwrite'
                ? t('pages.models.preview.apiKeyOverwrite')
                : t('pages.models.preview.apiKeyKeep') }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.preview.primaryModel')">
              {{ editChangePreview.inferredPrimary || t('pages.models.preview.unchanged') }}
            </NDescriptionsItem>
          </NDescriptions>

          <NCollapse v-if="editChangePreview.modelDiff.changed">
            <NCollapseItem
              :title="t('pages.models.confirm.modelDiffTitle', {
                added: editChangePreview.modelDiff.added.length,
                removed: editChangePreview.modelDiff.removed.length,
              })"
              name="confirm-edit-models"
            >
              <NSpace vertical :size="8">
                <div v-if="editChangePreview.modelDiff.added.length">
                  <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.addedModels') }}</NText>
                  <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                    <NTag
                      v-for="id in editChangePreview.modelDiff.added"
                      :key="`confirm-add-${id}`"
                      type="success"
                      size="small"
                      :bordered="false"
                    >
                      + {{ id }}
                    </NTag>
                  </NSpace>
                </div>
                <div v-if="editChangePreview.modelDiff.removed.length">
                  <NText depth="3" style="font-size: 12px;">{{ t('pages.models.preview.removedModels') }}</NText>
                  <NSpace :size="6" style="margin-top: 6px; flex-wrap: wrap;">
                    <NTag
                      v-for="id in editChangePreview.modelDiff.removed"
                      :key="`confirm-remove-${id}`"
                      type="error"
                      size="small"
                      :bordered="false"
                    >
                      - {{ id }}
                    </NTag>
                  </NSpace>
                </div>
              </NSpace>
            </NCollapseItem>
          </NCollapse>

          <NText depth="3" style="font-size: 12px;">
            {{ t('pages.models.preview.patchPathsWithValue', { paths: editChangePreview.patchPaths.join(', ') }) }}
          </NText>
        </template>

        <template v-else>
          <NDescriptions bordered :column="1" size="small" label-placement="left">
            <NDescriptionsItem :label="t('pages.models.confirm.createProvider')">
              <NTag size="small" type="info" :bordered="false">
                {{ createChangePreview.providerId || t('pages.models.preview.notProvided') }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.apiProtocol')">
              {{ createChangePreview.api }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.baseUrl')">
              {{ createChangePreview.baseUrl }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.preview.models')">
              {{ createChangePreview.modelIds.length }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.form.apiKey')">
              {{ createChangePreview.hasApiKey ? t('pages.models.preview.willWriteMasked') : t('pages.models.preview.notProvided') }}
            </NDescriptionsItem>
            <NDescriptionsItem :label="t('pages.models.preview.primaryModel')">
              {{ createChangePreview.inferredPrimary || t('pages.models.preview.unchanged') }}
            </NDescriptionsItem>
          </NDescriptions>

          <NCollapse v-if="createChangePreview.modelIds.length > 0">
            <NCollapseItem :title="t('pages.models.preview.modelsListTitle', { count: createChangePreview.modelIds.length })" name="confirm-create-models">
              <NSpace :size="6" style="flex-wrap: wrap;">
                <NTag
                  v-for="id in createChangePreview.modelIds"
                  :key="`confirm-create-${id}`"
                  size="small"
                  :bordered="false"
                >
                  {{ id }}
                </NTag>
              </NSpace>
            </NCollapseItem>
          </NCollapse>

          <NText depth="3" style="font-size: 12px;">
            {{ t('pages.models.preview.patchPathsWithValue', { paths: createChangePreview.patchPaths.join(', ') || '-' }) }}
          </NText>
        </template>

        <NAlert v-if="confirmActionType === 'edit' && editChangePreview?.warnings.length" type="warning" :bordered="false">
          <div v-for="(warning, index) in editChangePreview?.warnings" :key="`confirm-edit-warning-${index}`">
            {{ warning }}
          </div>
        </NAlert>
        <NAlert v-if="confirmActionType === 'create' && createChangePreview.warnings.length" type="warning" :bordered="false">
          <div v-for="(warning, index) in createChangePreview.warnings" :key="`confirm-create-warning-${index}`">
            {{ warning }}
          </div>
        </NAlert>
      </NSpace>

      <template #footer>
        <NSpace justify="end">
          <NButton @click="showSaveConfirmModal = false">{{ t('common.cancel') }}</NButton>
          <NButton
            type="primary"
            :loading="configStore.saving"
            :disabled="!canConfirmSave"
            @click="handleConfirmSave"
          >
            {{ saveConfirmButtonLabel }}
          </NButton>
        </NSpace>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.models-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.models-overview-card {
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at 86% 12%, rgba(32, 128, 240, 0.18), transparent 36%),
    linear-gradient(125deg, var(--bg-card), rgba(24, 160, 88, 0.08));
  border: 1px solid rgba(32, 128, 240, 0.16);
}

.models-overview-title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}

.models-overview-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.models-metric-item {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--bg-primary);
  padding: 10px 12px;
}

.models-metric-value {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}

.models-metric-code {
  font-size: 14px;
  font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

.models-workbench-card {
  border-radius: var(--radius-lg);
}

.models-quick-card {
  border-radius: var(--radius-lg);
}

.models-quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.models-quick-item {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  background:
    radial-gradient(circle at 88% 10%, rgba(24, 160, 88, 0.12), transparent 45%),
    var(--bg-primary);
}

.models-quick-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.models-quick-meta {
  font-size: 12px;
  line-height: 1.45;
}

.models-quick-meta code {
  white-space: normal;
  word-break: break-all;
}

.models-quick-doc-link {
  color: var(--primary-color);
  font-size: 12px;
  text-decoration: none;
}

.models-quick-doc-link:hover {
  text-decoration: underline;
}

.models-workbench-item {
  min-width: 0;
}

.models-panel {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  background: var(--bg-primary);
  overflow: hidden;
}

.models-panel :deep(.n-data-table-wrapper) {
  overflow-x: auto;
}

.models-provider-table :deep(.n-data-table-th),
.models-provider-table :deep(.n-data-table-td) {
  padding: 9px 10px;
}

.models-provider-actions-wrap {
  width: 100%;
  display: flex;
  justify-content: flex-end;
}

.models-provider-actions {
  align-items: center;
  flex-wrap: nowrap;
  justify-content: flex-end;
}

.models-action-btn {
  min-width: 72px;
  height: 34px;
  padding: 0 12px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.1px;
  transition: transform 0.16s ease, box-shadow 0.16s ease;
}

.models-action-btn--active {
  min-width: 82px;
}

.models-action-btn:not(:disabled):hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(15, 23, 42, 0.12);
}

.models-panel-toolbar {
  margin-bottom: 10px;
}

.models-editor-header {
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.models-preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}

.models-preview-card {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-primary);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.models-preview-card.is-changed {
  border-color: rgba(24, 160, 88, 0.5);
  background: rgba(24, 160, 88, 0.08);
}

.models-preview-label {
  font-size: 12px;
}

.models-preview-card code {
  white-space: normal;
  word-break: break-all;
  font-size: 12px;
}

.models-preview-diff {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.models-preview-diff--block {
  align-items: flex-start;
}

.models-preview-arrow {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.models-preview-paths {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-primary);
}

.models-empty {
  margin-top: 12px;
}

@media (max-width: 1100px) {
  .models-overview-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .models-quick-grid {
    grid-template-columns: 1fr;
  }

  .models-panel-toolbar {
    flex-direction: column;
    align-items: stretch !important;
  }
}
</style>
