<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useOfficeStore } from '@/stores/office'
import { useAgentStore } from '@/stores/agent'
import { getErrorMessage } from '@/utils/error'
import {
  NModal,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NButton,
  NSpace,
  NTag,
  NText,
  NDivider,
  useMessage,
} from 'naive-ui'

const emit = defineEmits<{
  agentCreated: []
}>()

const { t } = useI18n()
const officeStore = useOfficeStore()
const agentStore = useAgentStore()
const message = useMessage()

const showCreateAgentModal = ref(false)
const creatingAgent = ref(false)
const createAgentForm = ref({
  id: '',
  name: '',
  workspace: '',
})

const showToolsModal = ref(false)
const selectedAgentForTools = ref<{ id: string; name?: string; tools?: { allow?: string[]; deny?: string[] } } | null>(null)
const toolsForm = ref({
  allow: [] as string[],
  deny: [] as string[],
})
const savingTools = ref(false)

const toolCategories = [
  { nameKey: 'myworld.toolCategories.files', tools: ['read', 'write', 'edit', 'apply_patch'] },
  { nameKey: 'myworld.toolCategories.runtime', tools: ['exec', 'process'] },
  { nameKey: 'myworld.toolCategories.web', tools: ['web_search', 'web_fetch'] },
  { nameKey: 'myworld.toolCategories.memory', tools: ['memory_search', 'memory_get'] },
  { nameKey: 'myworld.toolCategories.sessions', tools: ['sessions_list', 'sessions_history', 'sessions_send', 'sessions_spawn', 'sessions_yield', 'subagents', 'session_status'] },
  { nameKey: 'myworld.toolCategories.ui', tools: ['browser', 'canvas'] },
  { nameKey: 'myworld.toolCategories.messaging', tools: ['message'] },
  { nameKey: 'myworld.toolCategories.automation', tools: ['cron', 'gateway'] },
  { nameKey: 'myworld.toolCategories.nodes', tools: ['nodes'] },
  { nameKey: 'myworld.toolCategories.agents', tools: ['agents_list'] },
  { nameKey: 'myworld.toolCategories.media', tools: ['image', 'image_generate', 'tts'] },
]

function openCreateAgentModal() {
  createAgentForm.value = {
    id: '',
    name: '',
    workspace: '',
  }
  showCreateAgentModal.value = true
}

async function handleCreateAgent() {
  if (!createAgentForm.value.id.trim()) {
    message.error(t('myworld.employeeIdRequired'))
    return
  }

  creatingAgent.value = true
  try {
    await agentStore.addAgent({
      id: createAgentForm.value.id.trim(),
      name: createAgentForm.value.name.trim() || createAgentForm.value.id.trim(),
      workspace: createAgentForm.value.workspace.trim() || undefined,
    })
    await new Promise(resolve => setTimeout(resolve, 500))
    await agentStore.fetchAgents()
    await officeStore.loadOfficeData()
    message.success(t('myworld.employeeCreated'))
    showCreateAgentModal.value = false

    emit('agentCreated')
  } catch (e: unknown) {
    message.error(getErrorMessage(e) || t('myworld.employeeCreateFailed'))
  } finally {
    creatingAgent.value = false
  }
}

function openToolsModal() {
  const agentList = agentStore.agents
  if (agentList.length === 0) {
    message.warning(t('myworld.noConfigurableEmployees'))
    return
  }

  const firstAgent = agentList[0]
  if (!firstAgent) return

  selectedAgentForTools.value = firstAgent
  toolsForm.value = {
    allow: firstAgent.tools?.allow || [],
    deny: firstAgent.tools?.deny || [],
  }
  showToolsModal.value = true
}

function selectAgentForTools(agentId: string) {
  const agent = agentStore.agents.find(a => a.id === agentId)
  if (!agent) return

  selectedAgentForTools.value = agent
  toolsForm.value = {
    allow: agent.tools?.allow || [],
    deny: agent.tools?.deny || [],
  }
}

function addToolToAllow(tool: string) {
  if (!toolsForm.value.allow.includes(tool)) {
    toolsForm.value.allow.push(tool)
  }
  const denyIndex = toolsForm.value.deny.indexOf(tool)
  if (denyIndex > -1) {
    toolsForm.value.deny.splice(denyIndex, 1)
  }
}

function removeToolFromAllow(tool: string) {
  const index = toolsForm.value.allow.indexOf(tool)
  if (index > -1) {
    toolsForm.value.allow.splice(index, 1)
  }
}

function addToolToDeny(tool: string) {
  if (!toolsForm.value.deny.includes(tool)) {
    toolsForm.value.deny.push(tool)
  }
  const allowIndex = toolsForm.value.allow.indexOf(tool)
  if (allowIndex > -1) {
    toolsForm.value.allow.splice(allowIndex, 1)
  }
}

function removeToolFromDeny(tool: string) {
  const index = toolsForm.value.deny.indexOf(tool)
  if (index > -1) {
    toolsForm.value.deny.splice(index, 1)
  }
}

