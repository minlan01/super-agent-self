<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import Phaser from 'phaser'
import { LibraryScene } from '@/museum/runtime/scene/LibraryScene'
import { createTelemetryFeed } from '@/adapters/museum/telemetry-feed'
import type { TelemetryFeed } from '@/adapters/museum/telemetry-feed'
import type { OpenClawSnapshot, ResourcePartitionId } from '@/museum/core/types'

/* ── Props ── */
const props = withDefaults(
  defineProps<{
    /** 'full' = fill container, 'mini' = compact widget */
    mode?: 'full' | 'mini'
    /** Optional live telemetry snapshot */
    snapshot?: OpenClawSnapshot | null
  }>(),
  { mode: 'full', snapshot: null }
)

/* ── Emits ── */
const emit = defineEmits<{
  /** Fired when user clicks a room in the museum */
  'room-select': [resourceId: ResourcePartitionId]
  /** Fired once the Phaser scene is ready */
  ready: []
}>()

/* ── State ── */
const container = ref<HTMLDivElement>()
const game = shallowRef<Phaser.Game | null>(null)
const scene = shallowRef<LibraryScene | null>(null)
const feed = shallowRef<TelemetryFeed | null>(null)
const isReady = ref(false)

/* ── Lifecycle ── */
onMounted(() => {
  if (!container.value) return

  const sceneInstance = new LibraryScene()
  scene.value = sceneInstance

  const g = new Phaser.Game({
    type: Phaser.AUTO,
    parent: container.value,
    transparent: true,
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      width: 1920,
      height: 1080
    },
    input: { activePointers: 3 }
  })

  g.scene.add('LibraryScene', sceneInstance, false)
  g.scene.start('LibraryScene')

  // Wait for scene to become active
  const checkReady = () => {
    if (g.scene.isActive('LibraryScene')) {
      game.value = g
      isReady.value = true
      feed.value = createTelemetryFeed({ scene: sceneInstance })

      // Room select → emit
      sceneInstance.events.on('select-resource', (resourceId: ResourcePartitionId) => {
        emit('room-select', resourceId)
      })

      emit('ready')
    } else {
      requestAnimationFrame(checkReady)
    }
  }
  checkReady()
})

onUnmounted(() => {
  feed.value?.dispose()
  feed.value = null
  try {
    game.value?.destroy(true)
  } catch { /* already destroyed */ }
  game.value = null
  scene.value = null
  isReady.value = false
})

/* ── Watchers ── */
watch(
  () => props.snapshot,
  (snapshot) => {
    if (!snapshot || !feed.value) return
    feed.value.push(snapshot)
  }
)
</script>

<template>
  <div
    ref="container"
    class="museum-canvas"
    :class="mode"
  />
</template>

<style scoped>
.museum-canvas {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: transparent;
}

/* Ensure Phaser canvas uses pixel-perfect rendering */
.museum-canvas :deep(canvas) {
  image-rendering: pixelated;
}

.museum-canvas.full {
  min-height: 400px;
}

.museum-canvas.mini {
  width: 320px;
  height: 180px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
}
</style>
