<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" :style="{ background: 'var(--theme-sidebar-bg)' }">
      <div style="padding: 20px; text-align: center; color: #fff; font-size: 16px; font-weight: bold">
        {{ t('app.title') }}
      </div>
      <el-menu
        :default-active="route.path"
        router
        background-color="var(--theme-sidebar-bg)"
        text-color="var(--theme-sidebar-text)"
        active-text-color="var(--theme-sidebar-active)"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <span>{{ t('nav.dashboard') }}</span>
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>{{ t('nav.chat') }}</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <span>{{ t('nav.tasks') }}</span>
        </el-menu-item>
        <el-menu-item index="/task-dag">
          <el-icon><Share /></el-icon>
          <span>{{ t('nav.taskDag') }}</span>
        </el-menu-item>
        <el-menu-item index="/audit">
          <el-icon><Document /></el-icon>
          <span>{{ t('nav.audit') }}</span>
        </el-menu-item>
        <el-menu-item index="/memory">
          <el-icon><Collection /></el-icon>
          <span>{{ t('nav.memory') }}</span>
        </el-menu-item>
        <el-menu-item index="/skills">
          <el-icon><MagicStick /></el-icon>
          <span>{{ t('nav.skills') }}</span>
        </el-menu-item>
        <el-menu-item index="/approvals">
          <el-badge :value="pendingApprovalCount" :hidden="pendingApprovalCount === 0" :max="99">
            <el-icon><Select /></el-icon>
          </el-badge>
          <span>{{ t('nav.approvals') }}</span>
        </el-menu-item>
        <el-menu-item index="/cron">
          <el-icon><Timer /></el-icon>
          <span>{{ t('nav.cron') }}</span>
        </el-menu-item>
        <el-menu-item index="/conversations">
          <el-icon><ChatLineSquare /></el-icon>
          <span>{{ t('nav.conversations') }}</span>
        </el-menu-item>
        <el-menu-item index="/export">
          <el-icon><Download /></el-icon>
          <span>{{ t('nav.export') }}</span>
        </el-menu-item>
        <el-menu-item index="/health">
          <el-icon><Monitor /></el-icon>
          <span>{{ t('nav.health') }}</span>
        </el-menu-item>
        <el-menu-item index="/analytics">
          <el-icon><TrendCharts /></el-icon>
          <span>{{ t('nav.analytics') }}</span>
        </el-menu-item>
        <el-menu-item index="/templates">
          <el-icon><DocumentCopy /></el-icon>
          <span>{{ t('nav.templates') }}</span>
        </el-menu-item>
        <el-menu-item index="/rbac">
          <el-icon><Lock /></el-icon>
          <span>RBAC Management</span>
        </el-menu-item>
        <el-menu-item index="/agents">
          <el-icon><User /></el-icon>
          <span>{{ t('nav.agents') }}</span>
        </el-menu-item>
        <el-menu-item index="/scenarios">
          <el-icon><VideoPlay /></el-icon>
          <span>{{ t('nav.scenarios') }}</span>
        </el-menu-item>
        <el-menu-item index="/monitoring">
          <el-icon><DataLine /></el-icon>
          <span>{{ t('nav.monitoring') }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header :style="headerStyle">
        <h3 style="margin: 0; color: var(--theme-text-primary)">{{ pageTitle }}</h3>
        <GlobalSearch />
        <div style="display: flex; align-items: center; gap: 12px">
          <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
            <el-button text @click="showNotifications = true" style="padding: 4px 8px">
              <el-icon :size="18"><Bell /></el-icon>
            </el-button>
          </el-badge>
          <el-tooltip :content="theme === 'dark' ? t('theme.light') : t('theme.dark')" placement="bottom">
            <el-button
              text
              size="small"
              @click="toggleTheme"
              style="padding: 4px 8px"
            >
              <el-icon :size="18">
                <Sunny v-if="theme === 'dark'" />
                <Moon v-else />
              </el-icon>
            </el-button>
          </el-tooltip>
          <el-button
            text
            size="small"
            @click="toggleLocale"
            style="font-size: 13px; min-width: auto; padding: 4px 8px"
          >
            {{ locale === 'zh' ? 'EN' : '中文' }}
          </el-button>
          <span v-if="authStore.user" style="color: var(--theme-text-regular); font-size: 13px">{{ authStore.user.username }}</span>
          <el-button text type="danger" @click="handleLogout">{{ t('auth.logout') }}</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>

    <NotificationPanel v-model="showNotifications" />
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { DataAnalysis, List, Document, Collection, MagicStick, Select, Timer, ChatDotRound, ChatLineSquare, Download, Monitor, TrendCharts, Bell, Sunny, Moon, DocumentCopy, Share, Lock, User, VideoPlay, DataLine } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import { notificationApi, getApprovals } from '../api/index'
import NotificationPanel from '../views/NotificationPanel.vue'
import GlobalSearch from './GlobalSearch.vue'
import { useTheme } from '../theme'
import { useNotificationWS } from '../composables/useNotificationWS'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { t, locale } = useI18n()
const { theme, toggleTheme } = useTheme()
const { unreadCount: wsUnreadCount, connect: connectNotificationWS, disconnect: disconnectNotificationWS, setUnread } = useNotificationWS()

const showNotifications = ref(false)
const pendingApprovalCount = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null
let approvalPollTimer: ReturnType<typeof setInterval> | null = null

// Derive unreadCount from the global WS composable so the badge is always current
const unreadCount = computed(() => wsUnreadCount.value)

const headerStyle = computed(() => ({
  background: 'var(--theme-header-bg)',
  borderBottom: '1px solid var(--theme-header-border)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
}))

function toggleLocale() {
  const newLocale = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = newLocale
  localStorage.setItem('locale', newLocale)
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

async function pollUnreadCount() {
  try {
    const res = await notificationApi.unreadCount()
    setUnread(res.count || 0)
  } catch {
    // silent
  }
}

async function fetchPendingApprovalCount() {
  try {
    const res = await getApprovals({ status: 'pending', page: 1, page_size: 1 })
    pendingApprovalCount.value = (res as any).total || 0
  } catch {
    pendingApprovalCount.value = 0
  }
}

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    '/dashboard': t('page.dashboard'),
    '/tasks': t('page.taskManagement'),
    '/audit': t('page.auditLog'),
    '/memory': t('page.memoryManagement'),
    '/skills': t('page.skillManagement'),
    '/approvals': t('page.approvalCenter'),
    '/cron': t('page.cronJobs'),
    '/chat': t('page.chat'),
    '/conversations': t('page.conversations'),
    '/export': t('page.exportData'),
    '/health': t('page.systemHealth'),
    '/analytics': t('page.analytics'),
    '/task-dag': t('page.taskDag'),
    '/templates': t('page.templates'),
    '/rbac': 'RBAC Management',
    '/agents': t('nav.agents'),
    '/scenarios': t('nav.scenarios'),
    '/monitoring': t('nav.monitoring'),
  }
  if (route.path.startsWith('/tasks/')) return t('page.taskDetail')
  if (route.path.startsWith('/agents/')) return t('nav.agents')
  if (route.path.startsWith('/scenarios/')) return t('nav.scenarios')
  return titles[route.path] || t('page.dashboard')
})

onMounted(() => {
  // Initial REST fetch to seed the count
  pollUnreadCount()
  // Connect global notification WebSocket for real-time updates
  connectNotificationWS()
  // REST polling as fallback every 120 seconds
  pollTimer = setInterval(pollUnreadCount, 120000)
  // Poll pending approval count every 60 seconds
  fetchPendingApprovalCount()
  approvalPollTimer = setInterval(fetchPendingApprovalCount, 60000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (approvalPollTimer) {
    clearInterval(approvalPollTimer)
    approvalPollTimer = null
  }
  disconnectNotificationWS()
})
</script>
