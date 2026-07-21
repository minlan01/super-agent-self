<template>
  <div class="approval-container">
    <!-- Filter Bar -->
    <div class="filter-bar" style="margin-bottom: 16px; display: flex; gap: 12px">
      <el-select v-model="statusFilter" :placeholder="t('common.status')" clearable style="width: 160px" @change="onFilterChange">
        <el-option :label="t('approval.pending')" value="pending" />
        <el-option :label="t('approval.approved')" value="approved" />
        <el-option :label="t('approval.rejected')" value="rejected" />
      </el-select>
      <el-select v-model="typeFilter" :placeholder="t('approval.approvalType')" clearable style="width: 180px" @change="onFilterChange">
        <el-option :label="'Skill'" value="skill" />
        <el-option :label="'High Risk Step'" value="high_risk_step" />
      </el-select>
    </div>

    <!-- Batch Action Bar -->
    <div v-if="selectedRows.length > 0" style="margin: 12px 0; display: flex; align-items: center; gap: 8px">
      <el-button type="success" size="small" @click="batchResolve(true)">{{ t('approval.batchApprove') }}</el-button>
      <el-button type="danger" size="small" @click="batchResolve(false)">{{ t('approval.batchReject') }}</el-button>
      <span style="color: var(--el-text-color-secondary); font-size: 13px">
        {{ t('approval.selectedCount', { count: selectedRows.length }) }}
      </span>
    </div>

    <!-- Table -->
    <el-table :data="approvals" stripe v-loading="loading" @row-click="showDetail" @selection-change="onSelectionChange">
      <el-table-column type="selection" width="50" />
      <el-table-column prop="id" :label="t('common.id')" width="80" show-overflow-tooltip />
      <el-table-column prop="approval_type" :label="t('common.type')" width="140">
        <template #default="{ row }">
          <el-tag size="small">{{ row.approval_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="target_id" :label="t('approval.target')" show-overflow-tooltip />
      <el-table-column prop="status" :label="t('common.status')" width="120">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="requested_by" :label="t('approval.requestedBy')" width="130" />
      <el-table-column prop="created_at" :label="t('common.created')" width="170" />
      <el-table-column :label="t('common.actions')" width="200" fixed="right">
        <template #default="{ row }">
          <template v-if="row.status === 'pending'">
            <el-button size="small" type="success" @click.stop="resolveOne(row, true)">{{ t('approval.approve') }}</el-button>
            <el-button size="small" type="danger" @click.stop="resolveOne(row, false)">{{ t('approval.reject') }}</el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
    <div style="margin-top: 16px; display: flex; justify-content: flex-end">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @size-change="loadApprovals"
        @current-change="loadApprovals"
      />
    </div>

    <!-- Detail Dialog -->
    <el-dialog v-model="detailVisible" :title="t('approval.detailTitle')" width="600px">
      <el-descriptions v-if="selectedApproval" :column="2" border>
        <el-descriptions-item :label="t('common.id')">{{ selectedApproval.id }}</el-descriptions-item>
        <el-descriptions-item :label="t('approval.approvalType')">{{ selectedApproval.approval_type }}</el-descriptions-item>
        <el-descriptions-item :label="t('approval.target')">{{ selectedApproval.target_id }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.status')">
          <el-tag :type="statusTagType(selectedApproval.status)">{{ selectedApproval.status }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item :label="t('approval.requestedBy')">{{ selectedApproval.requested_by }}</el-descriptions-item>
        <el-descriptions-item :label="t('approval.approvedBy')">{{ selectedApproval.approved_by || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('approval.reason')" :span="2">{{ selectedApproval.reason || '-' }}</el-descriptions-item>
        <el-descriptions-item :label="t('common.created')" :span="2">{{ selectedApproval.created_at }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getApprovals, resolveApproval, batchResolveApprovals } from '../api'
import { useAuthStore } from '../stores/auth'
import type { Approval } from '../types'

const { t } = useI18n()
const authStore = useAuthStore()

// -- Filters --
const statusFilter = ref<string>('')
const typeFilter = ref<string>('')

// -- Pagination --
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)

// -- Data --
const approvals = ref<Approval[]>([])
const loading = ref(false)

// -- Batch Selection --
const selectedRows = ref<Approval[]>([])

// -- Detail Dialog --
const detailVisible = ref(false)
const selectedApproval = ref<Approval | null>(null)

function statusTagType(status: string): '' | 'success' | 'danger' | 'warning' {
  const map: Record<string, '' | 'success' | 'danger' | 'warning'> = {
    pending: 'warning',
    approved: 'success',
    rejected: 'danger',
  }
  return map[status] || 'info'
}

function onFilterChange() {
  currentPage.value = 1
  loadApprovals()
}

async function loadApprovals() {
  loading.value = true
  try {
    const params: Record<string, unknown> = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (statusFilter.value) params.status = statusFilter.value
    if (typeFilter.value) params.approval_type = typeFilter.value
    const res = await getApprovals(params)
    approvals.value = res.items || []
    total.value = res.total || 0
  } catch {
    ElMessage.error(t('common.failedToLoad'))
  } finally {
    loading.value = false
  }
}

function onSelectionChange(rows: Approval[]) {
  selectedRows.value = rows
}

function showDetail(row: Approval) {
  selectedApproval.value = row
  detailVisible.value = true
}

async function resolveOne(approval: Approval, approved: boolean) {
  const actionLabel = approved ? t('approval.approve') : t('approval.reject')
  const actionLower = approved ? 'approve' : 'reject'
  const { value: reason } = await ElMessageBox.prompt(
    t('approval.reasonForAction', { action: actionLower }),
    `${actionLabel} ${approval.approval_type}`,
    { confirmButtonText: actionLabel, inputValue: '' },
  )
  try {
    await resolveApproval(approval.id, {
      approved,
      approved_by: authStore.user?.username || authStore.user?.id || 'unknown',
      reason: reason || undefined,
    })
    ElMessage.success(t('approval.actionSuccess', { action: actionLabel }))
    loadApprovals()
  } catch {
    ElMessage.error(t('approval.failedToAction', { action: actionLabel }))
  }
}

async function batchResolve(approved: boolean) {
  const actionLabel = approved ? t('approval.batchApprove') : t('approval.batchReject')
  const actionLower = approved ? 'approve' : 'reject'

  try {
    await ElMessageBox.confirm(
      t('approval.batchConfirm', { count: selectedRows.value.length, action: actionLower }),
      actionLabel,
      { confirmButtonText: actionLabel, type: approved ? 'success' : 'warning' },
    )
  } catch {
    return // cancelled
  }

  const items = selectedRows.value.map((row) => ({
    approval_id: row.id,
    approved,
    approved_by: authStore.user?.username || authStore.user?.id || 'unknown',
  }))

  try {
    const res = await batchResolveApprovals({ items })
    const resolved = (res as any)?.resolved ?? 0
    const failed = selectedRows.value.length - resolved
    if (failed > 0) {
      ElMessage.warning(t('approval.batchPartial', { resolved, failed }))
    } else {
      ElMessage.success(t('approval.batchSuccess', { count: resolved }))
    }
    loadApprovals()
  } catch {
    ElMessage.error(t('approval.failedToAction', { action: actionLabel }))
  }
}

onMounted(loadApprovals)
</script>
