<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NLayout, NLayoutHeader, NLayoutContent, NButton, NIcon, NSpace, NTag, NSpin } from 'naive-ui'
import { ArrowBackOutline, RefreshOutline } from '@vicons/ionicons5'
import { useRouter } from 'vue-router'
import { useMyselfAgentStore } from '@/stores/myself-agent'

const router = useRouter()
const store = useMyselfAgentStore()
const checking = ref(false)

const statusText = computed(() => {
  if (store.connecting) return '连接中...'
  if (store.connected) return `已连接 ${store.version ? 'v' + store.version : ''}`
  return '未连接'
})

const statusType = computed(() => {
  if (store.connecting) return 'warning' as const
  if (store.connected) return 'success' as const
  return 'default' as const
})

async function handleRefresh() {
  checking.value = true
  await store.fetchAll()
  checking.value = false
}

function goBack() {
  router.push({ name: 'Dashboard' })
}

onMounted(async () => {
  if (!store.connected) {
    await store.checkConnection()
  }
  if (store.connected) {
    await store.fetchAll()
  }
})
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered style="padding: 0 16px; height: 48px; display: flex; align-items: center; justify-content: space-between">
      <NSpace align="center" :size="12">
        <NButton text size="small" @click="goBack">
          <template #icon><NIcon><ArrowBackOutline /></NIcon></template>
          返回
        </NButton>
        <span style="font-size: 16px; font-weight: 600">🧠 Myself Agent</span>
      </NSpace>
      <NSpace align="center" :size="8">
        <NTag :type="statusType" size="small">{{ statusText }}</NTag>
        <NButton text size="small" :loading="checking" @click="handleRefresh">
          <template #icon><NIcon><RefreshOutline /></NIcon></template>
        </NButton>
      </NSpace>
    </NLayoutHeader>
    <NLayoutContent>
      <router-view />
    </NLayoutContent>
  </NLayout>
</template>
