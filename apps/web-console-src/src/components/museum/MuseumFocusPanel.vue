<script setup lang="ts">
import { ref, computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useOfficeStore } from '@/stores/office'
import { useSessionStore } from '@/stores/session'
import { useChatStore } from '@/stores/chat'
import { formatRelativeTime } from '@/utils/format'
import { getErrorMessage } from '@/utils/error'
import {
  AddOutline,
  ChatbubblesOutline,
  TrashOutline,
  CheckmarkOutline,
  CloseOutline,
} from '@vicons/ionicons5'
import {
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NButton,
  NSpace,
  NIcon,
  useMessage,
} from 'naive-ui'

const props = defineProps<{
  selectedCharacterId: string | null
  selectedCharacterPosition: { x: number; y: number } | null
  visible: boolean
  agents: Array<{ id: string; name?: string }>
}>()

const emit = defineEmits<{
  sessionSelected: [sessionKey: string]
  close: []
}>()

const { t } = useI18n()
const officeStore = useOfficeStore()
const sessionStore = useSessionStore()
const chatStore = useChatStore()
const message = useMessage()

const showCreateModal = ref(false)
const creating = ref(false)
const createForm = ref({
  agentId: '',
  channel: 'main',
  peer: '',
  label: '',
})

const isDeleteMode = ref(false)
const selectedSessionKeys = shallowRef<Set<string>>(new Set())

watch(() => props.visible, (vis) => {
  if (!vis) {
    isDeleteMode.value = false
    selectedSessionKeys.value = new Set()
  }
})

const channelOptions = [
  { label: 'Main', value: 'main' },
  { label: 'WhatsApp', value: 'whatsapp' },
  { label: 'Telegram', value: 'telegram' },
  { label: 'Discord', value: 'discord' },
  { label: 'Slack', value: 'slack' },
]

const selectedAgentSessions = computed(() => {
  if (!props.selectedCharacterId) return []
  return sessionStore.sessions
    .filter(s => s.agentId === props.selectedCharacterId)
    .sort((a, b) => new Date(b.lastActivity).getTime() - new Date(a.lastActivity).getTime())
})

function openCreateModal() {
  createForm.value = {
    agentId: props.selectedCharacterId || 'main',
    channel: 'main',
    peer: '',
    label: '',
  }
  showCreateModal.value = true
}

async function handleCreateSession() {
  creating.value = true
  try {
    await sessionStore.createSession({
      agentId: createForm.value.agentId || 'main',
      channel: createForm.value.channel || 'main',
      peer: createForm.value.peer || undefined,
      label: createForm.value.label || undefined,
    })
    await new Promise(resolve => setTimeout(resolve, 500))
    await sessionStore.fetchSessions()
    message.success(t('pages.sessions.list.createSuccess'))
    showCreateModal.value = false
  } catch (e: unknown) {
    message.error(getErrorMessage(e) || t('pages.sessions.list.createFailed'))
  } finally {
    creating.value = false
  }
}

function toggleDeleteMode() {
  isDeleteMode.value = !isDeleteMode.value
  if (!isDeleteMode.value) {
    selectedSessionKeys.value = new Set()
  }
}

function toggleSessionSelection(sessionKey: string) {
  if (selectedSessionKeys.value.has(sessionKey)) {
    const newKeys = new Set(selectedSessionKeys.value)
    newKeys.delete(sessionKey)
    selectedSessionKeys.value = newKeys
  } else {
    selectedSessionKeys.value = new Set([...selectedSessionKeys.value, sessionKey])
  }
}

async function handleDeleteSelectedSessions() {
  if (selectedSessionKeys.value.size === 0) return

  try {
    for (const key of selectedSessionKeys.value) {
      await sessionStore.deleteSession(key)
    }
    await new Promise(resolve => setTimeout(resolve, 500))
    await sessionStore.fetchSessions()
    message.success(t('pages.sessions.list.deleteSuccess'))
    selectedSessionKeys.value = new Set()
    isDeleteMode.value = false
  } catch (e: unknown) {
    message.error(getErrorMessage(e) || t('pages.sessions.list.deleteFailed'))
  }
}

