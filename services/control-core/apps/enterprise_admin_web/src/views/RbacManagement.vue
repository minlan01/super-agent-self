<template>
  <div class="rbac-management">
    <el-tabs v-model="activeTab">
      <!-- Roles Tab -->
      <el-tab-pane :label="t('rbac.roles')" name="roles">
        <div style="margin-bottom: 16px; display: flex; justify-content: space-between;">
          <h3>{{ t('rbac.roles') }}</h3>
          <el-button type="primary" @click="showCreateRoleDialog">{{ t('rbac.createRole') }}</el-button>
        </div>
        <el-table :data="roles" border stripe>
          <el-table-column prop="name" :label="t('rbac.name')" width="150" />
          <el-table-column prop="description" :label="t('rbac.description')" />
          <el-table-column prop="is_default" :label="t('rbac.default')" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_default ? 'success' : 'info'" size="small">
                {{ row.is_default ? t('common.yes') : t('common.no') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="is_system" :label="t('rbac.system')" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_system ? 'warning' : 'info'" size="small">
                {{ row.is_system ? t('common.yes') : t('common.no') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('rbac.permissionsLabel')" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="p in row.permissions?.slice(0, 5)" :key="p.id" size="small" style="margin: 2px;">
                {{ p.name }}
              </el-tag>
              <el-tag v-if="(row.permissions?.length || 0) > 5" size="small" type="info" style="margin: 2px;">
                {{ t('rbac.more', { count: row.permissions.length - 5 }) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('rbac.actions')" width="150" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="editRole(row)" :disabled="row.is_system">{{ t('common.edit') }}</el-button>
              <el-button size="small" type="danger" @click="deleteRole(row)" :disabled="row.is_system">{{ t('common.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- Permissions Tab -->
      <el-tab-pane :label="t('rbac.permissions')" name="permissions">
        <h3>{{ t('rbac.permissions') }}</h3>
        <el-table :data="permissions" border stripe>
          <el-table-column prop="name" :label="t('rbac.name')" width="200" />
          <el-table-column prop="resource" :label="t('rbac.resource')" width="120" />
          <el-table-column prop="action" :label="t('rbac.action')" width="100" />
          <el-table-column prop="description" :label="t('rbac.description')" />
        </el-table>
      </el-tab-pane>

      <!-- User Assignments Tab -->
      <el-tab-pane :label="t('rbac.userRoles')" name="users">
        <h3>{{ t('rbac.userRoleAssignments') }}</h3>
        <el-table :data="usersWithRoles" border stripe>
          <el-table-column prop="username" :label="t('rbac.username')" width="150" />
          <el-table-column prop="email" :label="t('rbac.email')" width="200" />
          <el-table-column prop="role" :label="t('rbac.legacyRole')" width="100" />
          <el-table-column :label="t('rbac.rbacRoles')" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="r in row.roles" :key="r.id" size="small" style="margin: 2px;">
                {{ r.name }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('rbac.actions')" width="120" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="manageUserRoles(row)">{{ t('rbac.manage') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- Create/Edit Role Dialog -->
    <el-dialog v-model="roleDialogVisible" :title="editingRole ? t('rbac.editRole') : t('rbac.createRole')" width="500px">
      <el-form :model="roleForm" label-width="100px">
        <el-form-item :label="t('rbac.name')">
          <el-input v-model="roleForm.name" :disabled="!!editingRole?.is_system" />
        </el-form-item>
        <el-form-item :label="t('rbac.description')">
          <el-input v-model="roleForm.description" type="textarea" />
        </el-form-item>
        <el-form-item :label="t('rbac.default')">
          <el-switch v-model="roleForm.is_default" />
        </el-form-item>
        <el-form-item :label="t('rbac.permissionsLabel')">
          <el-select v-model="roleForm.permission_ids" multiple :placeholder="t('rbac.selectPermissions')" style="width: 100%">
            <el-option v-for="p in permissions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveRole">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <!-- User Role Assignment Dialog -->
    <el-dialog v-model="userRoleDialogVisible" :title="t('rbac.manageUserRoles')" width="400px">
      <p>{{ t('rbac.assignRolesFor') }} <strong>{{ managingUser?.username }}</strong></p>
      <el-select v-model="selectedRoleIds" multiple :placeholder="t('rbac.selectRoles')" style="width: 100%; margin-top: 16px;">
        <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
      </el-select>
      <template #footer>
        <el-button @click="userRoleDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveUserRoles">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { rbacApi } from '@/api'
import type { RoleWithPermissions, Permission, UserWithRoles } from '@/types'

const { t } = useI18n()

const activeTab = ref('roles')
const roles = ref<RoleWithPermissions[]>([])
const permissions = ref<Permission[]>([])
const usersWithRoles = ref<UserWithRoles[]>([])
const roleDialogVisible = ref(false)
const userRoleDialogVisible = ref(false)
const editingRole = ref<RoleWithPermissions | null>(null)
const managingUser = ref<UserWithRoles | null>(null)
const selectedRoleIds = ref<string[]>([])
const roleForm = ref({
  name: '',
  description: '',
  is_default: false,
  permission_ids: [] as string[],
})

const fetchRoles = async () => {
  try {
    const resp = await rbacApi.roles()
    roles.value = resp || []
  } catch {
    ElMessage.error(t('rbac.failedToLoadRoles'))
  }
}

const fetchPermissions = async () => {
  try {
    const resp = await rbacApi.permissions()
    permissions.value = resp || []
  } catch {
    ElMessage.error(t('rbac.failedToLoadPermissions'))
  }
}

const fetchUsers = async () => {
  try {
    const resp = await rbacApi.users()
    usersWithRoles.value = resp || []
  } catch {
    ElMessage.error(t('rbac.failedToLoadUsers'))
  }
}

const showCreateRoleDialog = () => {
  editingRole.value = null
  roleForm.value = { name: '', description: '', is_default: false, permission_ids: [] }
  roleDialogVisible.value = true
}

const editRole = (role: RoleWithPermissions) => {
  editingRole.value = role
  roleForm.value = {
    name: role.name,
    description: role.description || '',
    is_default: role.is_default,
    permission_ids: (role.permissions || []).map(p => p.id),
  }
  roleDialogVisible.value = true
}

const saveRole = async () => {
  try {
    if (editingRole.value) {
      await rbacApi.updateRole(editingRole.value.id, roleForm.value)
    } else {
      await rbacApi.createRole(roleForm.value)
    }
    roleDialogVisible.value = false
    ElMessage.success(editingRole.value ? t('rbac.roleUpdated') : t('rbac.roleCreated'))
    fetchRoles()
  } catch {
    ElMessage.error(t('rbac.failedToSaveRole'))
  }
}

const deleteRole = async (role: RoleWithPermissions) => {
  try {
    await rbacApi.deleteRole(role.id)
    ElMessage.success(t('rbac.roleDeleted'))
    fetchRoles()
  } catch {
    ElMessage.error(t('rbac.failedToDeleteRole'))
  }
}

const manageUserRoles = (user: UserWithRoles) => {
  managingUser.value = user
  selectedRoleIds.value = (user.roles || []).map(r => r.id)
  userRoleDialogVisible.value = true
}

const saveUserRoles = async () => {
  if (!managingUser.value) return
  try {
    const currentIds = (managingUser.value.roles || []).map(r => r.id)
    const toAdd = selectedRoleIds.value.filter(id => !currentIds.includes(id))
    const toRemove = currentIds.filter((id: string) => !selectedRoleIds.value.includes(id))

    if (toAdd.length > 0) {
      await rbacApi.assignRoles({
        user_id: managingUser.value.id,
        role_ids: toAdd,
      })
    }
    if (toRemove.length > 0) {
      await rbacApi.revokeRoles({
        user_id: managingUser.value.id,
        role_ids: toRemove,
      })
    }

    userRoleDialogVisible.value = false
    ElMessage.success(t('rbac.userRolesUpdated'))
    fetchUsers()
  } catch {
    ElMessage.error(t('rbac.failedToUpdateUserRoles'))
  }
}

onMounted(() => {
  fetchRoles()
  fetchPermissions()
  fetchUsers()
})
</script>

<style scoped>
.rbac-management {
  padding: 20px;
}
</style>
