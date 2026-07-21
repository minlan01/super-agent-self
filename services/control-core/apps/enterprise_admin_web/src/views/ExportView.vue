<template>
  <div style="display: flex; flex-direction: column; gap: 16px">
    <el-card v-for="section in sections" :key="section.key">
      <template #header>
        <span style="font-weight: 600">{{ section.label }}</span>
      </template>
      <div style="display: flex; gap: 12px">
        <el-button type="primary" :loading="loading[section.key + '_json']" @click="handleExport(section.key, 'json')">
          {{ t('export.exportJson') }}
        </el-button>
        <el-button type="success" :loading="loading[section.key + '_csv']" @click="handleExport(section.key, 'csv')">
          {{ t('export.exportCsv') }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { exportApi } from '../api'

const { t } = useI18n()

const sections = computed(() => [
  { key: 'tasks', label: t('export.tasks') },
  { key: 'memories', label: t('export.memories') },
  { key: 'audit', label: t('export.auditLog') },
])

const loading = reactive<Record<string, boolean>>({})

async function handleExport(key: string, format: string) {
  const loadingKey = `${key}_${format}`
  loading[loadingKey] = true
  try {
    if (format === 'csv') {
      // Blob response -- the interceptor returns response.data which is the blob itself
      const res: any = await exportApi[key as keyof typeof exportApi](format)
      const blob = res instanceof Blob ? res : new Blob([JSON.stringify(res, null, 2)], { type: 'text/csv' })
      downloadBlob(blob, `${key}_export.csv`)
    } else {
      const res: any = await exportApi[key as keyof typeof exportApi](format)
      const data = typeof res === 'string' ? res : JSON.stringify(res, null, 2)
      const blob = new Blob([data], { type: 'application/json' })
      downloadBlob(blob, `${key}_export.json`)
    }
    ElMessage.success(t('export.exportSuccess', { key, format: format.toUpperCase() }))
  } catch {
    ElMessage.error(t('export.exportFailed', { key }))
  } finally {
    loading[loadingKey] = false
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>
