<template>
  <div class="evidence-page">
    <!-- 案件列表视图 -->
    <template v-if="view === 'list'">
      <n-card title="立案证据智能整理">
        <template #header-extra>
          <n-button type="primary" @click="showCreateDialog = true">
            <template #icon><n-icon :component="AddOutline" /></template>
            新建案件
          </n-button>
        </template>

        <n-data-table
          :columns="caseColumns"
          :data="caseList"
          :loading="listLoading"
          :pagination="pagination"
          :row-key="(row: EvidenceCase) => row.id"
          @update:page="handlePageChange"
        />
      </n-card>

      <!-- 新建案件对话框 -->
      <n-modal v-model:show="showCreateDialog" preset="dialog" title="新建证据案件" positive-text="创建" negative-text="取消" @positive-click="handleCreateCase">
        <n-form ref="createFormRef" :model="newCaseForm" label-placement="left" label-width="100">
          <n-form-item label="案件名称" path="case_name">
            <n-input v-model:value="newCaseForm.case_name" placeholder="请输入案件名称" />
          </n-form-item>
          <n-form-item label="案件类型" path="case_type">
            <n-radio-group v-model:value="newCaseForm.case_type">
              <n-radio value="injury">人身损害（伤残）</n-radio>
              <n-radio value="death">死亡案件</n-radio>
            </n-radio-group>
          </n-form-item>
          <n-form-item label="是否未成年人" path="is_minor">
            <n-switch v-model:value="newCaseForm.is_minor" />
          </n-form-item>
        </n-form>
      </n-modal>
    </template>

    <!-- 案件详情视图 -->
    <template v-else>
      <n-page-header @back="goBack" :title="currentCase?.case_name || '案件详情'" :subtitle="statusLabel">
        <template #extra>
          <n-tag :type="statusTagType" size="small">{{ statusLabel }}</n-tag>
        </template>
      </n-page-header>

      <n-card style="margin-top: 16px">
        <n-steps :current="currentStep" size="small">
          <n-step title="上传素材" />
          <n-step title="证据清单" />
          <n-step title="分析" />
          <n-step title="导出" />
        </n-steps>

        <!-- Step 1: 上传素材 -->
        <div v-if="currentStep === 1" class="step-content">
          <n-upload
            multiple
            directory-dnd
            :action="uploadUrl"
            :headers="uploadHeaders"
            @finish="handleUploadFinish"
            @error="handleUploadError"
            accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.docx,.xlsx"
          >
            <n-upload-dragger>
              <div style="padding: 40px 0">
                <n-icon size="48" :depth="3" :component="CloudUploadOutline" />
                <n-text style="font-size: 16px; display: block; margin-top: 12px">
                  点击或拖拽文件到此区域上传
                </n-text>
                <n-p depth="3" style="margin: 8px 0 0 0">
                  支持 PDF、图片、Word、Excel 格式
                </n-p>
              </div>
            </n-upload-dragger>
          </n-upload>

          <!-- 已上传文件列表 -->
          <n-divider>已上传材料 ({{ currentCase?.materials?.length || 0 }})</n-divider>
          <n-list bordered v-if="currentCase?.materials?.length">
            <n-list-item v-for="mat in currentCase.materials" :key="mat.id">
              <n-thing>
                <template #header>
                  {{ mat.original_filename || '未命名文件' }}
                  <n-tag size="tiny" :type="ocrStatusTagType(mat.ocr_status)" style="margin-left: 8px">
                    {{ ocrStatusLabel(mat.ocr_status) }}
                  </n-tag>
                </template>
                <template #description>
                  <n-text depth="3">
                    {{ formatFileSize(mat.file_size) }} · {{ mat.file_type }}
                    <template v-if="mat.effective_category">
                      · {{ categoryName(mat.effective_category) }}
                    </template>
                  </n-text>
                </template>
                <template #header-extra>
                  <n-button quaternary circle size="small" @click="handleDeleteMaterial(mat.id)">
                    <template #icon><n-icon :component="TrashOutline" /></template>
                  </n-button>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-divider />
          <n-space>
            <n-button type="primary" :disabled="!currentCase?.materials?.length" :loading="processLoading" @click="startProcess">
              开始处理（OCR + 分类 + 生成清单）
            </n-button>
          </n-space>

          <!-- 处理进度 -->
          <n-card v-if="processLoading || progressData" title="处理进度" size="small" style="margin-top: 16px">
            <n-progress :percentage="progressData?.progress_percent || 0" :status="progressStatus" />
            <n-text depth="3" v-if="progressData?.current_step">
              当前步骤：{{ progressData.current_step }}
            </n-text>
          </n-card>
        </div>

        <!-- Step 2: 证据清单 -->
        <div v-if="currentStep === 2" class="step-content">
          <n-tabs type="segment" v-if="catalogData">
            <n-tab-pane v-for="group in catalogData.groups" :key="group.category" :name="group.category" :tab="`${group.category_name} (${group.items.length})`">
              <n-list bordered>
                <n-list-item v-for="item in group.items" :key="item.id">
                  <n-thing>
                    <template #header>
                      证据{{ item.catalog_index }}. {{ item.catalog_title || item.original_filename }}
                    </template>
                    <template #description>
                      <n-text depth="3">{{ item.proof_purpose }}</n-text>
                    </template>
                    <template #header-extra>
                      <n-button text size="small" @click="openEditMaterial(item)">编辑</n-button>
                    </template>
                  </n-thing>
                </n-list-item>
              </n-list>
            </n-tab-pane>
          </n-tabs>

          <n-empty v-else description="暂无清单数据" />

          <!-- 费用汇总 -->
          <n-card v-if="catalogData?.fee_summary && Object.keys(catalogData.fee_summary).length" title="费用汇总" size="small" style="margin-top: 16px">
            <n-descriptions bordered :column="2">
              <n-descriptions-item v-for="(amount, type) in catalogData.fee_summary" :key="type" :label="type">
                {{ amount.toLocaleString('zh-CN', { style: 'currency', currency: 'CNY' }) }}
              </n-descriptions-item>
              <n-descriptions-item label="合计">
                <n-text type="error" strong>
                  {{ catalogData.total_amount?.toLocaleString('zh-CN', { style: 'currency', currency: 'CNY' }) }}
                </n-text>
              </n-descriptions-item>
            </n-descriptions>
          </n-card>

          <n-divider />
          <n-space>
            <n-button @click="downloadCatalogPdf">导出清单 PDF</n-button>
            <n-button type="primary" @click="startAnalysis">分析证据清单</n-button>
          </n-space>
        </div>

        <!-- Step 3: 分析结果 -->
        <div v-if="currentStep === 3" class="step-content">
          <!-- 要件验证 -->
          <n-card title="要件验证" size="small" style="margin-bottom: 16px">
            <n-space vertical v-if="analysisData?.validation_result?.items">
              <n-tag v-for="v in analysisData.validation_result.items" :key="v.category"
                :type="v.status === 'ok' ? 'success' : v.status === 'missing' ? 'error' : 'warning'"
                size="medium"
              >
                {{ v.category_name }}: {{ v.status === 'ok' ? '已具备' : v.status === 'missing' ? '缺失' : '待确认' }}
                <template v-if="v.is_required">（必填）</template>
              </n-tag>
            </n-space>
            <n-empty v-else description="暂无验证结果" />
          </n-card>

          <!-- 文档卡片 -->
          <n-grid :cols="2" :x-gap="16" :y-gap="16">
            <n-gi>
              <n-card title="立案证据" hoverable @click="exportFilingEvidence" class="doc-card">
                <template #cover>
                  <div class="doc-icon"><n-icon size="48" :component="DocumentTextOutline" /></div>
                </template>
                点击导出 Word 文档
              </n-card>
            </n-gi>
            <n-gi>
              <n-card title="民事起诉状" hoverable @click="exportComplaint" class="doc-card">
                <template #cover>
                  <div class="doc-icon"><n-icon size="48" :component="DocumentTextOutline" /></div>
                </template>
                点击导出 Word 文档
              </n-card>
            </n-gi>
            <n-gi>
              <n-card title="司法鉴定申请书" hoverable @click="exportAppraisalApp" class="doc-card">
                <template #cover>
                  <div class="doc-icon"><n-icon size="48" :component="DocumentTextOutline" /></div>
                </template>
                点击导出 Word 文档
              </n-card>
            </n-gi>
            <n-gi>
              <n-card title="赔偿费用总表" hoverable @click="exportCompensation" class="doc-card">
                <template #cover>
                  <div class="doc-icon"><n-icon size="48" :component="DocumentTextOutline" /></div>
                </template>
                点击导出 Excel
              </n-card>
            </n-gi>
          </n-grid>

          <!-- 费用明细导出 -->
          <n-card v-if="catalogData?.fee_summary && Object.keys(catalogData.fee_summary).length" title="单项费用明细" size="small" style="margin-top: 16px">
            <n-space>
              <n-button v-for="(_, feeType) in catalogData.fee_summary" :key="feeType" size="small" @click="exportFeeDetail(feeType as string)">
                {{ feeType }}.xlsx
              </n-button>
            </n-space>
          </n-card>

          <n-divider />
          <n-button type="primary" @click="goToExportStep">下一步：一键导出</n-button>
        </div>

        <!-- Step 4: 一键导出 -->
        <div v-if="currentStep === 4" class="step-content">
          <n-result status="success" title="分析完成" :description="`所有文档已准备就绪，案件名称：${currentCase?.case_name}`">
            <template #footer>
              <n-space vertical>
                <n-button type="primary" size="large" :loading="bundleLoading" @click="exportBundle">
                  一键打包下载 ZIP
                </n-button>
                <n-divider>或单独下载</n-divider>
                <n-space>
                  <n-button @click="exportFilingEvidence">立案证据</n-button>
                  <n-button @click="exportComplaint">民事起诉状</n-button>
                  <n-button @click="exportAppraisalApp">司法鉴定申请书</n-button>
                  <n-button @click="exportCompensation">赔偿费用总表</n-button>
                  <n-button @click="downloadCatalogPdf">证据清单 PDF</n-button>
                </n-space>
              </n-space>
            </template>
          </n-result>
        </div>
      </n-card>

      <!-- 编辑材料对话框 -->
      <n-modal v-model:show="showEditDialog" preset="dialog" title="编辑材料" positive-text="保存" negative-text="取消" @positive-click="handleSaveMaterial">
        <n-form :model="editForm" label-placement="left" label-width="100">
          <n-form-item label="分类">
            <n-select v-model:value="editForm.manual_category" :options="categoryOptions" clearable />
          </n-form-item>
          <n-form-item label="清单标题">
            <n-input v-model:value="editForm.catalog_title" />
          </n-form-item>
          <n-form-item label="证明目的">
            <n-input v-model:value="editForm.proof_purpose" type="textarea" :rows="2" />
          </n-form-item>
          <n-form-item label="描述">
            <n-input v-model:value="editForm.catalog_description" type="textarea" :rows="2" />
          </n-form-item>
        </n-form>
      </n-modal>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useMessage } from 'naive-ui'
