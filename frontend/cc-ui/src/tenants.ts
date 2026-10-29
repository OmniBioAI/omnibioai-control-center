import { authHeaders, reportUnauthorized } from './auth'

export type PlanId = 'free' | 'plus' | 'pro'
export type MembershipStatus = 'active' | 'trialing' | 'past_due' | 'canceled' | 'none'
export type StorageStatus = 'ok' | 'near' | 'over_allocation'

export interface PlanChange { from_plan: PlanId; to_plan: PlanId; at: string }
export interface TenantRow {
  tenant_id: string; username: string; email: string; plan_id: PlanId
  membership_status: MembershipStatus; effective_plan_id: PlanId
  valid_from: string | null; valid_until: string | null; auto_renew: boolean
  days_remaining: number | null; allocated_bytes: number
  allocation_source: 'plan' | 'override'; used_bytes: number; reserved_bytes: number
  pct: number; storage_status: StorageStatus; last_plan_change: PlanChange | null
  last_activity_at: string | null
}
export interface TenantSummary {
  tenants_total: number; per_plan: Record<PlanId, number>
  allocated_sum_bytes: number; used_sum_bytes: number; pool_capacity_bytes: number
  expiring_7d: number; past_due: number; over_allocation: number
}
export interface PlanHistoryItem extends PlanChange {
  old_allocated_bytes: number; new_allocated_bytes: number
  source: 'stripe_webhook' | 'admin_override' | 'payment_grace'
  actor: string | null; reason: string | null
}
export interface StorageOverride { allocated_bytes: number; reason: string; actor: string; expires_at: string | null }
export interface TenantDetail extends TenantRow {
  plan_history: PlanHistoryItem[]; override: StorageOverride | null
  top_allocations: { artifact_id: string; name: string; bytes: number; created_at: string }[]
  workflow_output_bytes: number; usage_trend_30d: { day: string; used_bytes: number }[]
}
export interface TenantListResponse { items: TenantRow[]; total: number }
export interface TenantQuery {
  plan?: PlanId | ''; status?: MembershipStatus | ''; validity?: 'expiring_7d' | 'expiring_30d' | 'expired' | ''
  storage_status?: 'near' | 'over_allocation' | ''; q?: string; sort?: string; page?: number; page_size?: number
}

export const DECIMAL_GB = 1_000_000_000
export function formatGB(bytes: number): string { return `${(bytes / DECIMAL_GB).toLocaleString(undefined, { maximumFractionDigits: 2 })} GB` }
export function storageStatus(used: number, allocated: number): StorageStatus {
  if (used > allocated) return 'over_allocation'
  return allocated > 0 && used / allocated >= .8 ? 'near' : 'ok'
}

const now = new Date()
const iso = (days: number) => new Date(now.getTime() + days * 86_400_000).toISOString()
const planBytes: Record<PlanId, number> = { free: DECIMAL_GB, plus: 20 * DECIMAL_GB, pro: 100 * DECIMAL_GB }
const seed: TenantDetail[] = [
  mockTenant('1042', 'maya', 'maya@example.org', 'pro', 'active', 73 * DECIMAL_GB, 18, true),
  mockTenant('1043', 'liam', 'liam@example.org', 'plus', 'trialing', 4.2 * DECIMAL_GB, 6, true),
  mockTenant('1044', 'sora', 'sora@example.org', 'plus', 'past_due', 18 * DECIMAL_GB, 3, false),
  mockTenant('1045', 'noah', 'noah@example.org', 'pro', 'canceled', 1.2 * DECIMAL_GB, -2, false),
  mockTenant('1046', 'ava', 'ava@example.org', 'free', 'none', .35 * DECIMAL_GB, null, false),
  mockTenant('1047', 'chen', 'chen@example.org', 'plus', 'active', 24 * DECIMAL_GB, 25, true, 30 * DECIMAL_GB),
]

function mockTenant(id: string, username: string, email: string, plan: PlanId, status: MembershipStatus, used: number, days: number | null, renew: boolean, override?: number): TenantDetail {
  const effective: PlanId = (status === 'active' || status === 'trialing') ? plan : 'free'
  const allocated = override ?? planBytes[effective]
  const row: TenantRow = {
    tenant_id: id, username, email, plan_id: plan, membership_status: status, effective_plan_id: effective,
    valid_from: status === 'none' ? null : iso(-12), valid_until: days == null ? null : iso(days), auto_renew: renew,
    days_remaining: days, allocated_bytes: allocated, allocation_source: override ? 'override' : 'plan',
    used_bytes: used, reserved_bytes: Math.round(used * .03), pct: allocated ? Math.round(used / allocated * 10_000) / 100 : 0,
    storage_status: storageStatus(used, allocated), last_plan_change: plan === 'free' ? null : { from_plan: 'free', to_plan: plan, at: iso(-42) },
    last_activity_at: iso(-1),
  }
  return {
    ...row,
    plan_history: row.last_plan_change ? [{ ...row.last_plan_change, old_allocated_bytes: planBytes.free, new_allocated_bytes: planBytes[plan], source: 'stripe_webhook', actor: 'stripe', reason: 'Subscription updated' }] : [],
    override: override ? { allocated_bytes: override, reason: 'Temporary research import', actor: 'platform-admin@example.org', expires_at: iso(14) } : null,
    top_allocations: [{ artifact_id: `artifact-${id}-1`, name: 'sequencing-results.tar', bytes: Math.round(used * .42), created_at: iso(-8) }, { artifact_id: `artifact-${id}-2`, name: 'analysis-output.zarr', bytes: Math.round(used * .21), created_at: iso(-4) }],
    workflow_output_bytes: Math.round(used * .08),
    usage_trend_30d: Array.from({ length: 30 }, (_, i) => ({ day: iso(i - 29).slice(0, 10), used_bytes: Math.max(0, Math.round(used * (.62 + i * .013))) })),
  }
}

