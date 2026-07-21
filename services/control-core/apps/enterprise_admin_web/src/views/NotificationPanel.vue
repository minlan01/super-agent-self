<template>
  <el-drawer
    v-model="visible"
    :title="t('notification.title')"
    direction="rtl"
    size="400px"
    :before-close="handleClose"
  >
    <template #header>
      <div style="display: flex; align-items: center; justify-content: space-between; width: 100%">
        <span style="font-size: 16px; font-weight: 600">{{ t('notification.title') }}</span>
        <div style="display: flex; gap: 8px">
          <el-button text size="small" @click="handleMarkAllRead" :disabled="unreadCount === 0">
            {{ t('notification.markAllRead') }}
          </el-button>
          <el-button text size="small" type="danger" @click="handleClearAll" :disabled="notifications.length === 0">
            {{ t('notification.clearAll') }}
          </el-button>
        </div>
      </div>
    </template>

    <div v-if="loading" style="text-align: center; padding: 40px 0">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <p style="color: var(--theme-text-secondary); margin-top: 8px">{{ t('common.loading') }}</p>
    </div>

    <div v-else-if="notifications.length === 0" style="text-align: center; padding: 40px 0">
      <el-empty :description="t('notification.noNotifications')" :image-size="64" />
    </div>

    <div v-else class="notification-list">
      <div
        v-for="n in notifications"
        :key="n.id"
        class="notification-item"
        :class="{ unread: !n.read }"
        @click="handleNotificationClick(n)"
      >
        <div class="notification-icon">
          <el-icon :size="20" :color="iconColor(n.type)">
            <SuccessFilled v-if="n.type === 'task_completed'" />
            <CircleCloseFilled v-else-if="n.type === 'task_failed'" />
            <Bell v-else-if="n.type === 'approval_requested'" />
            <WarningFilled v-else-if="n.type === 'system_warning'" />
            <InfoFilled v-else />
          </el-icon>
        </div>
        <div class="notification-content">
          <div class="notification-header">
            <span class="notification-title">{{ n.title }}</span>
            <span v-if="!n.read" class="unread-dot"></span>
          </div>
          <p class="notification-message">{{ n.message }}</p>
          <span class="notification-time">{{ formatTime(n.created_at) }}</span>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  Bell,
  Loading,
  SuccessFilled,
  CircleCloseFilled,
  WarningFilled,
  InfoFilled,
} from '@element-plus/icons-vue'
import { notificationApi } from '../api/index'
import type { Notification } from '../types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const router = useRouter()
const { t } = useI18n()

const visible = computed({
  get: () => props.modelValue,
  set: (val: boolean) => emit('update:modelValue', val),
})

const notifications = ref<Notification[]>([])
const unreadCount = ref(0)
const loading = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null

import { computed } from 'vue'

function handleClose() {
  visible.value = false
}

async function fetchNotifications() {
  loading.value = true
  try {
    const res = await notificationApi.list()
    notifications.value = res.data || []
    unreadCount.value = res.unread_count || 0
  } catch {
    // silent fail
  } finally {
    loading.value = false
  }
}

async function fetchUnreadCount() {
  try {
    const res = await notificationApi.unreadCount()
    unreadCount.value = res.count || 0
  } catch {
    // silent fail
  }
}

async function handleMarkAllRead() {
  try {
    await notificationApi.markAllRead()
    notifications.value.forEach(n => { n.read = true })
    unreadCount.value = 0
    ElMessage.success(t('notification.allMarkedRead'))
  } catch {
    ElMessage.error(t('notification.operationFailed'))
  }
}

async function handleClearAll() {
  try {
    await notificationApi.clear()
    notifications.value = []
    unreadCount.value = 0
    ElMessage.success(t('notification.allCleared'))
  } catch {
    ElMessage.error(t('notification.operationFailed'))
  }
}

async function handleNotificationClick(n: Notification) {
  if (!n.read) {
    try {
      await notificationApi.markRead(n.id)
      n.read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    } catch {
      // continue to navigate anyway
    }
  }

  // Navigate based on notification type
  if ((n.type === 'task_completed' || n.type === 'task_failed') && n.data?.task_id) {
    handleClose()
    router.push(`/tasks/${n.data.task_id}`)
  }
}

function iconColor(type: string): string {
  switch (type) {
    case 'task_completed': return '#67c23a'
    case 'task_failed': return '#f56c6c'
    case 'approval_requested': return '#e6a23c'
    case 'system_warning': return '#e6a23c'
    default: return '#909399'
  }
}

function formatTime(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)

  if (diffMin < 1) return t('notification.justNow')
  if (diffMin < 60) return t('notification.minutesAgo', { count: diffMin })
  const diffHours = Math.floor(diffMin / 60)
  if (diffHours < 24) return t('notification.hoursAgo', { count: diffHours })
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return t('notification.daysAgo', { count: diffDays })
  return date.toLocaleDateString()
}

onMounted(() => {
  fetchNotifications()
  // Auto-refresh every 30 seconds
  refreshTimer = setInterval(() => {
    fetchUnreadCount()
    if (visible.value) {
      fetchNotifications()
    }
  }, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

// Expose for parent to call refresh
defineExpose({ fetchNotifications, fetchUnreadCount, unreadCount })
</script>

<style scoped>
.notification-list {
  padding: 0;
}

.notification-item {
  display: flex;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--theme-border-lighter);
  cursor: pointer;
  transition: background 0.2s;
}

.notification-item:hover {
  background: var(--theme-hover-bg);
}

.notification-item.unread {
  background: var(--theme-active-bg);
}

.notification-item.unread:hover {
  background: var(--theme-active-hover-bg);
}

.notification-icon {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  padding-top: 2px;
}

.notification-content {
  flex: 1;
  min-width: 0;
}

.notification-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.notification-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--theme-text-primary);
}

.unread-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--theme-color-danger);
  flex-shrink: 0;
}

.notification-message {
  margin: 0 0 4px;
  font-size: 13px;
  color: var(--theme-text-regular);
  line-height: 1.4;
  word-break: break-word;
}

.notification-time {
  font-size: 12px;
  color: var(--theme-text-secondary);
}
</style>
