// Admin Console HIPAA Compliance Report (V1). Every call hits
// control-center's own backend at a relative path -- routes_hipaa_
// compliance.py, an in-process router this repo's own hipaa_compliance/
// package owns (not a routes_*_proxy.py relay to another service). No
// function here makes an authorization decision -- that's entirely the
// backend's job (require_permission(manage_all_orgs), the same
// permission audit.ts/organizations.ts already reuse for their own
// platform-admin-only reads).
import { authHeaders, reportUnauthorized } from './auth'

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

// Mirrors backend/src/control_center/hipaa_compliance/schemas.py exactly.
export type ComplianceStatus = 'planned' | 'in_progress' | 'verified' | 'released' | 'exception'

export const COMPLIANCE_STATUSES: readonly ComplianceStatus[] = [
  'planned', 'in_progress', 'verified', 'released', 'exception',
]

export type ComplianceControlCategory =
  | 'audit_integrity' | 'audit_event_signing' | 'audit_event_verification'
  | 'access_control' | 'authentication_authorization' | 'data_integrity'
  | 'monitoring_logging' | 'other'

export const CONTROL_CATEGORIES: readonly ComplianceControlCategory[] = [
  'audit_integrity', 'audit_event_signing', 'audit_event_verification',
  'access_control', 'authentication_authorization', 'data_integrity',
  'monitoring_logging', 'other',
]

// Mirrors CONTROL_CATEGORY_LABELS (schemas.py) exactly -- display only.
export const CONTROL_CATEGORY_LABELS: Record<ComplianceControlCategory, string> = {
  audit_integrity: 'Audit Integrity',
  audit_event_signing: 'Audit Event Signing',
  audit_event_verification: 'Audit Event Verification',
  access_control: 'Access Control',
  authentication_authorization: 'Authentication / Authorization',
  data_integrity: 'Data Integrity',
  monitoring_logging: 'Monitoring / Logging',
  other: 'Other',
}

export const STATUS_LABELS: Record<ComplianceStatus, string> = {
  planned: 'Planned',
  in_progress: 'In Progress',
  verified: 'Verified',
  released: 'Released',
  exception: 'Exception',
}

export type EvidenceType = 'github_pr' | 'commit' | 'ci_run' | 'test_suite' | 'documentation' | 'other'

export const EVIDENCE_TYPES: readonly EvidenceType[] = [
  'github_pr', 'commit', 'ci_run', 'test_suite', 'documentation', 'other',
]

export interface EvidenceRef {
  type: EvidenceType
  label: string
  url?: string | null
  identifier?: string | null
}

export interface HipaaComplianceChange {
  change_id: string
  title: string
  change_date: string
  repository: string
  branch: string | null
  commit_sha: string | null
  pr_number: number | null
  description: string
  control_category: ComplianceControlCategory
  affected_component: string | null
  status: ComplianceStatus
  verification_result: string | null
  reviewer: string | null
  evidence: EvidenceRef[]
  notes: string | null
  created_at: string
  updated_at: string
}

export interface HipaaComplianceChangeListResponse {
  items: HipaaComplianceChange[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface ControlCategorySummary {
  category: ComplianceControlCategory
  label: string
  total: number
  verified: number
  pending: number
  exceptions: number
}

export interface HipaaComplianceSummary {
  overall_status: 'no_data' | 'on_track' | 'in_progress' | 'attention_needed'
  total_controls_tracked: number
  verified_count: number
  pending_count: number
  exception_count: number
  latest_change_id: string | null
  latest_change_title: string | null
  latest_change_date: string | null
  controls: ControlCategorySummary[]
}

export interface HipaaComplianceChangeFilters {
  status?: ComplianceStatus
  controlCategory?: ComplianceControlCategory
  repository?: string
  page?: number
  pageSize?: number
}

export interface HipaaComplianceChangeInput {
  change_id: string
  title: string
  change_date: string
  repository: string
  branch?: string | null
  commit_sha?: string | null
  pr_number?: number | null
  description?: string
  control_category: ComplianceControlCategory
  affected_component?: string | null
  status: ComplianceStatus
  verification_result?: string | null
  reviewer?: string | null
  evidence?: EvidenceRef[]
  notes?: string | null
}

export type HipaaComplianceChangeUpdateInput = Partial<Omit<HipaaComplianceChangeInput, 'change_id'>>

export async function fetchHipaaComplianceSummary(): Promise<HipaaComplianceSummary> {
  const r = await apiFetch('/hipaa-compliance/changes/summary')
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/summary ${r.status}`)
  return r.json()
}

export async function fetchHipaaComplianceChanges(
  filters: HipaaComplianceChangeFilters = {},
): Promise<HipaaComplianceChangeListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(filters.page ?? 1))
  qs.set('page_size', String(filters.pageSize ?? 20))
  if (filters.status) qs.set('status', filters.status)
  if (filters.controlCategory) qs.set('control_category', filters.controlCategory)
  if (filters.repository) qs.set('repository', filters.repository)

  const r = await apiFetch(`/hipaa-compliance/changes?${qs.toString()}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/changes ${r.status}`)
  return r.json()
}

export async function fetchHipaaComplianceChange(changeId: string): Promise<HipaaComplianceChange> {
  const r = await apiFetch(`/hipaa-compliance/changes/${encodeURIComponent(changeId)}`)
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/${changeId} ${r.status}`)
  return r.json()
}

export async function createHipaaComplianceChange(
  input: HipaaComplianceChangeInput,
): Promise<HipaaComplianceChange> {
  const r = await apiFetch('/hipaa-compliance/changes', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (!r.ok) throw new Error(`/hipaa-compliance/changes ${r.status}`)
  return r.json()
}

export async function updateHipaaComplianceChange(
  changeId: string, input: HipaaComplianceChangeUpdateInput,
): Promise<HipaaComplianceChange> {
  const r = await apiFetch(`/hipaa-compliance/changes/${encodeURIComponent(changeId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
  if (!r.ok) throw new Error(`/hipaa-compliance/changes/${changeId} ${r.status}`)
  return r.json()
}
