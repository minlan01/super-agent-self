<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NSpin, NEmpty, NButton, NIcon, NAlert, NSwitch } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { useMyselfAgentStore } from '@/stores/myself-agent'
import type { MyselfMemory } from '@/api/myself-agent'

const store = useMyselfAgentStore()
const loading = ref(false)

const columns = [
  { title: 'Key', key: 'key', ellipsis: true },
  { title: '激活', key: 'is_active', width: 60, render: (row: MyselfMemory) =>
    h(NSwitch, { value: row.is_active, size: 'small', disabled: true })
  },
  { title: '更新时间', key: 'updated_at', width: 160 },
]

async function load() {
  loading.value = true
  await store.fetchMemories()
  loading.value = false
}

onMounted(() => { if (store.connected) load() })
</script>

<template>
  <NSpin :show="loading">
    <div style="padding: 16px; max-width: 1200px; margin: 0 auto">
      <NAlert v-if="!store.connected && !store.connecting" type="warning" style="margin-bottom: 16px">
        myself-agent 未连接。
      </NAlert>
      <NCard title="记忆管理" size="small">
        <template #header-extra>
          <NButton size="small" @click="load"><template #icon><NIcon><RefreshOutline /></NIcon></template></NButton>
        </template>
        <NDataTable v-if="store.memories.length > 0" :columns="columns" :data="store.memories" size="small" />
        <NEmpty v-else description="暂无记忆条目" />
      </NCard>
    </div>
  </NSpin>
</template>
