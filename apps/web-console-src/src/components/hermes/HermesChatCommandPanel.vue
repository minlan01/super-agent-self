<script setup lang="ts">
import { NSpace, NText, NTag } from 'naive-ui'
import type { CommandItem } from '@/api/hermes/chat-types'

defineProps<{
  commands: CommandItem[]
  selectedIndex: number
}>()

const emit = defineEmits<{
  select: [cmd: CommandItem]
  hover: [index: number]
}>()
</script>

<template>
  <Transition name="hermes-slide">
    <div v-if="commands.length > 0" class="hermes-command-panel">
      <div
        v-for="(cmd, idx) in commands"
        :key="cmd.key"
        class="hermes-command-item"
        :class="{ 'hermes-command-item--active': idx === selectedIndex }"
        @click="emit('select', cmd)"
        @mouseenter="emit('hover', idx)"
      >
        <NSpace :size="8" align="center" justify="space-between">
          <NSpace :size="8" align="center">
            <NText strong style="font-size: 13px; min-width: 80px;">{{ cmd.key }}</NText>
            <NText v-if="cmd.argsHint" depth="3" style="font-size: 11px; font-style: italic;">{{ cmd.argsHint }}</NText>
          </NSpace>
          <NSpace :size="6" align="center">
            <NTag size="tiny" :bordered="false" type="info">{{ cmd.category }}</NTag>
            <NText depth="3" style="font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{{ cmd.description }}</NText>
          </NSpace>
        </NSpace>
      </div>
    </div>
  </Transition>
</template>
