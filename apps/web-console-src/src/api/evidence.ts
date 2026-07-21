/**
 * 证据模块 API 调用封装
 */
import type { Ref } from 'vue'

const BASE = '/api/v1/evidence'

// ─── 通用类型 ────────────────────────────────────────────────────────────────

export interface EvidenceCase {
  id: string
  case_name: string
  case_type: 'injury' | 'death'
  is_minor: boolean
  status: string
  complaint_case_id?: string
  plaintiff_info: Record<string, unknown>
  defendant_info: Record<string, unknown>
  catalog_data: Record<string, unknown>
  catalog_pdf_path?: string
  analysis_result: Record<string, unknown>
  validation_result: Record<string, unknown>
  missing_items: Record<string, unknown>
  export_bundle_path?: string
  export_files: Record<string, unknown>
  metadata: Record<string, unknown>
  materials: EvidenceMaterial[]
  steps: EvidenceStep[]
  created_at: string
  updated_at: string
}

export interface EvidenceMaterial {
  id: string
  original_filename?: string
  file_type: string
  minio_bucket?: string
  minio_key?: string
  file_size?: number
  auto_category?: string
  manual_category?: string
  effective_category?: string
  category_confidence?: number
  ocr_status: string
  ocr_text?: string
  ocr_result: Record<string, unknown>
  page_count?: number
  extracted_data: Record<string, unknown>
  manual_edit: Record<string, unknown>
  catalog_index?: number
  catalog_title?: string
  catalog_description?: string
  proof_purpose?: string
  fee_detail: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface EvidenceStep {
  id: number
  step_name: string
  status: string
  progress: number
  duration_ms?: number
  error_message?: string
  started_at?: string
  completed_at?: string
}

export interface CaseListResponse {
  items: EvidenceCase[]
  total: number
}

export interface ProgressData {
  case_id: string
  status: string
  current_step?: string
  total_steps: number
  completed_steps: number
  progress_percent: number
  steps: EvidenceStep[]
}

export interface CatalogGroup {
  category: string
  category_name: string
  items: EvidenceMaterial[]
}

export interface CatalogData {
  case_id: string
  case_name: string
  case_type: string
  groups: CatalogGroup[]
  fee_summary: Record<string, number>
  total_amount: number
}

export interface AnalysisData {
  case_id: string
  status: string
  analysis_result: Record<string, unknown>
  validation_result: Record<string, unknown>
  missing_items: Record<string, unknown>
}

// ─── 请求函数 ────────────────────────────────────────────────────────────────

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(error.detail || `Request failed: ${resp.status}`)
  }
  return resp.json()
}

async function downloadBlob(url: string, method: string = 'GET'): Promise<void> {
  const resp = await fetch(url, { method })
  if (!resp.ok) {
    throw new Error(`Download failed: ${resp.status}`)
  }
  const blob = await resp.blob()
  const contentDisposition = resp.headers.get('Content-Disposition')
  let filename = 'download'
  if (contentDisposition) {
    const match = contentDisposition.match(/filename\*=UTF-8''(.+)/)
    if (match) {
      filename = decodeURIComponent(match[1])
    }
  }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

// ─── API 方法 ────────────────────────────────────────────────────────────────

export const evidenceApi = {
  /** 创建案件 */
  createCase: (data: {
    case_name: string
    case_type: 'injury' | 'death'
    is_minor?: boolean
    complaint_case_id?: string
    plaintiff_info?: Record<string, unknown>
    defendant_info?: Record<string, unknown>
  }) => request<EvidenceCase>(`${BASE}/cases`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  /** 案件列表 */
  listCases: (params?: { page?: number; size?: number }) => {
    const qs = params
      ? '?' + new URLSearchParams(
          Object.entries(params).filter(([_, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
        ).toString()
      : ''
    return request<CaseListResponse>(`${BASE}/cases${qs}`)
  },

  /** 案件详情 */
  getCase: (id: string) => request<EvidenceCase>(`${BASE}/cases/${id}`),

  /** 批量上传 */
  uploadMaterials: (caseId: string, formData: FormData) =>
    fetch(`${BASE}/cases/${caseId}/upload`, {
      method: 'POST',
      body: formData,
    }).then(async (resp) => {
      if (!resp.ok) {
        const error = await resp.json().catch(() => ({ detail: resp.statusText }))
        throw new Error(error.detail || 'Upload failed')
      }
      return resp.json() as Promise<EvidenceMaterial[]>
    }),

  /** 一键处理 */
  startProcess: (caseId: string) =>
    request<{ case_id: string; message: string; task_id?: string }>(
      `${BASE}/cases/${caseId}/process`,
      { method: 'POST' },
    ),

  /** 处理进度 */
  getProgress: (caseId: string) =>
    request<ProgressData>(`${BASE}/cases/${caseId}/progress`),

  /** 获取清单 */
  getCatalog: (caseId: string) =>
    request<CatalogData>(`${BASE}/cases/${caseId}/catalog`),

  /** 编辑清单 */
  updateCatalog: (caseId: string, data: {
    items: Array<{
      material_id: string
      manual_category?: string
      catalog_title?: string
      catalog_description?: string
      proof_purpose?: string
      sort_order?: number
    }>
  }) => request<{ message: string }>(`${BASE}/cases/${caseId}/catalog`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  /** 编辑材料 */
  updateMaterial: (caseId: string, mid: string, data: {
    manual_category?: string
    catalog_title?: string
    catalog_description?: string
    proof_purpose?: string
    manual_edit?: Record<string, unknown>
  }) => request<EvidenceMaterial>(`${BASE}/cases/${caseId}/materials/${mid}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  /** 删除材料 */
  deleteMaterial: (caseId: string, mid: string) =>
    request<{ message: string }>(`${BASE}/cases/${caseId}/materials/${mid}`, {
      method: 'DELETE',
    }),

  /** 开始分析 */
  startAnalysis: (caseId: string) =>
    request<{ case_id: string; message: string; task_id?: string }>(
      `${BASE}/cases/${caseId}/analyze`,
      { method: 'POST' },
    ),

  /** 获取分析结果 */
  getAnalysis: (caseId: string) =>
    request<AnalysisData>(`${BASE}/cases/${caseId}/analysis`),

  /** 导出清单 PDF */
  downloadCatalogPdf: (caseId: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/catalog/pdf`),

  /** 导出立案证据 Word */
  exportFilingEvidence: (caseId: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/export/filing-evidence`),

  /** 导出民事起诉状 Word */
  exportComplaint: (caseId: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/export/complaint`),

  /** 导出司法鉴定申请书 Word */
  exportAppraisalApp: (caseId: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/export/appraisal-app`),

  /** 导出赔偿费用总表 Excel */
  exportCompensation: (caseId: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/export/compensation`),

  /** 导出单项费用明细 Excel */
  exportFeeDetail: (caseId: string, feeType: string) =>
    downloadBlob(`${BASE}/cases/${caseId}/export/compensation/${encodeURIComponent(feeType)}`),

  /** 一键打包导出 */
  exportBundle: (caseId: string) =>
    request<{ case_id: string; message: string; bundle_path?: string }>(
      `${BASE}/cases/${caseId}/export/bundle`,
      { method: 'POST' },
    ),
}