async function handleDeleteSession(sessionKey: string) {
  try {
    await sessionStore.deleteSession(sessionKey)
    await new Promise(resolve => setTimeout(resolve, 500))
    await sessionStore.fetchSessions()
    message.success(t('pages.sessions.list.deleteSuccess'))
  } catch (e: unknown) {
    message.error(getErrorMessage(e) || t('pages.sessions.list.deleteFailed'))
  }
}

function handleSessionClick(sessionKey: string) {
  officeStore.selectSession(sessionKey)
  chatStore.setSessionKey(sessionKey)
  chatStore.fetchHistory(sessionKey)
  emit('sessionSelected', sessionKey)
}

function handleClose() {
  isDeleteMode.value = false
  selectedSessionKeys.value = new Set()
  emit('close')
}
</script>

<template>
  <!-- Session List Popup -->
  <Transition name="fade">
    <div
      v-if="visible && selectedCharacterPosition"
      class="session-list-popup"
      :style="{
        left: `${selectedCharacterPosition.x}px`,
        top: `${selectedCharacterPosition.y}px`,
      }"
      @click.stop
      @wheel.stop
    >
      <div class="popup-header">
        <span class="popup-title">{{ agents.find(a => a.id === selectedCharacterId)?.name }} - {{ t('myworld.skillsList') }}</span>
        <div class="popup-actions">
          <button v-if="!isDeleteMode" class="popup-add" @click="openCreateModal" :title="t('pages.sessions.list.createModal.title')">
            <NIcon :component="AddOutline" :size="16" />
          </button>
          <button v-if="!isDeleteMode && selectedAgentSessions.length > 0" class="popup-delete" @click="toggleDeleteMode" :title="t('common.delete')">
            <NIcon :component="TrashOutline" :size="16" />
          </button>
          <template v-if="isDeleteMode">
            <button class="popup-confirm" @click="handleDeleteSelectedSessions" :disabled="selectedSessionKeys.size === 0" :title="t('common.confirm')">
              <NIcon :component="CheckmarkOutline" :size="16" />
            </button>
            <button class="popup-cancel" @click="toggleDeleteMode" :title="t('common.cancel')">
              <NIcon :component="CloseOutline" :size="16" />
            </button>
          </template>
          <button class="popup-close" @click="handleClose" :title="t('myworld.popup.close')">x</button>
        </div>
      </div>
      <div class="popup-content">
        <div v-if="selectedAgentSessions.length === 0" class="empty-sessions">
          <p>{{ t('myworld.popup.noSessions') }}</p>
        </div>
        <div
          v-for="session in selectedAgentSessions"
          :key="session.key"
          class="session-item"
          :class="{
            'selected-for-delete': selectedSessionKeys.has(session.key),
            'delete-mode': isDeleteMode
          }"
          @click="isDeleteMode ? toggleSessionSelection(session.key) : handleSessionClick(session.key)"
        >
          <div v-if="isDeleteMode" class="session-checkbox" :class="{ checked: selectedSessionKeys.has(session.key) }">
            <NIcon v-if="selectedSessionKeys.has(session.key)" :component="CheckmarkOutline" :size="12" />
          </div>
          <div class="session-icon">
            <NIcon :component="ChatbubblesOutline" :size="14" />
          </div>
          <div class="session-info">
            <span class="session-name">{{ session.label || session.key.split(':').pop() }}</span>
            <span class="session-time">{{ session.messageCount }}条消息 · {{ formatRelativeTime(session.lastActivity) }}</span>
          </div>
          <div v-if="!isDeleteMode" class="session-arrow">&rarr;</div>
          <button v-if="isDeleteMode" class="session-delete-btn" @click.stop="handleDeleteSession(session.key)">
            <NIcon :component="TrashOutline" :size="14" />
          </button>
        </div>
      </div>
    </div>
  </Transition>

  <!-- Create Session Modal -->
  <NModal
    v-model:show="showCreateModal"
    preset="card"
    :title="t('pages.sessions.list.createModal.title')"
    style="width: 500px; max-width: 90vw;"
    :mask-closable="false"
  >
    <NForm label-placement="left" label-width="80">
      <NFormItem :label="t('pages.sessions.list.createModal.channel')">
        <NSelect
          v-model:value="createForm.channel"
          :options="channelOptions"
          :placeholder="t('pages.sessions.list.createModal.channelPlaceholder')"
        />
      </NFormItem>
      <NFormItem :label="t('pages.sessions.list.createModal.peer')">
        <NInput
          v-model:value="createForm.peer"
          :placeholder="t('pages.sessions.list.createModal.peerPlaceholder')"
        />
      </NFormItem>
      <NFormItem :label="t('pages.sessions.list.createModal.label')">
        <NInput
          v-model:value="createForm.label"
          :placeholder="t('pages.sessions.list.createModal.labelPlaceholder')"
        />
      </NFormItem>
    </NForm>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="showCreateModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="primary" :loading="creating" @click="handleCreateSession">
          {{ t('common.create') }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.session-list-popup {
  position: fixed;
  width: 280px;
  max-height: 400px;
  background: rgba(15, 23, 42, 0.98);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  box-shadow:
    0 20px 40px rgba(0, 0, 0, 0.4),
    0 0 0 1px rgba(255, 255, 255, 0.05);
  z-index: 300;
  overflow: hidden;
  transform-origin: left center;
}

.popup-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: rgba(59, 130, 246, 0.1);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.popup-title {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
}

.popup-add {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(59, 130, 246, 0.2);
  border: none;
  border-radius: 6px;
  color: #60a5fa;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s ease;
}

.popup-add:hover {
  background: rgba(59, 130, 246, 0.3);
  color: #93c5fd;
}

.popup-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.popup-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(239, 68, 68, 0.2);
  border: none;
  border-radius: 6px;
  color: #f87171;
  cursor: pointer;
  transition: all 0.2s ease;
}

