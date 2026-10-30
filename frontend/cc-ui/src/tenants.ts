import { authHeaders, reportUnauthorized } from './auth'

export type PlanId = 'free' | 'plus' | 'pro'
export type MembershipStatus = 'active' | 'trialing' | 'past_due' | 'canceled' | 'none'
export type StorageStatus = 'ok' | 'near' | 'over_allocation'
export type PlanSource = 'stripe' | 'promo' | 'free'

export interface PlanChange { from_plan: PlanId; to_plan: PlanId; at: string }
export interface TenantRow {
  tenant_id: string; username: string; email: string; plan_id: PlanId
  membership_status: MembershipStatus; effective_plan_id: PlanId
  plan_source: PlanSource; promo_expires_at: string | null
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
  promos_active: number; promos_expiring_7d: number
}
export interface PlanHistoryItem extends PlanChange {
  old_allocated_bytes: number; new_allocated_bytes: number
  source: 'stripe_webhook' | 'admin_override' | 'payment_grace' | 'admin_promo' | 'promo_expired'
  event?: string
  actor: string | null; actor_display?: string | null; reason: string | null
}
export interface StorageOverride { allocated_bytes: number; reason: string; actor: string; expires_at: string | null }
export interface PlanGrant { id: number; plan_id: 'plus' | 'pro'; starts_at: string; expires_at: string; reason: string; granted_by: string; created_at: string; revoked_at: string | null; revoked_by: string | null; revoke_reason: string | null }
export interface TenantDetail extends TenantRow {
  plan_history: PlanHistoryItem[]; override: StorageOverride | null
  active_grant: PlanGrant | null; grant_history: PlanGrant[]
  top_allocations: { artifact_id: string; name: string; bytes: number; created_at: string }[]
  workflow_output_bytes: number; usage_trend_30d: { day: string; used_bytes: number }[]
}
export interface TenantListResponse { items: TenantRow[]; total: number }
export interface TenantQuery {
  plan?: PlanId | ''; status?: MembershipStatus | ''; validity?: 'expiring_7d' | 'expiring_30d' | 'expired' | ''
  plan_source?: PlanSource | ''; storage_status?: 'ok' | 'near' | 'over_allocation' | ''; q?: string; sort?: string; page?: number; page_size?: number
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
  mockTenant('1048', 'priya', 'priya@example.org', 'free', 'none', 12 * DECIMAL_GB, null, false, undefined, 'pro'),
]

function mockTenant(id: string, username: string, email: string, plan: PlanId, status: MembershipStatus, used: number, days: number | null, renew: boolean, override?: number, promoPlan?: 'plus' | 'pro'): TenantDetail {
  const effective: PlanId = promoPlan ?? ((status === 'active' || status === 'trialing') ? plan : 'free')
  const source: PlanSource = promoPlan ? 'promo' : effective === 'free' ? 'free' : 'stripe'
  const allocated = override ?? planBytes[effective]
  const row: TenantRow = {
    tenant_id: id, username, email, plan_id: plan, membership_status: status, effective_plan_id: effective, plan_source: source, promo_expires_at: promoPlan ? iso(12) : null,
    valid_from: status === 'none' ? null : iso(-12), valid_until: days == null ? null : iso(days), auto_renew: renew,
    days_remaining: days, allocated_bytes: allocated, allocation_source: override ? 'override' : 'plan',
    used_bytes: used, reserved_bytes: Math.round(used * .03), pct: allocated ? Math.round(used / allocated * 10_000) / 100 : 0,
    storage_status: storageStatus(used, allocated), last_plan_change: plan === 'free' ? null : { from_plan: 'free', to_plan: plan, at: iso(-42) },
    last_activity_at: iso(-1),
  }
  return {
    ...row,
    plan_history: promoPlan ? [{ from_plan: 'free', to_plan: promoPlan, at: iso(-2), old_allocated_bytes: planBytes.free, new_allocated_bytes: planBytes[promoPlan], source: 'admin_promo', event: 'promo_granted', actor: 'mock-platform-admin', reason: 'Launch promotion' }] : row.last_plan_change ? [{ ...row.last_plan_change, old_allocated_bytes: planBytes.free, new_allocated_bytes: planBytes[plan], source: 'stripe_webhook', actor: 'stripe', reason: 'Subscription updated' }] : [],
    override: override ? { allocated_bytes: override, reason: 'Temporary research import', actor: 'platform-admin@example.org', expires_at: iso(14) } : null,
    active_grant: promoPlan ? { id: Number(id), plan_id: promoPlan, starts_at: iso(-2), expires_at: iso(12), reason: 'Launch promotion', granted_by: 'mock-platform-admin', created_at: iso(-2), revoked_at: null, revoked_by: null, revoke_reason: null } : null,
    grant_history: [],
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
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase()
  if (contentType !== 'application/json' && !contentType?.match(/^application\/[^\s;]+\+json$/)) {
    throw new Error(`Tenant API returned a non-JSON response (${contentType || 'missing Content-Type'}). Check the tenant API proxy configuration.`)
  }
  return response.json()
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
    promos_active: rows.filter(x => Boolean(x.promo_expires_at)).length,
    promos_expiring_7d: rows.filter(x => x.promo_expires_at && new Date(x.promo_expires_at).getTime() <= now.getTime() + 7 * 86_400_000).length,
  }
}