import {
  NCard, NButton, NDataTable, NModal, NForm, NFormItem, NInput,
  NRadioGroup, NRadio, NSwitch, NTag, NUpload, NUploadDragger,
  NIcon, NText, NP, NDivider, NSpace, NList, NListItem, NThing,
  NTabs, NTabPane, NDescriptions, NDescriptionsItem, NGrid, NGi,
  NResult, NSelect, NProgress, NPageHeader, NEmpty,
} from 'naive-ui'
import {
  AddOutline, CloudUploadOutline, TrashOutline, DocumentTextOutline,
} from '@vicons/ionicons5'
import { evidenceApi } from '@/api/evidence'
import type { EvidenceCase, EvidenceMaterial, ProgressData, CatalogData, AnalysisData } from '@/api/evidence'

const message = useMessage()

// ─── 状态 ────────────────────────────────────────────────────────────────────

const view = ref<'list' | 'detail'>('list')
const caseList = ref<EvidenceCase[]>([])
const listLoading = ref(false)
const currentCase = ref<EvidenceCase | null>(null)
const pagination = ref({ page: 1, pageSize: 20, itemCount: 0 })

// 新建案件
const showCreateDialog = ref(false)
const newCaseForm = ref({ case_name: '', case_type: 'injury' as 'injury' | 'death', is_minor: false })

