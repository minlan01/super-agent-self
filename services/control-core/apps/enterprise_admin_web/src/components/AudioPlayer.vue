<template>
  <div v-if="audioUrl" class="audio-player">
    <audio :src="audioUrl" controls class="audio-element" />
    <el-button size="small" circle @click="dismiss">
      <el-icon><Close /></el-icon>
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Close } from '@element-plus/icons-vue'

const props = defineProps<{ url: string | null }>()
const emit = defineEmits<{ dismiss: [] }>()
const audioUrl = ref<string | null>(null)

watch(() => props.url, (val) => { audioUrl.value = val }, { immediate: true })

function dismiss() {
  audioUrl.value = null
  emit('dismiss')
}
</script>

<style scoped>
.audio-player {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  margin-bottom: 8px;
}
.audio-element {
  flex: 1;
  height: 36px;
}
</style>
