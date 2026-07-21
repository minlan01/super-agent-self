<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NPopover, NButton } from 'naive-ui'
import MuseumCanvas from './MuseumCanvas.vue'
import { ROOM_ROUTE_MAP } from '@/adapters/museum/router-sync'
import type { ResourcePartitionId } from '@/museum/core/types'
import type { OpenClawSnapshot } from '@/museum/core/types'

const props = defineProps<{
  snapshot?: OpenClawSnapshot | null
}>()

const router = useRouter()
const visible = ref(false)
const collapsed = ref(false)

function onRoomSelect(resourceId: ResourcePartitionId) {
  const route = ROOM_ROUTE_MAP[resourceId]
  if (route) {
    router.push(route)
  }
  // Close popover after navigation
  visible.value = false
}

function toggleWidget() {
  if (collapsed.value) {
    collapsed.value = false
  } else {
    visible.value = !visible.value
  }
}
</script>

<template>
  <div v-if="!collapsed" class="mini-museum-widget">
    <NPopover
      :show="visible"
      trigger="manual"
      placement="top-end"
      :width="340"
      :show-arrow="false"
      raw
    >
      <template #trigger>
        <NButton
          quaternary
          circle
          size="small"
          @click="toggleWidget"
        >
          <span class="widget-trigger-icon">🏛</span>
        </NButton>
      </template>

      <div class="popover-content glass-panel-strong">
        <div class="popover-header pixel-text">
          <span>Pixel Museum</span>
          <button class="popover-close" @click="visible = false">&times;</button>
        </div>
        <div class="popover-canvas">
          <MuseumCanvas
            mode="mini"
            :snapshot="snapshot"
            @room-select="onRoomSelect"
          />
        </div>
        <div class="popover-hint">
          Click a room to navigate
        </div>
      </div>
    </NPopover>
  </div>
  <button
    v-else
    class="widget-collapsed"
    @click="toggleWidget"
    title="Show museum"
  >
    🏛
  </button>
</template>

<style scoped>
.mini-museum-widget {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 100;
}

.widget-trigger-icon {
  font-size: 18px;
  filter: drop-shadow(0 0 6px var(--accent-glow));
}

.popover-content {
  border-radius: 0;
  overflow: hidden;
}

.popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 14px;
  color: var(--ink);
  background: var(--panel-strong);
  border-bottom: 1px solid var(--line);
}

.popover-close {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 18px;
  cursor: pointer;
  line-height: 1;
}

.popover-close:hover {
  color: var(--ink);
}

.popover-canvas {
  width: 320px;
  height: 180px;
  background: var(--bg-deepest);
}

.popover-hint {
  padding: 6px 10px;
  font-family: var(--font-display);
  font-size: 11px;
  color: var(--dim);
  text-align: center;
  background: var(--panel);
  border-top: 1px solid var(--line);
}

.widget-collapsed {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 100;
  width: 36px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--panel-strong);
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 12px var(--accent-glow);
  transition: border-color var(--ease-fast);
}

.widget-collapsed:hover {
  border-color: var(--accent);
}
</style>