// 处理进度
const processLoading = ref(false)
const progressData = ref<ProgressData | null>(null)
let progressTimer: ReturnType<typeof setInterval> | null = null

// 清单数据
const catalogData = ref<CatalogData | null>(null)

// 分析数据
const analysisData = ref<AnalysisData | null>(null)
const analysisLoading = ref(false)

// 导出
const bundleLoading = ref(false)

// 编辑材料
const showEditDialog = ref(false)
const editingMaterialId = ref('')
const editForm = ref({
  manual_category: null as string | null,
  catalog_title: '',
  proof_purpose: '',
  catalog_description: '',
})

// ─── 分类选项 ────────────────────────────────────────────────────────────────

const CATEGORY_MAP: Record<string, string> = {
  identity: '身份证明',
  medical_record: '病历资料',
  fee_receipt: '费用票据',
  appraisal: '司法鉴定',
  death_certificate: '死亡证明',
  other_evidence: '其他证据',
}

const categoryOptions = Object.entries(CATEGORY_MAP).map(([value, label]) => ({ label, value }))

function categoryName(cat: string): string {
  return CATEGORY_MAP[cat] || cat
}

// ─── 步骤计算 ────────────────────────────────────────────────────────────────

const currentStep = computed(() => {
  if (!currentCase.value) return 1
  const s = currentCase.value.status
  if (['draft', 'uploading', 'processing'].includes(s)) return 1
  if (s === 'catalog_ready') return 2
  if (['analyzing', 'analysis_done'].includes(s)) return 3
  if (['exporting', 'completed'].includes(s)) return 4
  if (s === 'failed') return 1
  return 1
})

