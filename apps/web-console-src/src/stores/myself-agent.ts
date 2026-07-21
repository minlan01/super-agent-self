/**
 * myself-agent Pinia Store
 *
 * 管理模式:
 * - 大数据对象 (tasks/skills/memories/cronJobs) → shallowRef（整对象替换）
 * - 简单状态 (connected/connecting/error) → ref
 */

import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import {
  checkMyselfConnection,
  myselfTasks,
  myselfSkills,
  myselfMemory,
  myselfCron,
  myselfHealth,
  type MyselfTask,
  type MyselfSkill,
  type MyselfMemory,
  type MyselfCronJob,
  type MyselfMetrics,
  type MyselfHealthStatus,
} from '@/api/myself-agent'

export const useMyselfAgentStore = defineStore('myself-agent', () => {
  // ── 连接状态 ────────────────────────────────────────────────────────────
  const connected = ref(false)
  const connecting = ref(false)
  const error = ref<string | null>(null)
  const version = ref<string>('')
  const lastCheckTime = ref<number>(0)

  // ── 数据 (shallowRef 不可变模式) ────────────────────────────────────────
  const tasks = shallowRef<MyselfTask[]>([])
  const skills = shallowRef<MyselfSkill[]>([])
  const memories = shallowRef<MyselfMemory[]>([])
  const cronJobs = shallowRef<MyselfCronJob[]>([])
  const metrics = shallowRef<MyselfMetrics | null>(null)
  const healthStatus = shallowRef<MyselfHealthStatus | null>(null)

  // ── 计算属性 ────────────────────────────────────────────────────────────
  const taskCount = computed(() => tasks.value.length)
  const activeTaskCount = computed(() =>
    tasks.value.filter((t) => t.status !== 'completed' && t.status !== 'cancelled').length,
  )
  const pendingTaskCount = computed(() =>
    tasks.value.filter((t) => t.status === 'pending').length,
  )
  const skillCount = computed(() => skills.value.length)
  const memoryCount = computed(() => memories.value.length)
  const activeCronCount = computed(() => cronJobs.value.filter((j) => j.enabled).length)

  // ── 方法 ────────────────────────────────────────────────────────────────

  async function checkConnection(): Promise<boolean> {
    connecting.value = true
    error.value = null
    try {
      const result = await checkMyselfConnection()
      connected.value = result.connected
      version.value = result.version || ''
      lastCheckTime.value = Date.now()
      if (!result.connected) {
        error.value = result.error || 'myself-agent 不可达'
      }
      return result.connected
    } catch (err) {
      connected.value = false
      error.value = String(err)
      return false
    } finally {
      connecting.value = false
    }
  }

  async function fetchHealth() {
    const { success, data } = await myselfHealth.check()
    if (success && data) {
      healthStatus.value = data
    }
  }

  async function fetchMetrics() {
    const { success, data } = await myselfHealth.metrics()
    if (success && data) {
      metrics.value = data
    }
  }

  async function fetchTasks() {
    const { success, data } = await myselfTasks.list()
    if (success && data) {
      tasks.value = data
    }
  }

  async function fetchSkills() {
    const { success, data } = await myselfSkills.list()
    if (success && data) {
      skills.value = data
    }
  }

  async function fetchMemories() {
    const { success, data } = await myselfMemory.list()
    if (success && data) {
      memories.value = data
    }
  }

  async function fetchCronJobs() {
    const { success, data } = await myselfCron.list()
    if (success && data) {
      cronJobs.value = data
    }
  }

  /** 一次性获取所有数据（Dashboard 用） */
  async function fetchAll() {
    const connected_ok = await checkConnection()
    if (!connected_ok) return
    await Promise.all([
      fetchTasks(),
      fetchSkills(),
      fetchMemories(),
      fetchCronJobs(),
      fetchMetrics(),
    ])
  }

  return {
    // 状态
    connected,
    connecting,
    error,
    version,
    lastCheckTime,
    tasks,
    skills,
    memories,
    cronJobs,
    metrics,
    healthStatus,
    // 计算属性
    taskCount,
    activeTaskCount,
    pendingTaskCount,
    skillCount,
    memoryCount,
    activeCronCount,
    // 方法
    checkConnection,
    fetchHealth,
    fetchMetrics,
    fetchTasks,
    fetchSkills,
    fetchMemories,
    fetchCronJobs,
    fetchAll,
  }
})
