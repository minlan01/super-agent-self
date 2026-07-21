<script setup lang="ts">
import {
  NTag,
  NText,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Skill } from '@/api/types'

interface SlashCommandPreset {
  command: string
  usage?: string
  description: string
  category: string
  expectArgs?: boolean
  aliases?: string[]
}

interface SubagentsSubcommandPreset {
  subcommand: string
  usage?: string
  description: string
}

interface ConfiguredModelOption {
  modelRef: string
  providerId: string
  modelId: string
}

export interface SlashSuggestionItem {
  kind: 'command' | 'skill' | 'subagents-subcommand' | 'model' | 'new-model' | 'new-default'
  key: string
  preset?: SlashCommandPreset
  skill?: Skill
  subagentsSubcommand?: SubagentsSubcommandPreset
  model?: ConfiguredModelOption
}

const props = defineProps<{
  suggestions: SlashSuggestionItem[]
  selectedIndex: number
}>()

const emit = defineEmits<{
  (e: 'update:selectedIndex', index: number): void
  (e: 'apply', item: SlashSuggestionItem): void
}>()

const { t } = useI18n()

function skillSourceLabel(source: Skill['source']): string {
  if (source === 'workspace') return t('pages.skills.sources.workspace')
  if (source === 'managed') return t('pages.skills.sources.managed')
  if (source === 'extra') return t('pages.skills.sources.extra')
  return t('pages.skills.sources.bundled')
}
</script>

<template>
  <div class="chat-slash-panel">
    <div class="chat-slash-head">
      <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.slash.title') }}</NText>
      <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.slash.hint') }}</NText>
    </div>
    <div v-if="suggestions.length" class="chat-slash-list">
      <button
        v-for="(item, index) in suggestions"
        :key="item.key"
        class="chat-slash-item"
        :class="{ 'is-active': index === selectedIndex }"
        type="button"
        @mouseenter="emit('update:selectedIndex', index)"
        @mousedown.prevent
        @click="emit('apply', item)"
      >
        <div v-if="item.kind === 'command' && item.preset">
          <div class="chat-slash-line">
            <span class="chat-slash-command">{{ item.preset.command }}</span>
            <span v-if="item.preset.usage" class="chat-slash-usage">{{ item.preset.usage }}</span>
            <NTag size="tiny" :bordered="false" round>{{ item.preset.category }}</NTag>
          </div>
          <div class="chat-slash-line chat-slash-desc">
            <span>{{ item.preset.description }}</span>
          </div>
        </div>
        <div v-else-if="item.kind === 'skill' && item.skill">
          <div class="chat-slash-line">
            <span class="chat-slash-command">/skill {{ item.skill.name }}</span>
            <NTag size="tiny" type="success" :bordered="false" round>
              {{ skillSourceLabel(item.skill.source) }}
            </NTag>
          </div>
          <div v-if="item.skill.description" class="chat-slash-line chat-slash-desc">
            <span>{{ item.skill.description }}</span>
          </div>
        </div>
        <div v-else-if="item.kind === 'subagents-subcommand' && item.subagentsSubcommand">
          <div class="chat-slash-line">
            <span class="chat-slash-command">/subagents {{ item.subagentsSubcommand.subcommand }}</span>
            <span v-if="item.subagentsSubcommand.usage" class="chat-slash-usage">{{ item.subagentsSubcommand.usage }}</span>
          </div>
          <div class="chat-slash-line chat-slash-desc">
            <span>{{ item.subagentsSubcommand.description }}</span>
          </div>
        </div>
        <div v-else-if="item.kind === 'model' && item.model">
          <div class="chat-slash-line">
            <span class="chat-slash-command">/model {{ item.model.modelRef }}</span>
          </div>
          <div class="chat-slash-line chat-slash-desc">
            <span>{{ item.model.providerId }} / {{ item.model.modelId }}</span>
          </div>
        </div>
        <div v-else-if="item.kind === 'new-default'">
          <div class="chat-slash-line">
            <span class="chat-slash-command">/new</span>
            <NTag size="tiny" type="info" :bordered="false" round>
              {{ t('pages.chat.slash.commands.new.defaultLabel') }}
            </NTag>
          </div>
          <div class="chat-slash-line chat-slash-desc">
            <span>{{ t('pages.chat.slash.commands.new.defaultDesc') }}</span>
          </div>
        </div>
        <div v-else-if="item.kind === 'new-model' && item.model">
          <div class="chat-slash-line">
            <span class="chat-slash-command">/new {{ item.model.modelRef }}</span>
          </div>
          <div class="chat-slash-line chat-slash-desc">
            <span>{{ item.model.providerId }} / {{ item.model.modelId }}</span>
          </div>
        </div>
      </button>
    </div>
    <div v-else class="chat-slash-empty">
      <NText depth="3" style="font-size: 12px;">{{ t('pages.chat.slash.noMatch') }}</NText>
    </div>
  </div>
</template>

<style scoped>
.chat-slash-panel {
  margin-top: 8px;
  padding: 8px;
  background: var(--bg-secondary);
  border-radius: var(--radius);
  border: 1px solid var(--border-color);
}

.chat-slash-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.chat-slash-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.chat-slash-item {
  display: block;
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
}

.chat-slash-item:hover,
.chat-slash-item.is-active {
  background: rgba(24, 160, 88, 0.1);
}

.chat-slash-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-slash-command {
  font-weight: 600;
  font-size: 13px;
  color: #fff;
}

.chat-slash-usage {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.chat-slash-desc {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.chat-slash-empty {
  padding: 12px;
  text-align: center;
}
</style>