export function filterMockTenants(input: TenantDetail[], query: TenantQuery): TenantDetail[] {
  const q = query.q?.trim().toLowerCase()
  let rows = input.filter(row =>
    (!query.plan || row.effective_plan_id === query.plan) && (!query.status || row.membership_status === query.status) &&
    (!query.plan_source || row.plan_source === query.plan_source) &&
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
  const page = query.page ?? 1, size = query.page_size ?? 50
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

export async function grantPromoPlan(id: string, body: { plan_id: 'plus' | 'pro'; days?: number; expires_at?: string; reason: string }): Promise<TenantDetail> {
  if (!body.reason.trim()) throw new Error('Reason is required')
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}/plan-grant`, { method: 'POST', body: JSON.stringify(body) })
  const row = seed.find(x => x.tenant_id === id); if (!row) throw new Error('Tenant not found')
  const expires = body.expires_at ?? iso(body.days ?? 30), previous = row.effective_plan_id
  const paid = (row.membership_status === 'active' || row.membership_status === 'trialing') && row.plan_id !== 'free' ? row.plan_id : 'free'
  const effective = planBytes[paid] >= planBytes[body.plan_id] ? paid : body.plan_id
  row.plan_source = effective === paid && paid !== 'free' ? 'stripe' : 'promo'; row.effective_plan_id = effective; row.promo_expires_at = expires
  row.active_grant = { id: Date.now(), plan_id: body.plan_id, starts_at: new Date().toISOString(), expires_at: expires, reason: body.reason, granted_by: 'mock-platform-admin', created_at: new Date().toISOString(), revoked_at: null, revoked_by: null, revoke_reason: null }
  row.grant_history.unshift(row.active_grant); row.plan_history.unshift({ from_plan: previous, to_plan: effective, at: new Date().toISOString(), old_allocated_bytes: planBytes[previous], new_allocated_bytes: planBytes[effective], source: 'admin_promo', event: 'promo_granted', actor: 'mock-platform-admin', reason: body.reason })
  if (!row.override) { row.allocated_bytes = planBytes[effective]; row.allocation_source = 'plan' }
  row.pct = Math.round(row.used_bytes / row.allocated_bytes * 10_000) / 100; row.storage_status = storageStatus(row.used_bytes, row.allocated_bytes)
  return structuredClone(row)
}

export async function revokePromoPlan(id: string, reason: string): Promise<TenantDetail> {
  if (!reason.trim()) throw new Error('Reason is required')
  if (!useMocks()) return jsonFetch(`/admin/tenants/${encodeURIComponent(id)}/plan-grant`, { method: 'DELETE', body: JSON.stringify({ reason }) })
  const row = seed.find(x => x.tenant_id === id); if (!row) throw new Error('Tenant not found')
  const previous = row.effective_plan_id, paid = (row.membership_status === 'active' || row.membership_status === 'trialing') && row.plan_id !== 'free'
  row.effective_plan_id = paid ? row.plan_id : 'free'; row.plan_source = paid ? 'stripe' : 'free'; row.promo_expires_at = null
  if (row.active_grant) { row.active_grant.revoked_at = new Date().toISOString(); row.active_grant.revoked_by = 'mock-platform-admin'; row.active_grant.revoke_reason = reason }
  row.active_grant = null; row.plan_history.unshift({ from_plan: previous, to_plan: row.effective_plan_id, at: new Date().toISOString(), old_allocated_bytes: planBytes[previous], new_allocated_bytes: planBytes[row.effective_plan_id], source: 'admin_promo', event: 'promo_revoked', actor: 'mock-platform-admin', reason })
  if (!row.override) { row.allocated_bytes = planBytes[row.effective_plan_id]; row.allocation_source = 'plan' }
  row.pct = Math.round(row.used_bytes / row.allocated_bytes * 10_000) / 100; row.storage_status = storageStatus(row.used_bytes, row.allocated_bytes)
  return structuredClone(row)
}

export function tenantsCsv(rows: TenantRow[]): string {
  const values = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const keys: (keyof TenantRow)[] = ['tenant_id', 'username', 'email', 'effective_plan_id', 'plan_source', 'promo_expires_at', 'membership_status', 'valid_until', 'allocated_bytes', 'used_bytes', 'reserved_bytes', 'pct', 'storage_status']
  return [keys.join(','), ...rows.map(row => keys.map(key => values(row[key])).join(','))].join('\n')
}
