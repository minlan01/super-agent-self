import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'

export const useNotificationStore = defineStore('notification', {
  state: () => ({
    loadingCount: 0,
    lastError: null as string | null,
  }),

  getters: {
    isLoading: (state) => state.loadingCount > 0,
  },

  actions: {
    startLoading() {
      this.loadingCount++
    },

    stopLoading() {
      if (this.loadingCount > 0) this.loadingCount--
    },

    notifySuccess(message: string) {
      ElNotification({ title: 'Success', message, type: 'success', duration: 3000 })
    },

    notifyError(message: string) {
      this.lastError = message
      ElNotification({ title: 'Error', message, type: 'error', duration: 5000 })
    },

    clearError() {
      this.lastError = null
    },
  },
})
