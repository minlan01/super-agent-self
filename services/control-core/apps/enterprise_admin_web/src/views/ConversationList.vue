<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between">
      <span style="color: var(--theme-text-secondary); font-size: 13px">{{ t('chat.totalConversations', { count: conversations.length }) }}</span>
      <el-button @click="loadConversations">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="conversations" stripe v-loading="loading">
      <el-table-column prop="id" :label="t('common.id')" width="280" show-overflow-tooltip />
      <el-table-column prop="user_id" :label="t('conversation.userId')" width="220" show-overflow-tooltip />
      <el-table-column prop="title" :label="t('common.name')" show-overflow-tooltip>
        <template #default="{ row }">{{ row.title || '-' }}</template>
      </el-table-column>
      <el-table-column prop="edition" :label="t('common.edition')" width="120">
        <template #default="{ row }">
          <el-tag :type="row.edition === 'enterprise' ? 'primary' : 'success'" size="small">{{ row.edition }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.created')" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="$router.push(`/chat?conv=${row.id}`)">{{ t('common.view') }}</el-button>
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
import { chatApi } from '../api'
import { formatTime } from '@/utils/format'
import type { Conversation } from '../types'

const { t } = useI18n()

const conversations = ref<Conversation[]>([])
const loading = ref(false)


async function loadConversations() {
  loading.value = true
  try {
    const res = await chatApi.listConversations()
    conversations.value = res.data || []
  } finally {
    loading.value = false
  }
}

async function handleDelete(row: Conversation) {
  await ElMessageBox.confirm(
    t('conversation.deleteConfirm', { title: row.title || row.id.slice(0, 8) }),
    t('common.confirm'),
    { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' }
  )
  try {
    await chatApi.deleteConversation(row.id)
    ElMessage.success(t('conversation.deleted'))
    loadConversations()
  } catch {
    ElMessage.error(t('conversation.deleteFailed'))
  }
}

onMounted(loadConversations)
</script>
