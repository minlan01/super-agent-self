<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NTag, NSpin, NEmpty, NButton, NIcon, NAlert } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { useMyselfAgentStore } from '@/stores/myself-agent'
import type { MyselfCronJob } from '@/api/myself-agent'

const store = useMyselfAgentStore()
const loading = ref(false)

const columns = [
  { title: '名称', key: 'name', ellipsis: true },
  { title: '调度', key: 'schedule' },
  { title: '状态', key: 'enabled', width: 70, render: (row: MyselfCronJob) =>
    h(NTag, { type: row.enabled ? 'success' : 'default', size: 'small' }, row.enabled ? '启用' : '停用')
  },
  { title: '上次运行', key: 'last_run', width: 160 },
]

async function load() {
  loading.value = true
  await store.fetchCronJobs()
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
      <NCard title="定时任务" size="small">
        <template #header-extra>
          <NButton size="small" @click="load"><template #icon><NIcon><RefreshOutline /></NIcon></template></NButton>
        </template>
        <NDataTable v-if="store.cronJobs.length > 0" :columns="columns" :data="store.cronJobs" size="small" />
        <NEmpty v-else description="暂无定时任务" />
      </NCard>
    </div>
  </NSpin>
</template>
