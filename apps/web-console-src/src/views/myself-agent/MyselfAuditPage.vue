<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NCard, NSpin, NEmpty, NButton, NIcon, NDataTable, NAlert } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { myselfAudit, type MyselfAuditEntry } from '@/api/myself-agent'

const entries = ref<MyselfAuditEntry[]>([])
const loading = ref(false)
const connected = ref(true)

const columns = [
  { title: '操作', key: 'action', ellipsis: true },
  { title: '实体类型', key: 'entity_type', width: 100 },
  { title: '时间', key: 'timestamp', width: 160 },
]

async function load() {
  loading.value = true
  try {
    const { success, data } = await myselfAudit.list({ limit: '50' })
    connected.value = true
    if (success && data) entries.value = data
  } catch {
    connected.value = false
  }
  loading.value = false
}

onMounted(() => load())
</script>

<template>
  <NSpin :show="loading">
    <div style="padding: 16px; max-width: 1200px; margin: 0 auto">
      <NAlert v-if="!connected" type="warning" style="margin-bottom: 16px">
        myself-agent 未连接。
      </NAlert>
      <NCard title="审计日志" size="small">
        <template #header-extra>
          <NButton size="small" @click="load"><template #icon><NIcon><RefreshOutline /></NIcon></template></NButton>
        </template>
        <NDataTable v-if="entries.length > 0" :columns="columns" :data="entries" size="small" :max-height="500" />
        <NEmpty v-else description="暂无审计记录" />
      </NCard>
    </div>
  </NSpin>
</template>
