<template>
  <div style="display: flex; height: calc(100vh - 120px); gap: 12px">
    <!-- Left sidebar: conversation list -->
    <el-card style="width: 260px; flex-shrink: 0; display: flex; flex-direction: column" v-loading="convLoading">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>{{ t('chat.conversations') }}</span>
          <el-button size="small" type="primary" @click="newConversation">{{ t('chat.newConversation') }}</el-button>
        </div>
      </template>
      <div style="flex: 1; overflow-y: auto">
        <div
          v-for="c in conversations"
          :key="c.id"
          :class="['conv-item', { active: c.id === currentConvId }]"
          @click="loadConversation(c.id)"
        >
          {{ c.title || c.id.slice(0, 8) }}
        </div>
        <el-empty v-if="!conversations.length" :description="t('chat.noConversations')" :image-size="60" />
      </div>
    </el-card>

    <!-- Right panel: messages + input -->
    <el-card style="flex: 1; display: flex; flex-direction: column">
      <!-- Connection status bar -->
      <div v-if="wsStatus !== 'connected'" :class="['ws-status', wsStatus]">
        <span class="ws-dot" />
        {{ wsStatus === 'connecting' ? t('chat.connecting') : t('chat.disconnected') }}
        <el-button v-if="wsStatus === 'disconnected'" size="small" text type="primary" @click="connectWs">
          {{ t('chat.reconnect') }}
        </el-button>
      </div>

      <div ref="scrollRef" style="flex: 1; overflow-y: auto; padding: 12px">
        <!-- TTS audio player -->
        <AudioPlayer :url="ttsAudioUrl" @dismiss="ttsAudioUrl = null" />
        <div v-for="msg in messages" :key="msg.id" :class="['msg-bubble', msg.role]">
          <div class="msg-role">{{ msg.role === 'user' ? t('chat.you') : t('chat.assistant') }}</div>
          <div class="msg-content">{{ msg.content }}</div>
        </div>
        <!-- Typing indicator -->
        <div v-if="isTyping" class="msg-bubble assistant typing-indicator">
          <div class="msg-role">{{ t('chat.assistant') }}</div>
          <div class="typing-dots">
            <span /><span /><span />
          </div>
        </div>
        <el-empty v-if="!messages.length && !isTyping" :description="t('chat.sendToStart')" :image-size="80" />
      </div>

      <div style="display: flex; gap: 8px; padding-top: 12px; border-top: 1px solid var(--theme-border-light)">
        <el-input
          v-model="inputMsg"
          :placeholder="t('chat.typeMessage')"
          @keyup.enter="sendMessage"
          :disabled="sending"
        />
        <el-button type="primary" @click="sendMessage" :loading="sending" :disabled="!inputMsg.trim()">
          {{ t('chat.sendMessage') }}
        </el-button>
        <el-button
          :type="isRecording ? 'danger' : 'default'"
          :icon="isRecording ? 'VideoPause' : 'Microphone'"
          circle
          @click="toggleVoice"
          :loading="voiceProcessing"
          :title="isRecording ? t('voice.recording') : t('voice.record')"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElNotification } from 'element-plus'
import { chatApi, voiceApi } from '../api'
import { useChatWS } from '../composables/useChatWS'
import { useAudioRecorder } from '../composables/useAudioRecorder'
import AudioPlayer from '../components/AudioPlayer.vue'
import type { Conversation, ConversationMessage } from '../types'

const { t } = useI18n()
const conversations = ref<Conversation[]>([])
const messages = ref<ConversationMessage[]>([])
const currentConvId = ref('')
const inputMsg = ref('')
const sending = ref(false)
const convLoading = ref(false)
const isTyping = ref(false)
const scrollRef = ref<HTMLElement>()

// Voice
const { isRecording, audioBlob, startRecording, stopRecording } = useAudioRecorder()
const voiceProcessing = ref(false)
const ttsAudioUrl = ref<string | null>(null)

async function toggleVoice() {
  if (isRecording.value) {
    stopRecording()
  } else {
    await startRecording()
  }
}

watch(audioBlob, async (blob) => {
  if (!blob) return
  voiceProcessing.value = true
  try {
    const sttResult = await voiceApi.stt(new File([blob], 'recording.webm', { type: 'audio/webm' }))
    const transcript = sttResult.data.transcript
    if (!transcript) return

    // Populate input and send as chat message
    inputMsg.value = transcript
    await sendMessage()
  } catch (err) {
    console.error('Voice processing failed:', err)
  } finally {
    voiceProcessing.value = false
  }
})

