// Phase 3 PR2: Organizations page data layer. Kept as its own module
// rather than growing api.ts further -- this is a genuinely new feature
// area (not one more control-center-native endpoint like /docker or
// /config), and future admin-console pages (Users, Roles, SSO, Audit)
// will likely each want the same treatment rather than one growing
// monolith.
//
// Every call here hits control-center's own backend at a relative path
// (routes_org_proxy.py proxies it to omnibioai-auth) -- exactly the same
// apiFetch/authHeaders pattern api.ts already uses, so 401 handling stays
// centralized. No function here makes an authorization *decision* --
// that's entirely omnibioai-auth's job (require_permission/require_org_
// permission_or_platform_admin, Phase 3 PR0.4) -- this module only knows
// how to call the two endpoint families and shape the responses.
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

// ── Shared shapes ────────────────────────────────────────────────────────

export interface ResourceCountSummary {
  total: number
  active: number | null
  invited: number | null
  revoked: number | null
  most_recent_at: string | null
}

export interface SSOConfigSummary {
  configured: boolean
  provider_type: string | null
  issuer: string | null
  status: string | null
  enforced: boolean
  override_active: boolean
}

export interface RecentActivity {
  org_created_at: string | null
  most_recent_member_joined_at: string | null
  most_recent_api_key_created_at: string | null
  most_recent_oauth_client_created_at: string | null
}

// ── GET /platform/orgs (platform admin, cross-tenant) ──────────────────────

export interface PlatformOrgSummary {
  id: number
  name: string
  status: string
  created_at: string
  owner_email: string | null
  member_count: number
  team_count: number
  api_key_count: number
  oauth_client_count: number
  license_count: number
  sso_enabled: boolean
}

export interface PlatformOrgListResponse {
  items: PlatformOrgSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export type OrgSortField = 'name' | 'created_at' | 'status' | 'owner_email'
export type SortOrder = 'asc' | 'desc'

export interface PlatformOrgListParams {
  page?: number
  pageSize?: number
  search?: string
  sortBy?: OrgSortField
  sortOrder?: SortOrder
}

export async function fetchPlatformOrgs(params: PlatformOrgListParams = {}): Promise<PlatformOrgListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.pageSize ?? 20))
  if (params.search) qs.set('search', params.search)
  qs.set('sort_by', params.sortBy ?? 'created_at')
  qs.set('sort_order', params.sortOrder ?? 'desc')

  const r = await apiFetch(`/platform/orgs?${qs.toString()}`)
  if (!r.ok) throw new Error(`/platform/orgs ${r.status}`)
  return r.json()
}

export interface PlatformOrgDetail {
  id: number
  slug: string
  name: string
  plan: string
  status: string
  created_at: string
  owner_user_id: number | null
  owner_email: string | null
  member_summary: ResourceCountSummary
  team_summary: ResourceCountSummary
  api_key_summary: ResourceCountSummary
  oauth_client_summary: ResourceCountSummary
  license_summary: ResourceCountSummary
  sso: SSOConfigSummary
  recent_activity: RecentActivity
  status_changed_at: string | null
  status_changed_reason: string | null
  status_changed_by_email: string | null
}

export async function fetchPlatformOrgDetail(orgId: number): Promise<PlatformOrgDetail> {
  const r = await apiFetch(`/platform/orgs/${orgId}`)
  if (!r.ok) throw new Error(`/platform/orgs/${orgId} ${r.status}`)
  return r.json()
}

// ── /orgs (org-scoped -- "my orgs" only, never cross-tenant) ───────────────

export interface MyOrg {
  id: number
  slug: string
  name: string
  plan: string
  status: string
  status_changed_at: string | null
  status_changed_reason: string | null
  status_changed_by_user_id: number | null
}

export async function fetchMyOrgs(): Promise<MyOrg[]> {
  const r = await apiFetch('/orgs')
  if (!r.ok) throw new Error(`/orgs ${r.status}`)
  return r.json()
}

export async function fetchMyOrg(orgId: number): Promise<MyOrg> {
  const r = await apiFetch(`/orgs/${orgId}`)
  if (!r.ok) throw new Error(`/orgs/${orgId} ${r.status}`)
  return r.json()
}

export async function createOrganization(name: string, slug: string): Promise<MyOrg> {
  const r = await apiFetch('/orgs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, slug }),
  })
  if (!r.ok) throw new Error(`/orgs ${r.status}`)
  return r.json()
}

// Phase 3 PR2: platform-admin-only server-side (omnibioai-auth's PATCH
// /orgs/{org_id} rejects this with 403 for anyone lacking manage_all_orgs
// -- this function does not and cannot enforce that itself, it just calls
// the endpoint and surfaces whatever the backend decides).
export async function setOrganizationStatus(
  orgId: number,
  status: 'active' | 'suspended',
  reason?: string,
): Promise<MyOrg> {
  const r = await apiFetch(`/orgs/${orgId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, status_reason: reason }),
  })
  if (!r.ok) throw new Error(`/orgs/${orgId} ${r.status}`)
  return r.json()
}