const statusLabel = computed(() => {
  if (!currentCase.value) return ''
  const map: Record<string, string> = {
    draft: '草稿', uploading: '上传中', processing: '处理中',
    catalog_ready: '清单已生成', analyzing: '分析中',
    analysis_done: '分析完成', exporting: '导出中',
    completed: '已完成', failed: '失败',
  }
  return map[currentCase.value.status] || currentCase.value.status
})

const statusTagType = computed(() => {
  if (!currentCase.value) return 'default' as const
  const map: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    draft: 'default', uploading: 'info', processing: 'info',
    catalog_ready: 'success', analyzing: 'warning',
    analysis_done: 'success', exporting: 'warning',
    completed: 'success', failed: 'error',
  }
  return map[currentCase.value.status] || 'default'
})

const progressStatus = computed(() => {
  if (!progressData.value) return 'default' as const
  if (progressData.value.status === 'failed') return 'error' as const
  if (progressData.value.progress_percent >= 100) return 'success' as const
  return 'info' as const
})

// ─── 上传 URL ────────────────────────────────────────────────────────────────

const uploadUrl = computed(() => {
  if (!currentCase.value) return ''
  return `/api/v1/evidence/cases/${currentCase.value.id}/upload`
})

const uploadHeaders = computed(() => ({}))

// ─── 表格列 ──────────────────────────────────────────────────────────────────

const caseColumns = [
  { title: '案件名称', key: 'case_name', ellipsis: { tooltip: true } },
  { title: '类型', key: 'case_type', width: 120, render: (row: EvidenceCase) => row.case_type === 'injury' ? '人身损害' : '死亡' },
  { title: '状态', key: 'status', width: 120, render: (row: EvidenceCase) => {
    const map: Record<string, string> = {
      draft: '草稿', uploading: '上传中', processing: '处理中',
      catalog_ready: '清单已生成', analyzing: '分析中',
      analysis_done: '分析完成', exporting: '导出中',
      completed: '已完成', failed: '失败',
    }
    return map[row.status] || row.status
  }},
  { title: '创建时间', key: 'created_at', width: 180, render: (row: EvidenceCase) => new Date(row.created_at).toLocaleString('zh-CN') },
  { title: '操作', key: 'actions', width: 100, render: (row: EvidenceCase) => {
    return h(NButton, { size: 'small', type: 'primary', onClick: () => openCaseDetail(row.id) }, { default: () => '查看' })
  }},
]

// h 函数需要从 vue 导入
import { h } from 'vue'

// ─── 方法 ────────────────────────────────────────────────────────────────────

async function loadCaseList() {
  listLoading.value = true
  try {
    const res = await evidenceApi.listCases({ page: pagination.value.page, size: pagination.value.pageSize })
    caseList.value = res.items
    pagination.value.itemCount = res.total
  } catch (e: any) {
    message.error(`加载案件列表失败: ${e.message}`)
  } finally {
    listLoading.value = false
  }
}

