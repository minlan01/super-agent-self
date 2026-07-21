<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NTag, NSpin, NEmpty, NButton, NIcon, NSpace, NAlert } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { useMyselfAgentStore } from '@/stores/myself-agent'
import type { MyselfTask } from '@/api/myself-agent'

const store = useMyselfAgentStore()
const loading = ref(false)

const columns = [
  { title: '标题', key: 'title', ellipsis: true },
  { title: '状态', key: 'status', width: 80, render: (row: MyselfTask) => {
    const map: Record<string, { type: 'success' | 'info' | 'warning' | 'error' | 'default'; label: string }> = {
      completed: { type: 'success', label: '完成' },
      in_progress: { type: 'info', label: '进行中' },
      pending: { type: 'warning', label: '待处理' },
      cancelled: { type: 'error', label: '已取消' },
      failed: { type: 'error', label: '失败' },
    }
    const item = map[row.status] || { type: 'default' as const, label: row.status }
    return h(NTag, { type: item.type, size: 'small' }, item.label)
  }},
  { title: '创建时间', key: 'created_at', width: 160 },
]

async function load() {
  loading.value = true
  await store.fetchTasks()
  loading.value = false
}

onMounted(() => { if (store.connected) load() })
</script>

<template>
  <NSpin :show="loading">
    <div style="padding: 16px; max-width: 1200px; margin: 0 auto">
      <NAlert v-if="!store.connected && !store.connecting" type="warning" style="margin-bottom: 16px">
        myself-agent 未连接，无法加载任务数据。
      </NAlert>
      <NCard title="任务列表" size="small">
        <template #header-extra>
          <NButton size="small" @click="load">
            <template #icon><NIcon><RefreshOutline /></NIcon></template>
          </NButton>
        </template>
        <NDataTable v-if="store.tasks.length > 0" :columns="columns" :data="store.tasks" size="small" :max-height="500" />
        <NEmpty v-else description="暂无任务" />
      </NCard>
    </div>
  </NSpin>
</template>
