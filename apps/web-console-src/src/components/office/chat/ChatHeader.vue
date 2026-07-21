<script setup lang="ts">
import {
  NButton,
  NIcon,
  NSpace,
  NSwitch,
  NTag,
  NTooltip,
} from 'naive-ui'
import { ExpandOutline, TimeOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'

export interface TokenMetricTag {
  key: string
  label: string
  value: string
  highlight: boolean
}

const props = defineProps<{
  tokenMetrics: TokenMetricTag[]
  hasSessionKey: boolean
  tokenStatusText: string
  executionInProgress: boolean
  agentDisplayName: string
  sessionDisplayLabel: string
  sessionTooltip: string
  autoFollowBottom: boolean
}>()

const emit = defineEmits<{
  (e: 'update:autoFollowBottom', value: boolean): void
  (e: 'open-expanded'): void
}>()

const { t } = useI18n()
</script>

<template>
  <NSpace :size="8" align="center">
    <div v-if="tokenMetrics.length" class="chat-token-metrics">
      <NTag
        v-for="metric in tokenMetrics"
        :key="metric.key"
        size="small"
        :bordered="false"
        round
        class="chat-token-chip"
        :class="{ 'chat-token-chip--total': metric.highlight }"
      >
        <span class="chat-token-chip__label">{{ metric.label }}</span>
        <span class="chat-token-chip__value">{{ metric.value }}</span>
      </NTag>
    </div>
    <NTag v-else-if="hasSessionKey" size="small" :bordered="false" round class="chat-token-chip chat-token-chip--loading">
      {{ tokenStatusText }}
    </NTag>
    <NTag v-if="executionInProgress" size="small" type="info" :bordered="false" round>
      <template #icon>
        <NIcon :component="TimeOutline" />
      </template>
      {{ t('pages.office.chat.executing') }}
    </NTag>
    <NTooltip>
      <template #trigger>
        <NTag size="small" :bordered="false" round class="session-tag">
          <span class="session-tag__text">
            {{ agentDisplayName }} / {{ sessionDisplayLabel }}
          </span>
        </NTag>
      </template>
      {{ sessionTooltip }}
    </NTooltip>
    <NTooltip>
      <template #trigger>
        <NSwitch :value="autoFollowBottom" size="small" @update:value="emit('update:autoFollowBottom', $event)" />
      </template>
      {{ t('pages.chat.preferences.autoFollow') }}
    </NTooltip>
    <NButton size="tiny" quaternary @click="emit('open-expanded')">
      <template #icon>
        <NIcon :component="ExpandOutline" />
      </template>
    </NButton>
  </NSpace>
</template>

<style scoped>
.chat-token-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.chat-token-chip.n-tag {
  border-radius: 999px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 11px;
}

.chat-token-chip--total.n-tag {
  background: rgba(32, 128, 240, 0.12);
}

.chat-token-chip--loading.n-tag {
  border: 1px dashed var(--border-color);
}

.chat-token-chip__label {
  color: var(--text-secondary);
  margin-right: 3px;
}

.chat-token-chip__value {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.session-tag {
  max-width: 200px;
  overflow: hidden;
}

.session-tag__text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}
</style>
