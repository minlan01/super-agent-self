import { defineStore } from 'pinia'
import { getTasks, getTask } from '../api'
import type { Task } from '../types'

export const useTaskStore = defineStore('task', {
  state: () => ({
    tasks: [] as Task[],
    currentTask: null as Task | null,
    totalTasks: 0,
  }),

  actions: {
    async fetchTasks(params?: Record<string, unknown>) {
      const res: any = await getTasks(params)
      this.tasks = res.data?.items || res.data || []
      this.totalTasks = res.data?.total || this.tasks.length
    },

    async fetchTask(id: string) {
      const res: any = await getTask(id)
      this.currentTask = res.data || res
    },

    clearCurrentTask() {
      this.currentTask = null
    },
  },
})
