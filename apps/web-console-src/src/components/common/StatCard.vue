<script setup lang="ts">
import { NIcon } from 'naive-ui'

defineProps<{
  title: string
  value: number | string
  icon: unknown
  color?: string
  /** stat-bar fill percentage (0-100), optional */
  barValue?: number
}>()
</script>

<template>
  <div
    class="pixel-stat"
    :style="{ '--stat-accent': color || '#18a058' }"
  >
    <div style="display: flex; justify-content: space-between; align-items: flex-start; padding: 14px 14px 10px 18px;">
      <div style="display: flex; flex-direction: column;">
        <span class="pixel-stat-value" :style="{ color: color || '#18a058' }">
          {{ value }}
        </span>
        <span class="pixel-stat-label">{{ title }}</span>
      </div>
      <div class="pixel-stat-icon" :style="{ color: color || '#18a058' }">
        <NIcon :size="22" :component="icon as any" />
      </div>
    </div>

    <!-- RPG-style stat bar -->
    <div v-if="barValue !== undefined" style="padding: 0 14px 12px 18px;">
      <div class="stat-bar">
        <div
          class="stat-bar-fill"
          :style="{
            width: `${Math.min(Math.max(barValue, 0), 100)}%`,
            background: `linear-gradient(180deg, ${color || '#18a058'}, ${color || '#18a058'}88)`,
            boxShadow: `inset 0 1px 0 rgba(255,255,255,0.15), 0 0 8px ${color || '#18a058'}33`,
          }"
        />
      </div>
    </div>
  </div>
</template>