function handlePageChange(page: number) {
  pagination.value.page = page
  loadCaseList()
}

async function handleCreateCase() {
  if (!newCaseForm.value.case_name.trim()) {
    message.warning('请输入案件名称')
    return false
  }
  try {
    const caseData = await evidenceApi.createCase(newCaseForm.value)
    message.success('案件创建成功')
    showCreateDialog.value = false
    newCaseForm.value = { case_name: '', case_type: 'injury', is_minor: false }
    await loadCaseList()
    openCaseDetail(caseData.id)
  } catch (e: any) {
    message.error(`创建失败: ${e.message}`)
  }
  return true
}

async function openCaseDetail(caseId: string) {
  try {
    currentCase.value = await evidenceApi.getCase(caseId)
    view.value = 'detail'

    // 加载清单数据
    if (['catalog_ready', 'analyzing', 'analysis_done', 'exporting', 'completed'].includes(currentCase.value.status)) {
      await loadCatalogData(caseId)
    }

    // 加载分析数据
    if (['analysis_done', 'exporting', 'completed'].includes(currentCase.value.status)) {
      await loadAnalysisData(caseId)
    }
  } catch (e: any) {
    message.error(`加载案件详情失败: ${e.message}`)
  }
}

function goBack() {
  view.value = 'list'
  currentCase.value = null
  catalogData.value = null
  analysisData.value = null
  progressData.value = null
  stopProgressPolling()
  loadCaseList()
}

function handleUploadFinish({ event }: { event: ProgressEvent }) {
  message.success('文件上传成功')
  // 刷新案件详情
  if (currentCase.value) {
    openCaseDetail(currentCase.value.id)
  }
  return
}

function handleUploadError() {
  message.error('文件上传失败')
}

async function handleDeleteMaterial(materialId: string) {
  if (!currentCase.value) return
  try {
    await evidenceApi.deleteMaterial(currentCase.value.id, materialId)
    message.success('材料已删除')
    await openCaseDetail(currentCase.value.id)
  } catch (e: any) {
    message.error(`删除失败: ${e.message}`)
  }
}

async function startProcess() {
  if (!currentCase.value) return
  processLoading.value = true
  try {
    const res = await evidenceApi.startProcess(currentCase.value.id)
    message.info(res.message)
    startProgressPolling()
  } catch (e: any) {
    message.error(`处理启动失败: ${e.message}`)
  } finally {
    processLoading.value = false
  }
}

function startProgressPolling() {
  stopProgressPolling()
  progressTimer = setInterval(async () => {
    if (!currentCase.value) return
    try {
      const progress = await evidenceApi.getProgress(currentCase.value.id)
      progressData.value = progress

      if (progress.status === 'catalog_ready' || progress.status === 'failed' || progress.status === 'completed') {
        stopProgressPolling()
        await openCaseDetail(currentCase.value.id)
      }
    } catch {
      // 忽略轮询错误
    }
  }, 3000)
}

function stopProgressPolling() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

async function loadCatalogData(caseId: string) {
  try {
    catalogData.value = await evidenceApi.getCatalog(caseId)
  } catch {
    // 忽略
  }
}

async function loadAnalysisData(caseId: string) {
  try {
    analysisData.value = await evidenceApi.getAnalysis(caseId)
  } catch {
    // 忽略
  }
}

async function startAnalysis() {
  if (!currentCase.value) return
  analysisLoading.value = true
  try {
    const res = await evidenceApi.startAnalysis(currentCase.value.id)
    message.info(res.message)

    // 轮询等待分析完成
    const timer = setInterval(async () => {
      if (!currentCase.value) { clearInterval(timer); return }
      try {
        const progress = await evidenceApi.getProgress(currentCase.value.id)
        if (['analysis_done', 'failed', 'completed'].includes(progress.status)) {
          clearInterval(timer)
          await openCaseDetail(currentCase.value.id)
        }
      } catch { /* ignore */ }
    }, 3000)
  } catch (e: any) {
    message.error(`分析启动失败: ${e.message}`)
  } finally {
    analysisLoading.value = false
  }
}

function goToExportStep() {
  // currentStep 会根据 status 自动切换
  // 只需确保数据已刷新
  if (currentCase.value) {
    openCaseDetail(currentCase.value.id)
  }
}

