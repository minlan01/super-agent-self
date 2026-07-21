<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; gap: 10px">
      <el-select v-model="statusFilter" :placeholder="t('common.status')" clearable style="width: 160px" @change="loadSkills">
        <el-option :label="t('skill.candidate')" value="candidate" />
        <el-option :label="t('skill.stable')" value="stable" />
        <el-option :label="t('skill.disable')" value="disabled" />
        <el-option :label="t('skill.deprecated')" value="deprecated" />
      </el-select>
    </div>

    <el-table :data="skills" stripe v-loading="loading">
      <el-table-column prop="name" :label="t('common.name')" width="200">
        <template #default="{ row }">
          <el-link type="primary" @click="router.push(`/skills/${row.id}`)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="description" :label="t('common.description')" show-overflow-tooltip />
      <el-table-column prop="version" :label="t('common.version')" width="90" />
      <el-table-column prop="status" :label="t('common.status')" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('skill.successRate')" width="120">
        <template #default="{ row }">{{ (row.success_rate * 100).toFixed(0) }}%</template>
      </el-table-column>
      <el-table-column prop="total_runs" :label="t('skill.runs')" width="80" />
      <el-table-column :label="t('common.created')" width="160">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="200">
        <template #default="{ row }">
          <el-button size="small" type="success" @click="handleApprove(row)" v-if="row.status === 'candidate'">{{ t('skill.approve') }}</el-button>
          <el-button size="small" type="warning" @click="handleDisable(row)" v-if="row.status === 'stable'">{{ t('skill.disable') }}</el-button>
          <el-button size="small" type="primary" @click="handleRollback(row)" v-if="row.status === 'disabled'">{{ t('skill.rollback') }}</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSkills, approveSkill, disableSkill, rollbackSkill } from '../api'
import { formatTime } from '@/utils/format'
import { skillStatusType as statusType } from '@/utils/status'
import { useAsyncData } from '@/composables/useAsyncData'
import type { Skill } from '../types'

const { t } = useI18n()
const router = useRouter()
const statusFilter = ref('')

const { data: skills, loading, execute: loadSkills } = useAsyncData<Skill[]>(async () => {
  const params: Record<string, unknown> = { page: 1, page_size: 50 }
  if (statusFilter.value) params.status = statusFilter.value
  const res = await getSkills(params)
  return res.data || []
}, [])

async function handleApprove(skill: Skill) {
  await ElMessageBox.confirm(t('skill.approveConfirm', { name: skill.name }), t('common.confirm'))
  await approveSkill(skill.id)
  ElMessage.success(t('skill.approved'))
  loadSkills()
}

async function handleDisable(skill: Skill) {
  await ElMessageBox.confirm(t('skill.disableConfirm', { name: skill.name }), t('common.confirm'))
  await disableSkill(skill.id)
  ElMessage.success(t('skill.disabled'))
  loadSkills()
}

async function handleRollback(skill: Skill) {
  await ElMessageBox.confirm(t('skill.rollbackConfirm', { name: skill.name }), t('common.confirm'))
  await rollbackSkill(skill.id)
  ElMessage.success(t('skill.rolledBack'))
  loadSkills()
}

onMounted(loadSkills)
</script>