// WebSocket via composable
const { status: wsStatus, connect: connectWs, sendChatMessage } = useChatWS({
  onMessage: handleWsMessage,
})

function handleWsMessage(data: { type: string; [key: string]: unknown }) {
  switch (data.type) {
    case 'typing':
      isTyping.value = true
      nextTick(scrollToBottom)
      break
    case 'message':
      isTyping.value = false
      sending.value = false
      const convId = data.conversation_id as string | undefined
      if (convId && !currentConvId.value) {
        currentConvId.value = convId
        loadConversations()
      }
      messages.value.push({
        id: `ws-${Date.now()}`,
        role: data.role as string,
        content: data.content as string,
      })
      nextTick(scrollToBottom)
      break
    case 'notification':
      ElNotification({
        title: (data.data as Record<string, unknown> | undefined)?.title as string || t('common.notification'),
        message: (data.data as Record<string, unknown> | undefined)?.message as string || '',
        type: 'info',
        duration: 5000,
      })
      break
    case 'task_status':
      // Optionally show a notification
      break
    case 'error':
      isTyping.value = false
      sending.value = false
      ElMessage.error(data.message as string || t('chat.failedToSend'))
      break
  }
}

async function loadConversations() {
  convLoading.value = true
  try {
    const res = await chatApi.listConversations()
    conversations.value = res.data || []
  } catch { /* silent */ }
  finally { convLoading.value = false }
}

async function loadConversation(id: string) {
  currentConvId.value = id
  try {
    const res = await chatApi.getConversation(id)
    messages.value = res.messages || []
  } catch {
    ElMessage.error(t('chat.failedToLoad'))
  }
  await nextTick()
  scrollToBottom()
}

function newConversation() {
  currentConvId.value = ''
  messages.value = []
}

async function sendMessage() {
  const text = inputMsg.value.trim()
  if (!text || sending.value) return
  sending.value = true
  inputMsg.value = ''

  // Optimistically show user message
  messages.value.push({
    id: `temp-${Date.now()}`,
    role: 'user',
    content: text,
  })
  await nextTick()
  scrollToBottom()

  // Try WebSocket first, fall back to HTTP
  if (wsStatus.value === 'connected') {
    sendChatMessage(text, currentConvId.value || undefined)
  } else {
    // HTTP fallback
    try {
      const res = await chatApi.send({
        message: text,
        conversation_id: currentConvId.value || undefined,
      })
      const reply: ConversationMessage = {
        id: `reply-${Date.now()}`,
        role: 'assistant',
        content: res.reply || t('chat.noResponse'),
      }
      messages.value.push(reply)

      const convId = res.conversation_id
      if (convId && !currentConvId.value) {
        currentConvId.value = convId
        loadConversations()
      }
    } catch {
      ElMessage.error(t('chat.failedToSend'))
    } finally {
      sending.value = false
      await nextTick()
      scrollToBottom()
    }
  }
}

function scrollToBottom() {
  if (scrollRef.value) {
    scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  }
}

onMounted(() => {
  loadConversations()
  connectWs()
})
</script>

<style scoped>
.conv-item {
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}
.conv-item:hover { background: var(--theme-hover-bg); }
.conv-item.active { background: var(--theme-active-bg); color: var(--theme-color-primary); font-weight: 600; }

.msg-bubble {
  margin-bottom: 12px;
  max-width: 70%;
  padding: 10px 14px;
  border-radius: 8px;
  line-height: 1.5;
}
.msg-bubble.user {
  margin-left: auto;
  background: var(--theme-chat-user-bg);
  color: var(--theme-chat-user-text);
  text-align: right;
}
.msg-bubble.assistant {
  margin-right: auto;
  background: var(--theme-chat-assistant-bg);
  color: var(--theme-chat-assistant-text);
}
.msg-role { font-size: 11px; opacity: 0.7; margin-bottom: 4px; }
.msg-content { white-space: pre-wrap; word-break: break-word; }

/* WebSocket status bar */
.ws-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 12px;
  border-radius: 4px;
  margin-bottom: 8px;
}
.ws-status.connecting {
  background: var(--theme-status-connecting-bg);
  color: var(--theme-status-connecting-text);
}
.ws-status.disconnected {
  background: var(--theme-status-disconnected-bg);
  color: var(--theme-status-disconnected-text);
}
.ws-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

/* Typing indicator */
.typing-indicator .typing-dots {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}
.typing-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--theme-color-info);
  animation: typing-bounce 1.4s infinite ease-in-out;
}
.typing-dots span:nth-child(1) { animation-delay: 0s; }
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
