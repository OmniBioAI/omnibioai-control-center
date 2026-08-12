// Usage Analytics v1 (PR-D). Data layer, mirroring interactions.ts's own
// shape exactly -- every call hits this service's own backend at a
// relative path (control_center.analytics.router, mounted at /analytics
// in main.py); no function here makes an authorization decision, that's
// entirely require_analytics_scope's job server-side (401/403 on a
// missing/insufficient token, re-checked on every single call below --
// the org_id/team_id this file sends are a UX convenience, never trusted
// client-side).
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

export interface AnalyticsFilters {
  fromDate?: string
  toDate?: string
  orgId?: number
  teamId?: number
}

function buildQuery(filters: AnalyticsFilters): URLSearchParams {
  const qs = new URLSearchParams()
  if (filters.fromDate) qs.set('from_date', filters.fromDate)
  if (filters.toDate) qs.set('to_date', filters.toDate)
  if (filters.orgId != null) qs.set('org_id', String(filters.orgId))
  if (filters.teamId != null) qs.set('team_id', String(filters.teamId))
  return qs
}

// Mirrors control_center.analytics.service.get_overview's response
// exactly. `total_queries`/`active_users`/`workflows_run` are `null`,
// not fabricated, when the backend couldn't answer for this scope (a
// team-roster lookup failure, or a platform_admin asking about
// workflows -- see that module's own docstring for the full list) --
// this page renders those the same "--" way DashboardPage.tsx already
// established for a null MetricCard value.
export interface AnalyticsOverview {
  total_queries: number | null
  active_users: number | null
  workflows_run: number | null
  error_rate: number
  from_date: string
  to_date: string
  org_id: number | null
  team_id: number | null
  team_scope_available?: boolean
}

export interface DailyCount {
  date: string
  count: number | null
}

export interface AnalyticsUsers {
  daily: DailyCount[]
  dau: number | null
  wau: number | null
  mau: number | null
  org_id: number | null
  team_id: number | null
  team_scope_available?: boolean
}

export interface AnalyticsQueries {
  daily: DailyCount[]
  total_queries: number | null
  from_date: string
  to_date: string
  org_id: number | null
  team_id: number | null
  team_scope_available?: boolean
}

export interface ServiceBreakdownRow {
  service: string
  total_calls: number
  errors: number
  error_rate: number
  avg_latency_ms: number | null
}

export interface AnalyticsServices {
  services: ServiceBreakdownRow[]
  org_id: number | null
  team_id: number | null
  note?: string
}

// PLATFORM-WIDE ONLY -- org_id/team_id are always null here regardless
// of the caller's own filter selection (audit:events, this response's
// real source, carries no organization_id at all -- see aggregator.py's
// own module docstring). AnalyticsDashboard.tsx must never attribute
// these numbers to whatever org/team filter happens to be selected.
export interface AnalyticsPerformance {
  scope: 'platform'
  org_id: null
  team_id: null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  p99_latency_ms: number | null
  error_rate: number
  throughput_per_day: number
  latency_source: 'prometheus' | 'events'
  from_date: string
  to_date: string
}

export interface AnalyticsWorkflows {
  workflows_run: number | null
  daily: DailyCount[] | null
  success_rate: number | null
  org_id: number | null
  team_id: number | null
  from_date: string
  to_date: string
  note?: string
}

export interface AnalyticsUsage {
  org_id: number | null
  team_id: number | null
  billing_available: boolean
  usage: Record<string, unknown> | null
  limits: Record<string, unknown> | null
  note?: string
}

async function getJson<T>(path: string, filters: AnalyticsFilters): Promise<T> {
  const qs = buildQuery(filters)
  const r = await apiFetch(`${path}?${qs.toString()}`)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json()
}

export const fetchAnalyticsOverview = (filters: AnalyticsFilters = {}) => getJson<AnalyticsOverview>('/analytics/overview', filters)
export const fetchAnalyticsQueries = (filters: AnalyticsFilters = {}) => getJson<AnalyticsQueries>('/analytics/queries', filters)
export const fetchAnalyticsUsers = (filters: AnalyticsFilters = {}) => getJson<AnalyticsUsers>('/analytics/users', filters)
export const fetchAnalyticsServices = (filters: AnalyticsFilters = {}) => getJson<AnalyticsServices>('/analytics/services', filters)
export const fetchAnalyticsWorkflows = (filters: AnalyticsFilters = {}) => getJson<AnalyticsWorkflows>('/analytics/workflows', filters)
export const fetchAnalyticsPerformance = (filters: AnalyticsFilters = {}) => getJson<AnalyticsPerformance>('/analytics/performance', filters)
export const fetchAnalyticsUsage = (filters: AnalyticsFilters = {}) => getJson<AnalyticsUsage>('/analytics/usage', filters)

export type ExportType = 'overview' | 'queries' | 'users' | 'services' | 'workflows' | 'performance'

// Triggers a browser download of the CSV the backend streams back
// (StreamingResponse, media_type text/csv) -- fetched (not a bare <a
// href>) specifically so the Authorization header can be attached; a
// plain link can't carry it. Throws the same `${path} ${status}` shape
// every other function in this file does, including a 403 -- an
// unauthorized export attempt surfaces the same way an unauthorized
// dashboard load already does, not a silently-empty file.
export async function exportAnalyticsCsv(type: ExportType, filters: AnalyticsFilters = {}): Promise<void> {
  const qs = buildQuery(filters)
  qs.set('type', type)
  const r = await apiFetch(`/analytics/export?${qs.toString()}`)
  if (!r.ok) throw new Error(`/analytics/export ${r.status}`)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `analytics_${type}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