function useMocks(): boolean { return import.meta.env.VITE_TENANTS_MOCKS === 'true' }
async function jsonFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(init.headers ?? {}) } })
  if (response.status === 401) reportUnauthorized()
  if (!response.ok) { const error = new Error(`${path} ${response.status}`); Object.assign(error, { status: response.status }); throw error }
  return response.status === 204 ? undefined as T : response.json()
}

export async function fetchTenantSummary(): Promise<TenantSummary> {
  if (!useMocks()) return jsonFetch('/admin/tenants/summary')
  const rows = seed
  return {
    tenants_total: rows.length,
    per_plan: { free: rows.filter(x => x.effective_plan_id === 'free').length, plus: rows.filter(x => x.effective_plan_id === 'plus').length, pro: rows.filter(x => x.effective_plan_id === 'pro').length },
    allocated_sum_bytes: rows.reduce((n, x) => n + x.allocated_bytes, 0), used_sum_bytes: rows.reduce((n, x) => n + x.used_bytes, 0), pool_capacity_bytes: 2_000 * DECIMAL_GB,
    expiring_7d: rows.filter(x => x.days_remaining != null && x.days_remaining >= 0 && x.days_remaining <= 7).length,
    past_due: rows.filter(x => x.membership_status === 'past_due').length,
    over_allocation: rows.filter(x => x.storage_status === 'over_allocation').length,
  }
}

export function filterMockTenants(input: TenantDetail[], query: TenantQuery): TenantDetail[] {
  const q = query.q?.trim().toLowerCase()
  let rows = input.filter(row =>
    (!query.plan || row.effective_plan_id === query.plan) && (!query.status || row.membership_status === query.status) &&
    (!query.storage_status || row.storage_status === query.storage_status) &&
    (!q || [row.tenant_id, row.username, row.email].some(v => v.toLowerCase().includes(q))) &&
    (!query.validity || (query.validity === 'expired' ? (row.days_remaining ?? 1) < 0 : query.validity === 'expiring_7d' ? row.days_remaining != null && row.days_remaining >= 0 && row.days_remaining <= 7 : row.days_remaining != null && row.days_remaining >= 0 && row.days_remaining <= 30))
  )
  const rawSort = query.sort || 'username'
  const descending = rawSort.startsWith('-')
  const key = (descending ? rawSort.slice(1) : rawSort) as keyof TenantRow
  rows = [...rows].sort((a, b) => String(a[key] ?? '').localeCompare(String(b[key] ?? ''), undefined, { numeric: true }) * (descending ? -1 : 1))
  return rows
}

export async function fetchTenants(query: TenantQuery = {}): Promise<TenantListResponse> {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([k, v]) => { if (v !== '' && v != null) params.set(k, String(v)) })
  if (!useMocks()) return jsonFetch(`/admin/tenants?${params}`)
  const filtered = filterMockTenants(seed, query)
  const page = query.page ?? 1, size = query.page_size ?? 20
  return { items: filtered.slice((page - 1) * size, page * size), total: filtered.length }
}
export async function fetchTenant(id: string): Promise<TenantDetail> {
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}`)
  const found = seed.find(x => x.tenant_id === id); if (!found) throw Object.assign(new Error('Tenant not found'), { status: 404 }); return structuredClone(found)
}
export async function setStorageOverride(id: string, body: { allocated_bytes: number; reason: string; expires_at?: string | null }): Promise<TenantDetail> {
  if (!body.reason.trim()) throw new Error('Reason is required')
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}/storage-override`, { method: 'PUT', body: JSON.stringify(body) })
  const row = seed.find(x => x.tenant_id === id); if (!row) throw new Error('Tenant not found')
  row.override = { ...body, actor: 'mock-platform-admin', expires_at: body.expires_at ?? null }; row.allocated_bytes = body.allocated_bytes; row.allocation_source = 'override'; row.pct = Math.round(row.used_bytes / row.allocated_bytes * 10_000) / 100; row.storage_status = storageStatus(row.used_bytes, row.allocated_bytes); return structuredClone(row)
}
export async function clearStorageOverride(id: string, reason: string): Promise<TenantDetail> {
  if (!reason.trim()) throw new Error('Reason is required')
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}/storage-override`, { method: 'DELETE', body: JSON.stringify({ reason }) })
  const row = seed.find(x => x.tenant_id === id); if (!row) throw new Error('Tenant not found')
  row.override = null; row.allocated_bytes = planBytes[row.effective_plan_id]; row.allocation_source = 'plan'; row.pct = Math.round(row.used_bytes / row.allocated_bytes * 10_000) / 100; row.storage_status = storageStatus(row.used_bytes, row.allocated_bytes); return structuredClone(row)
}
export async function recomputeTenantUsage(id: string, reason: string): Promise<TenantDetail> {
  if (!reason.trim()) throw new Error('Reason is required')
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}/recompute-usage`, { method: 'POST', body: JSON.stringify({ reason }) })
  return fetchTenant(id)
}

export function tenantsCsv(rows: TenantRow[]): string {
  const values = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const keys: (keyof TenantRow)[] = ['tenant_id', 'username', 'email', 'effective_plan_id', 'membership_status', 'valid_until', 'allocated_bytes', 'used_bytes', 'reserved_bytes', 'pct', 'storage_status']
  return [keys.join(','), ...rows.map(row => keys.map(key => values(row[key])).join(','))].join('\n')
}
