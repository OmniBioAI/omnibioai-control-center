// HIPAA Basic Compliance Report v0.8.0. Data layer, mirroring analytics.ts's
// own shape exactly -- every call hits this service's own backend at a
// relative path (control_center.compliance.router, mounted at /compliance
// in main.py); no function here makes an authorization decision, that's
// entirely require_permission(manage_all_orgs)'s job server-side
// (401/403 re-checked on every single call below).
import { authHeaders, reportUnauthorized } from './auth'

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401) {
    reportUnauthorized()
  }
  return r
}

export interface HipaaReportFilters {
  fromDate: string
  toDate: string
  orgId: number
}

function buildQuery(filters: HipaaReportFilters): URLSearchParams {
  const qs = new URLSearchParams()
  qs.set('from_date', filters.fromDate)
  qs.set('to_date', filters.toDate)
  qs.set('org_id', String(filters.orgId))
  return qs
}

// Mirrors control_center.compliance.service.build_report's response
// exactly (backend/src/control_center/compliance/service.py).
export interface HipaaReportSummary {
  total_users: number
  active_users: number
  total_rag_queries: number
  security_incidents: number
}

export interface HipaaReportUserAccessRow {
  user_label: string
  login_count: number
  last_login: string | null
  failed_attempts: number
}

export interface HipaaReportRagQueryRow {
  timestamp: string | null
  user_label: string
  trace_id: string | null
}

export interface HipaaReportSecurityEventRow {
  timestamp: string | null
  label: string
  actor_label: string
  outcome: string
  event_type: string
}

export interface HipaaReport {
  organization_id: number
  organization_name: string
  from_date: string
  to_date: string
  generated_at: string
  generated_by: string
  summary: HipaaReportSummary
  user_access: HipaaReportUserAccessRow[]
  rag_queries: HipaaReportRagQueryRow[]
  security_events: HipaaReportSecurityEventRow[]
  truncated: boolean
}

export async function fetchHipaaReport(filters: HipaaReportFilters): Promise<HipaaReport> {
  const qs = buildQuery(filters)
  const r = await apiFetch(`/compliance/hipaa-report?${qs.toString()}`)
  if (!r.ok) throw new Error(`/compliance/hipaa-report ${r.status}`)
  return r.json()
}

async function downloadFile(path: string, filename: string): Promise<void> {
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function filenameStem(filters: HipaaReportFilters): string {
  return `hipaa-report-org${filters.orgId}-${filters.fromDate}-to-${filters.toDate}`
}

export async function downloadHipaaReportPdf(filters: HipaaReportFilters): Promise<void> {
  const qs = buildQuery(filters)
  await downloadFile(`/compliance/hipaa-report/pdf?${qs.toString()}`, `${filenameStem(filters)}.pdf`)
}

export async function downloadHipaaReportCsv(filters: HipaaReportFilters): Promise<void> {
  const qs = buildQuery(filters)
  await downloadFile(`/compliance/hipaa-report/csv?${qs.toString()}`, `${filenameStem(filters)}.csv`)
}
