<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; gap: 10px">
      <el-button type="primary" @click="openCreateDialog">{{ t('template.createTemplate') }}</el-button>
      <el-button @click="loadTemplates">{{ t('common.refresh') }}</el-button>
    </div>

    <el-table :data="templates" stripe v-loading="loading">
      <el-table-column prop="name" :label="t('common.name')" width="180" />
      <el-table-column prop="description" :label="t('common.description')" show-overflow-tooltip />
      <el-table-column prop="goal_template" :label="t('template.goalTemplate')" show-overflow-tooltip />
      <el-table-column :label="t('common.edition')" width="120">
        <template #default="{ row }">
          <el-tag :type="row.edition === 'enterprise' ? 'primary' : 'success'" size="small">{{ row.edition }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('template.builtin')" width="100" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.is_builtin" type="info" size="small">{{ t('common.yes') }}</el-tag>
          <span v-else>{{ t('common.no') }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="usage_count" :label="t('template.usageCount')" width="110" align="center" />
      <el-table-column :label="t('common.actions')" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="success" @click="openApplyDialog(row)">{{ t('template.apply') }}</el-button>
          <el-button size="small" type="primary" :disabled="row.is_builtin" @click="openEditDialog(row)">{{ t('common.edit') }}</el-button>
          <el-button size="small" type="danger" :disabled="row.is_builtin" @click="handleDelete(row)">{{ t('common.delete') }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create / Edit Template Dialog -->
    <el-dialog
      v-model="createDialogVisible"
      :title="isEditing ? t('template.editTemplate') : t('template.createTemplate')"
      width="560px"
      destroy-on-close
    >
      <el-form :model="createForm" label-width="120px" label-position="right">
        <el-form-item :label="t('common.name')" required>
          <el-input v-model="createForm.name" :placeholder="t('template.namePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('template.goalTemplate')" required>
          <el-input v-model="createForm.goal_template" type="textarea" :rows="3" :placeholder="t('template.goalPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="createForm.description" type="textarea" :rows="2" :placeholder="t('template.descPlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.edition')">
          <el-select v-model="createForm.edition" style="width: 100%">
            <el-option :label="t('common.enterprise')" value="enterprise" />
            <el-option :label="t('common.personal')" value="personal" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('template.parameters')">
          <el-input v-model="createForm.parametersJson" type="textarea" :rows="3" :placeholder="t('template.paramsPlaceholder')" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreateSubmit">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- Apply Template Dialog -->
    <el-dialog
      v-model="applyDialogVisible"
      :title="t('template.applyTemplate')"
      width="520px"
      destroy-on-close
    >
      <p style="margin-bottom: 12px; color: var(--theme-color-info)">{{ applyTemplate?.goal_template }}</p>
      <el-form :model="applyForm" label-width="140px" label-position="right">
        <el-form-item
          v-for="field in applyFields"
          :key="field.name"
          :label="field.label"
          :required="field.required"
        >
          <el-input v-model="applyForm.params[field.name]" :placeholder="field.label" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="applyDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="applying" @click="handleApplySubmit">{{ t('template.createTask') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { templateApi } from '../api'
import type { Template } from '../types'

const { t } = useI18n()

const templates = ref<Template[]>([])
const loading = ref(false)
const submitting = ref(false)
const applying = ref(false)

// Create / Edit dialog
const createDialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref('')

const defaultCreateForm = () => ({
  name: '',
  goal_template: '',
  description: '',
  edition: 'enterprise',
  parametersJson: '',
})

const createForm = reactive(defaultCreateForm())

// Apply dialog
const applyDialogVisible = ref(false)
const applyTemplate = ref<Template | null>(null)
const applyForm = reactive({ params: {} as Record<string, string> })

const applyFields = computed(() => {
  const params = applyTemplate.value?.parameters
  if (!params || !params.fields) return []
  return params.fields as Array<{ name: string; label: string; required: boolean }>
})

async function loadTemplates() {
  loading.value = true
  try {
    const res = await templateApi.list()
    templates.value = res.data || []
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  isEditing.value = false
  editingId.value = ''
  Object.assign(createForm, defaultCreateForm())
  createDialogVisible.value = true
}

function openEditDialog(row: Template) {
  isEditing.value = true
  editingId.value = row.id
  Object.assign(createForm, {
    name: row.name,
    goal_template: row.goal_template,
    description: row.description || '',
    edition: row.edition || 'enterprise',
    parametersJson: row.parameters ? JSON.stringify(row.parameters, null, 2) : '',
  })
  createDialogVisible.value = true
}

async function handleCreateSubmit() {
  if (!createForm.name.trim() || !createForm.goal_template.trim()) {
    ElMessage.warning(t('template.requiredFields'))
    return
  }
  submitting.value = true
  try {
    let parameters = null
    if (createForm.parametersJson.trim()) {
      try {
        parameters = JSON.parse(createForm.parametersJson.trim())
      } catch {
        ElMessage.warning(t('template.invalidJson'))
        return
      }
    }
    const payload: Record<string, any> = {
      name: createForm.name.trim(),
      goal_template: createForm.goal_template.trim(),
      description: createForm.description.trim() || null,
      edition: createForm.edition,
      parameters,
    }
    if (isEditing.value) {
      await templateApi.update(editingId.value, payload)
      ElMessage.success(t('template.templateUpdated'))
    } else {
      await templateApi.create(payload)
      ElMessage.success(t('template.templateCreated'))
    }
    createDialogVisible.value = false
    loadTemplates()
  } finally {
    submitting.value = false
  }
}

function openApplyDialog(row: Template) {
  applyTemplate.value = row
  const params: Record<string, string> = {}
  if (row.parameters && Array.isArray(row.parameters.fields)) {
    for (const field of row.parameters.fields as Array<{ name: string }>) {
      params[field.name] = ''
    }
  }
  applyForm.params = params
  applyDialogVisible.value = true
}

async function handleApplySubmit() {
  // Validate required fields
  for (const field of applyFields.value) {
    if (field.required && !applyForm.params[field.name]?.trim()) {
      ElMessage.warning(t('template.missingRequired', { name: field.label }))
      return
    }
  }
  applying.value = true
  try {
    const res = await templateApi.apply(applyTemplate.value!.id, {
      params: applyForm.params,
      user_id: 'default',
    })
    ElMessage.success(t('template.taskCreatedFromTemplate'))
    applyDialogVisible.value = false
  } finally {
    applying.value = false
  }
}

async function handleDelete(row: Template) {
  await ElMessageBox.confirm(
    t('template.deleteConfirm', { name: row.name }),
    t('common.confirm'),
    {
      confirmButtonText: t('common.delete'),
      cancelButtonText: t('common.cancel'),
      type: 'warning',
    }
  )
  await templateApi.delete(row.id)
  ElMessage.success(t('template.templateDeleted'))
  loadTemplates()
}

onMounted(loadTemplates)
</script>
