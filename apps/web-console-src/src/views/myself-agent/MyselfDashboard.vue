<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NGrid, NGi, NStatistic, NButton, NIcon, NSpace, NTag,
  NDataTable, NSpin, NEmpty, NAlert,
} from 'naive-ui'
import {
  ListOutline, ExtensionPuzzleOutline, BookOutline,
  CalendarOutline, AnalyticsOutline, RefreshOutline,
  ChatboxEllipsesOutline,
} from '@vicons/ionicons5'
import { useMyselfAgentStore } from '@/stores/myself-agent'

const router = useRouter()
const store = useMyselfAgentStore()
const loading = ref(false)

const statCards = computed(() => [
  { title: '总任务数', value: store.taskCount, color: '#63e2b7', icon: ListOutline, route: '/myself-agent/tasks' },
  { title: '活跃任务', value: store.activeTaskCount, color: '#e69a3a', icon: AnalyticsOutline, route: '/myself-agent/tasks' },
  { title: '技能数', value: store.skillCount, color: '#70c0e8', icon: ExtensionPuzzleOutline, route: '/myself-agent/skills' },
  { title: '记忆条目', value: store.memoryCount, color: '#a78bfa', icon: BookOutline, route: '/myself-agent/memory' },
  { title: '活跃定时任务', value: store.activeCronCount, color: '#f0a0a0', icon: CalendarOutline, route: '/myself-agent/cron' },
])

const taskColumns = [
  { title: '标题', key: 'title', ellipsis: true },
  { title: '状态', key: 'status', width: 100, render: (row: { status: string }) =>
    row.status === 'completed' ? h(NTag, { type: 'success', size: 'small' }, '完成') :
    row.status === 'in_progress' ? h(NTag, { type: 'info', size: 'small' }, '进行中') :
    row.status === 'pending' ? h(NTag, { type: 'warning', size: 'small' }, '待处理') :
    h(NTag, { size: 'small' }, row.status)
  },
]

async function loadData() {
  loading.value = true
  await store.fetchAll()
  loading.value = false
}

onMounted(() => { loadData() })
</script>

<template>
  <NSpin :show="loading">
    <div style="padding: 16px; max-width: 1200px; margin: 0 auto">
      <NAlert v-if="!store.connected && !store.connecting" type="warning" style="margin-bottom: 16px">
        myself-agent 未连接。请确认服务已启动（端口 8000），然后点击刷新按钮重试。
      </NAlert>

      <NGrid :cols="5" :x-gap="12" :y-gap="12" responsive="screen" style="margin-bottom: 16px">
        <NGi v-for="card in statCards" :key="card.title" :span="1">
          <NCard hoverable size="small" @click="router.push(card.route)" style="cursor: pointer">
            <NStatistic>
              <template #prefix>
                <NIcon :size="20" :color="card.color"><component :is="card.icon" /></NIcon>
              </template>
              {{ card.value }}
              <template #label>{{ card.title }}</template>
            </NStatistic>
          </NCard>
        </NGi>
      </NGrid>

      <NGrid :cols="2" :x-gap="16" responsive="screen">
        <NGi span="1">
          <NCard title="近期任务" size="small" :bordered="true">
            <NDataTable
              v-if="store.tasks.length > 0"
              :columns="taskColumns"
              :data="store.tasks.slice(0, 10)"
              :max-height="300"
              size="small"
            />
            <NEmpty v-else description="暂无任务" />
          </NCard>
        </NGi>
        <NGi span="1">
          <NCard title="快捷入口" size="small" :bordered="true">
            <NSpace vertical :size="8">
              <NButton block dashed @click="router.push('/myself-agent/chat')">
                <template #icon><NIcon><ChatboxEllipsesOutline /></NIcon></template>
                对话交互
              </NButton>
              <NButton block dashed @click="router.push('/myself-agent/skills')">
                <template #icon><NIcon><ExtensionPuzzleOutline /></NIcon></template>
                技能管理
              </NButton>
              <NButton block dashed @click="router.push('/myself-agent/cron')">
                <template #icon><NIcon><CalendarOutline /></NIcon></template>
                定时任务
              </NButton>
              <NButton block dashed @click="router.push('/myself-agent/analytics')">
                <template #icon><NIcon><AnalyticsOutline /></NIcon></template>
                分析面板
              </NButton>
            </NSpace>
          </NCard>
        </NGi>
      </NGrid>

      <NSpace justify="center" style="margin-top: 16px">
        <NButton size="small" @click="loadData">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
          刷新数据
        </NButton>
      </NSpace>
    </div>
  </NSpin>
</template>
