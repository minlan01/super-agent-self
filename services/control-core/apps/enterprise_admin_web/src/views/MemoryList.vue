<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; gap: 10px">
      <el-input v-model="keyword" :placeholder="t('memory.searchMemories')" clearable style="width: 300px" @keyup.enter="search" />
      <el-select v-model="memoryType" :placeholder="t('common.type')" clearable style="width: 200px" @change="loadMemories">
        <el-option v-for="mt in memoryTypes" :key="mt" :label="mt" :value="mt" />
      </el-select>
      <el-button type="primary" @click="search">{{ t('common.search') }}</el-button>
    </div>

    <el-table :data="memories" stripe v-loading="loading">
      <el-table-column prop="title" :label="t('memory.title')" show-overflow-tooltip />
      <el-table-column prop="memory_type" :label="t('common.type')" width="180">
        <template #default="{ row }">
          <el-tag size="small">{{ row.memory_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="summary" :label="t('memory.summary')" show-overflow-tooltip />
      <el-table-column :label="t('memory.importance')" width="110">
        <template #default="{ row }">
          <el-progress :percentage="Math.round(row.importance_score * 100)" :stroke-width="8" style="width: 80px" />
        </template>
      </el-table-column>
      <el-table-column prop="confidence_score" :label="t('memory.confidence')" width="100">
        <template #default="{ row }">{{ (row.confidence_score * 100).toFixed(0) }}%</template>
      </el-table-column>
      <el-table-column :label="t('memory.active')" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? t('common.yes') : t('common.no') }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.created')" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="140">
        <template #default="{ row }">
          <el-button size="small" type="warning" @click="handleDisable(row)" v-if="row.is_active">{{ t('skill.disable') }}</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMemories, searchMemories, disableMemory, deleteMemory } from '../api'
import { formatTime } from '@/utils/format'
import type { Memory } from '../types'

const { t } = useI18n()

const memoryTypes = [
  'execution_experience', 'workflow_pattern', 'domain_knowledge',
  'error_solution', 'user_preference',
]

const memories = ref<Memory[]>([])
const loading = ref(false)
const keyword = ref('')
const memoryType = ref('')


async function loadMemories() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, page_size: 50 }
    if (memoryType.value) params.memory_type = memoryType.value
    const res = await getMemories(params)
    memories.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function search() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { limit: 50 }
    if (keyword.value) params.keyword = keyword.value
    if (memoryType.value) params.memory_type = memoryType.value
    const res = await searchMemories(params)
    memories.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function handleDisable(memory: Memory) {
  await ElMessageBox.confirm(t('memory.disableConfirm'), t('common.confirm'))
  await disableMemory(memory.id)
  ElMessage.success(t('memory.disabled'))
  loadMemories()
}

async function handleDelete(memory: Memory) {
  await ElMessageBox.confirm(t('memory.deleteConfirm'), t('common.confirm'), { type: 'warning' })
  await deleteMemory(memory.id)
  ElMessage.success(t('memory.deleted'))
  loadMemories()
}

onMounted(loadMemories)
</script>
