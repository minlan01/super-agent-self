<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AddOutline, RemoveOutline, ExpandOutline } from '@vicons/ionicons5'
import { NIcon } from 'naive-ui'

defineProps<{
  scale: number
}>()

const emit = defineEmits<{
  zoomIn: []
  zoomOut: []
  resetView: []
}>()

const { t } = useI18n()
</script>

<template>
  <div class="world-controls">
    <button class="control-btn" @click="emit('zoomIn')" :title="t('myworld.zoomIn')">
      <NIcon :component="AddOutline" :size="18" />
    </button>
    <span class="zoom-level">{{ Math.round(scale * 100) }}%</span>
    <button class="control-btn" @click="emit('zoomOut')" :title="t('myworld.zoomOut')">
      <NIcon :component="RemoveOutline" :size="18" />
    </button>
    <button class="control-btn reset-btn" @click="emit('resetView')" :title="t('myworld.resetView')">
      <NIcon :component="ExpandOutline" :size="18" />
    </button>
  </div>
</template>

<style scoped>
.world-controls {
  position: absolute;
  top: 80px;
  right: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 100;
  background: rgba(15, 23, 42, 0.9);
  padding: 12px;
  border-radius: 16px;
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(59, 130, 246, 0.1) 100%);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 10px;
  color: #60a5fa;
  cursor: pointer;
  transition: all 0.2s ease;
}

.control-btn:hover {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.3) 0%, rgba(59, 130, 246, 0.2) 100%);
  border-color: rgba(59, 130, 246, 0.5);
  transform: translateY(-1px);
}

.zoom-level {
  text-align: center;
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
  padding: 4px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.reset-btn {
  margin-top: 4px;
}
</style>
