<template>
  <div v-loading="loading">
    <el-page-header @back="$router.push('/skills')" :title="t('skill.backToSkills')" :content="skill?.name || t('page.skillDetail')" />

    <div v-if="skill" style="margin-top: 20px">
      <!-- Basic info -->
      <el-descriptions :column="2" border>
        <el-descriptions-item :label="t('common.id')">{{ skill.id }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.name')">{{ skill.name }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.status')">
          <el-tag :type="statusType(skill.status)" size="small">{{ skill.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="t('common.version')">v{{ skill.version }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.edition')">{{ skill.edition }}</el-descriptions-item>
        <el-descriptions-item :label="t('skill.totalRuns')">{{ skill.total_runs }}</el-descriptions-item>
        <el-descriptions-item :label="t('skill.successRate')">
          <el-progress :percentage="Math.round(skill.success_rate * 100)" :color="rateColor" :stroke-width="16" style="width: 200px" />
        </el-descriptions-item>
        <el-descriptions-item :label="t('common.description')" :span="2">{{ skill.description || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('skill.sourceTask')">{{ skill.source_task_id || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.created')">{{ formatTime(skill.created_at) }}</el-descriptions-item>
      </el-descriptions>

      <!-- Actions -->
      <div style="margin-top: 16px; display: flex; gap: 10px">
        <el-button type="success" @click="handleApprove" v-if="skill.status === 'candidate'">{{ t('skill.approve') }}</el-button>
        <el-button type="warning" @click="handleDisable" v-if="skill.status === 'stable'">{{ t('skill.disable') }}</el-button>
        <el-button type="primary" @click="handleRollback" v-if="skill.status === 'disabled'">{{ t('skill.rollback') }}</el-button>
      </div>

      <!-- Definition JSON -->
      <el-divider content-position="left">{{ t('skill.definition') }}</el-divider>
      <el-input
        type="textarea"
        :model-value="definitionJson"
        :rows="10"
        readonly
        style="font-family: monospace"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getSkill, approveSkill, disableSkill, rollbackSkill } from '../api'
import { formatTime } from '@/utils/format'
import { skillStatusType as statusType } from '@/utils/status'
import { useAsyncData } from '@/composables/useAsyncData'
import type { Skill } from '../types'

const { t } = useI18n()
const props = defineProps<{ id: string }>()
const route = useRoute()

const { data: skill, loading, execute: loadSkill } = useAsyncData<Skill>(async () => {
  const skillId = props.id || (route.params.id as string)
  const res = await getSkill(skillId)
  return res.data
})

const rateColor = computed(() => {
  const rate = skill.value?.success_rate ?? 0
  if (rate >= 0.8) return '#67c23a'
  if (rate >= 0.5) return '#e6a23c'
  return '#f56c6c'
})

const definitionJson = computed(() => {
  if (!skill.value?.definition) return ''
  return JSON.stringify(skill.value.definition, null, 2)
})

async function handleApprove() {
  await ElMessageBox.confirm(t('skill.approveConfirm', { name: skill.value?.name }), t('common.confirm'))
  await approveSkill(skill.value!.id)
  ElMessage.success(t('skill.approved'))
  loadSkill()
}

async function handleDisable() {
  await ElMessageBox.confirm(t('skill.disableConfirm', { name: skill.value?.name }), t('common.confirm'))
  await disableSkill(skill.value!.id)
  ElMessage.success(t('skill.disabled'))
  loadSkill()
}

async function handleRollback() {
  await ElMessageBox.confirm(t('skill.rollbackConfirm', { name: skill.value?.name }), t('common.confirm'))
  await rollbackSkill(skill.value!.id)
  ElMessage.success(t('skill.rolledBack'))
  loadSkill()
}

onMounted(loadSkill)
</script>