.popup-delete:hover {
  background: rgba(239, 68, 68, 0.3);
  color: #fca5a5;
}

.popup-confirm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(34, 197, 94, 0.2);
  border: none;
  border-radius: 6px;
  color: #4ade80;
  cursor: pointer;
  transition: all 0.2s ease;
}

.popup-confirm:hover:not(:disabled) {
  background: rgba(34, 197, 94, 0.3);
  color: #86efac;
}

.popup-confirm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.popup-cancel {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(156, 163, 175, 0.2);
  border: none;
  border-radius: 6px;
  color: #9ca3af;
  cursor: pointer;
  transition: all 0.2s ease;
}

.popup-cancel:hover {
  background: rgba(156, 163, 175, 0.3);
  color: #d1d5db;
}

.popup-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 6px;
  color: #94a3b8;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s ease;
}

.popup-close:hover {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.popup-content {
  max-height: 340px;
  overflow-y: auto;
  padding: 8px;
}

.empty-sessions {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100px;
  color: #64748b;
  font-size: 13px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  margin-bottom: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.session-item:last-child {
  margin-bottom: 0;
}

.session-item:hover {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
  transform: translateX(4px);
}

.session-item.delete-mode:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
}

.session-item.selected-for-delete {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
}

.session-checkbox {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  flex-shrink: 0;
  transition: all 0.2s ease;
}

.session-checkbox.checked {
  background: #ef4444;
  border-color: #ef4444;
  color: #fff;
}

.session-delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: rgba(239, 68, 68, 0.2);
  border: none;
  border-radius: 6px;
  color: #f87171;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.session-delete-btn:hover {
  background: rgba(239, 68, 68, 0.4);
  color: #fff;
}

.session-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(59, 130, 246, 0.1) 100%);
  border-radius: 8px;
  color: #60a5fa;
  flex-shrink: 0;
}

.session-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.session-name {
  font-size: 13px;
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-time {
  font-size: 11px;
  color: #64748b;
}

.session-arrow {
  font-size: 14px;
  color: #475569;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.session-item:hover .session-arrow {
  color: #60a5fa;
  transform: translateX(2px);
}

.fade-enter-active,
.fade-leave-active {
  transition: all 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: scale(0.95) translateY(-10px);
}
</style>