// ─── 编辑材料 ────────────────────────────────────────────────────────────────

function openEditMaterial(mat: EvidenceMaterial) {
  editingMaterialId.value = mat.id
  editForm.value = {
    manual_category: mat.manual_category || mat.effective_category || null,
    catalog_title: mat.catalog_title || '',
    proof_purpose: mat.proof_purpose || '',
    catalog_description: mat.catalog_description || '',
  }
  showEditDialog.value = true
}

async function handleSaveMaterial() {
  if (!currentCase.value) return false
  try {
    await evidenceApi.updateMaterial(currentCase.value.id, editingMaterialId.value, editForm.value)
    message.success('材料信息已更新')
    await openCaseDetail(currentCase.value.id)
  } catch (e: any) {
    message.error(`保存失败: ${e.message}`)
  }
  return true
}

// ─── 导出 ────────────────────────────────────────────────────────────────────

async function downloadCatalogPdf() {
  if (!currentCase.value) return
  try {
    await evidenceApi.downloadCatalogPdf(currentCase.value.id)
    message.success('PDF 下载已开始')
  } catch (e: any) {
    message.error(`下载失败: ${e.message}`)
  }
}

async function exportFilingEvidence() {
  if (!currentCase.value) return
  try {
    await evidenceApi.exportFilingEvidence(currentCase.value.id)
    message.success('立案证据下载已开始')
  } catch (e: any) {
    message.error(`导出失败: ${e.message}`)
  }
}

async function exportComplaint() {
  if (!currentCase.value) return
  try {
    await evidenceApi.exportComplaint(currentCase.value.id)
    message.success('民事起诉状下载已开始')
  } catch (e: any) {
    message.error(`导出失败: ${e.message}`)
  }
}

async function exportAppraisalApp() {
  if (!currentCase.value) return
  try {
    await evidenceApi.exportAppraisalApp(currentCase.value.id)
    message.success('司法鉴定申请书下载已开始')
  } catch (e: any) {
    message.error(`导出失败: ${e.message}`)
  }
}

async function exportCompensation() {
  if (!currentCase.value) return
  try {
    await evidenceApi.exportCompensation(currentCase.value.id)
    message.success('赔偿费用总表下载已开始')
  } catch (e: any) {
    message.error(`导出失败: ${e.message}`)
  }
}

async function exportFeeDetail(feeType: string) {
  if (!currentCase.value) return
  try {
    await evidenceApi.exportFeeDetail(currentCase.value.id, feeType)
    message.success(`${feeType}明细下载已开始`)
  } catch (e: any) {
    message.error(`导出失败: ${e.message}`)
  }
}

async function exportBundle() {
  if (!currentCase.value) return
  bundleLoading.value = true
  try {
    const res = await evidenceApi.exportBundle(currentCase.value.id)
    message.info(res.message)

    // 轮询等待打包完成
    const timer = setInterval(async () => {
      if (!currentCase.value) { clearInterval(timer); return }
      try {
        const caseData = await evidenceApi.getCase(currentCase.value.id)
        if (caseData.status === 'completed' && caseData.export_bundle_path) {
          clearInterval(timer)
          currentCase.value = caseData
          message.success('打包完成，请重新点击下载')
        }
      } catch { /* ignore */ }
    }, 5000)
  } catch (e: any) {
    message.error(`打包失败: ${e.message}`)
  } finally {
    bundleLoading.value = false
  }
}

// ─── 辅助函数 ────────────────────────────────────────────────────────────────

function formatFileSize(bytes?: number | null): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function ocrStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待处理', processing: '处理中', completed: '已完成',
    failed: '失败', skipped: '已跳过',
  }
  return map[status] || status
}

function ocrStatusTagType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const map: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    pending: 'default', processing: 'info', completed: 'success',
    failed: 'error', skipped: 'warning',
  }
  return map[status] || 'default'
}

// ─── 生命周期 ────────────────────────────────────────────────────────────────

onMounted(() => {
  loadCaseList()
})
</script>

<style scoped>
.evidence-page {
  padding: 0;
}

.step-content {
  margin-top: 24px;
}

.doc-card {
  cursor: pointer;
  text-align: center;
  transition: box-shadow 0.2s;
}

.doc-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.doc-icon {
  padding: 24px 0;
  text-align: center;
  color: #4472c4;
}
</style>
