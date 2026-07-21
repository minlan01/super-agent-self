<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NCard, NDataTable, NSpin, NEmpty, NButton, NIcon, NAlert } from 'naive-ui'
import { RefreshOutline } from '@vicons/ionicons5'
import { useMyselfAgentStore } from '@/stores/myself-agent'

const store = useMyselfAgentStore()
const loading = ref(false)

const columns = [
  { title: '名称', key: 'name', ellipsis: true },
  { title: '分类', key: 'category', width: 100 },
  { title: '版本', key: 'version', width: 80 },
]

async function load() {
  loading.value = true
  await store.fetchSkills()
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
      <NCard title="技能管理" size="small">
        <template #header-extra>
          <NButton size="small" @click="load"><template #icon><NIcon><RefreshOutline /></NIcon></template></NButton>
        </template>
        <NDataTable v-if="store.skills.length > 0" :columns="columns" :data="store.skills" size="small" />
        <NEmpty v-else description="暂无技能" />
      </NCard>
    </div>
  </NSpin>
</template>
