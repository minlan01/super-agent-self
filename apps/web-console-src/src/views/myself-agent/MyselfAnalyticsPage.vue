<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NCard, NSpin, NAlert, NStatistic, NGrid, NGi, NEmpty } from 'naive-ui'
import { useMyselfAgentStore } from '@/stores/myself-agent'

const store = useMyselfAgentStore()
const loading = ref(false)

async function load() {
  loading.value = true
  await store.fetchMetrics()
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
      <NCard title="分析面板" size="small">
        <NGrid v-if="store.metrics" :cols="4" :x-gap="12" responsive="screen">
          <NGi span="1">
            <NStatistic label="总任务数" :value="store.metrics.total_tasks || 0" />
          </NGi>
          <NGi span="1">
            <NStatistic label="记忆总数" :value="store.metrics.memories?.total || 0" />
          </NGi>
          <NGi span="1">
            <NStatistic label="活跃记忆" :value="store.metrics.memories?.active || 0" />
          </NGi>
          <NGi span="1">
            <NStatistic label="运行时间(秒)" :value="store.metrics.uptime_seconds || 0" />
          </NGi>
        </NGrid>
        <NEmpty v-else description="加载中..." />
      </NCard>
    </div>
  </NSpin>
</template>