async function handleSetTools() {
  if (!selectedAgentForTools.value) return

  savingTools.value = true
  try {
    await agentStore.setAgentTools({
      agentId: selectedAgentForTools.value.id,
      allow: toolsForm.value.allow.length > 0 ? toolsForm.value.allow : undefined,
      deny: toolsForm.value.deny.length > 0 ? toolsForm.value.deny : undefined,
    })
    message.success(t('myworld.permissionSaved'))
    showToolsModal.value = false
  } catch (e: unknown) {
    message.error(getErrorMessage(e) || t('myworld.permissionSaveFailed'))
  } finally {
    savingTools.value = false
  }
}

defineExpose({
  openCreateAgentModal,
  openToolsModal,
})
</script>

<template>
  <!-- Create Agent Modal -->
  <NModal
    v-model:show="showCreateAgentModal"
    preset="card"
    :title="t('myworld.addEmployee')"
    style="width: 500px; max-width: 90vw;"
    :mask-closable="false"
  >
    <NForm label-placement="left" label-width="100">
      <NFormItem :label="t('myworld.employeeId')" path="id">
        <NInput v-model:value="createAgentForm.id" :placeholder="t('myworld.employeeIdPlaceholder')" />
      </NFormItem>
      <NFormItem :label="t('myworld.employeeName')" path="name">
        <NInput v-model:value="createAgentForm.name" :placeholder="t('myworld.employeeNamePlaceholder')" />
      </NFormItem>
      <NFormItem :label="t('myworld.workspace')" path="workspace">
        <NInput v-model:value="createAgentForm.workspace" :placeholder="t('myworld.workspacePlaceholder')" />
      </NFormItem>
    </NForm>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="showCreateAgentModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="primary" :loading="creatingAgent" @click="handleCreateAgent">
          {{ t('common.create') }}
        </NButton>
      </NSpace>
    </template>
  </NModal>

  <!-- Tools/Permissions Modal -->
  <NModal
    v-model:show="showToolsModal"
    preset="card"
    :title="t('myworld.modifyEmployeePermission')"
    style="width: 700px; max-width: 90vw;"
    :mask-closable="false"
  >
    <NSpace vertical size="large">
      <NFormItem :label="t('myworld.employeeName')">
        <NSelect
          :value="selectedAgentForTools?.id"
          :options="agentStore.agents.map(a => ({ label: a.name || a.id, value: a.id }))"
          @update:value="selectAgentForTools"
        />
      </NFormItem>

      <div>
        <NText depth="3" style="font-size: 12px; margin-bottom: 8px; display: block;">
          {{ t('myworld.allowedPermissions') }} (Allow)
        </NText>
        <NSpace size="small" style="margin-bottom: 8px;">
          <NTag
            v-for="tool in toolsForm.allow"
            :key="tool"
            type="success"
            closable
            @close="removeToolFromAllow(tool)"
          >
            {{ tool }}
          </NTag>
          <NInput
            :style="{ width: '120px' }"
            size="small"
            :placeholder="t('myworld.addPermission')"
            @keydown.enter="(e: KeyboardEvent) => {
              const target = e.target as HTMLInputElement
              if (target.value.trim()) {
                addToolToAllow(target.value.trim())
                target.value = ''
              }
            }"
          />
        </NSpace>
      </div>

      <div>
        <NText depth="3" style="font-size: 12px; margin-bottom: 8px; display: block;">
          {{ t('myworld.deniedPermissions') }} (Deny)
        </NText>
        <NSpace size="small" style="margin-bottom: 8px;">
          <NTag
            v-for="tool in toolsForm.deny"
            :key="tool"
            type="error"
            closable
            @close="removeToolFromDeny(tool)"
          >
            {{ tool }}
          </NTag>
          <NInput
            :style="{ width: '120px' }"
            size="small"
            :placeholder="t('myworld.addPermission')"
            @keydown.enter="(e: KeyboardEvent) => {
              const target = e.target as HTMLInputElement
              if (target.value.trim()) {
                addToolToDeny(target.value.trim())
                target.value = ''
              }
            }"
          />
        </NSpace>
      </div>

      <NDivider style="margin: 8px 0;" />

      <div>
        <NText depth="3" style="font-size: 12px; margin-bottom: 8px; display: block;">
          {{ t('myworld.commonPermissions') }}
        </NText>
        <NSpace vertical size="small">
          <div v-for="category in toolCategories" :key="category.nameKey">
            <NText depth="3" style="font-size: 11px; margin-right: 8px;">{{ t(category.nameKey) }}:</NText>
            <NSpace size="small" style="margin-top: 4px;">
              <NButton
                v-for="tool in category.tools"
                :key="tool"
                size="tiny"
                :type="toolsForm.allow.includes(tool) ? 'success' : toolsForm.deny.includes(tool) ? 'error' : 'default'"
                :disabled="toolsForm.allow.includes(tool) || toolsForm.deny.includes(tool)"
                @click="addToolToAllow(tool)"
                @contextmenu.prevent="addToolToDeny(tool)"
              >
                {{ tool }}
              </NButton>
            </NSpace>
          </div>
        </NSpace>
        <NText depth="3" style="font-size: 11px; margin-top: 8px; display: block;">
          {{ t('myworld.permissionHint') }}
        </NText>
      </div>
    </NSpace>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="showToolsModal = false">{{ t('common.cancel') }}</NButton>
        <NButton type="primary" :loading="savingTools" @click="handleSetTools">
          {{ t('common.save') }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>
