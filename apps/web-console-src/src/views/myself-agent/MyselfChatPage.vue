<script setup lang="ts">
import { NCard, NAlert, NEmpty } from 'naive-ui'
import { useMyselfAgentStore } from '@/stores/myself-agent'

const store = useMyselfAgentStore()
</script>

<template>
  <div style="padding: 16px; max-width: 800px; margin: 0 auto">
    <NAlert v-if="!store.connected && !store.connecting" type="warning" style="margin-bottom: 16px">
      myself-agent 未连接。
    </NAlert>
    <NCard title="对话交互" size="small">
      <NEmpty description="对话功能接入中，请通过 API 直接调用 /myself-agent/chat" />
    </NCard>
  </div>
</template>
