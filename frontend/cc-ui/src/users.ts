// Phase 3 PR3A: Users page data layer, mirroring organizations.ts's own
// shape exactly (Phase 3 PR2) -- kept as its own module for the same
// reason organizations.ts is: a genuinely new feature area, not one more
// control-center-native endpoint. Every call hits control-center's own
// backend at a relative path (routes_org_proxy.py's new /platform/users
// routes proxy it to omnibioai-auth); no function here makes an
// authorization decision -- that's entirely omnibioai-auth's job
// (require_permission(MANAGE_ALL_ORGS), Phase 3 PR0.4/PR1).
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

export interface PlatformUserSummary {
  id: number
  email: string
  status: string
  created_at: string | null
  global_roles: string[]
  org_count: number
}

export interface PlatformUserListResponse {
  items: PlatformUserSummary[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export type UserSortField = 'email' | 'created_at' | 'status'
export type SortOrder = 'asc' | 'desc'

export interface PlatformUserListParams {
  page?: number
  pageSize?: number
  search?: string
  sortBy?: UserSortField
  sortOrder?: SortOrder
}

export async function fetchPlatformUsers(params: PlatformUserListParams = {}): Promise<PlatformUserListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.pageSize ?? 20))
  if (params.search) qs.set('search', params.search)
  qs.set('sort_by', params.sortBy ?? 'created_at')
  qs.set('sort_order', params.sortOrder ?? 'desc')

  const r = await apiFetch(`/platform/users?${qs.toString()}`)
  if (!r.ok) throw new Error(`/platform/users ${r.status}`)
  return r.json()
}

export interface OrgMembershipSummary {
  organization_id: number
  organization_name: string
  organization_slug: string
  roles: string[]
  status: string
  joined_at: string | null
}

export interface PlatformUserDetail {
  id: number
  email: string
  status: string
  created_at: string | null
  global_roles: string[]
  memberships: OrgMembershipSummary[]
  status_changed_at: string | null
  status_changed_reason: string | null
  status_changed_by_email: string | null
}

export async function fetchPlatformUserDetail(userId: number): Promise<PlatformUserDetail> {
  const r = await apiFetch(`/platform/users/${userId}`)
  if (!r.ok) throw new Error(`/platform/users/${userId} ${r.status}`)
  return r.json()
}

// Platform-admin-only server-side (omnibioai-auth's PATCH /platform/users/{id}
// rejects this with 403 for anyone lacking manage_all_orgs) -- this
// function does not and cannot enforce that itself.
export async function setUserStatus(
  userId: number,
  status: 'active' | 'suspended',
  reason?: string,
): Promise<PlatformUserDetail> {
  const r = await apiFetch(`/platform/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, reason }),
  })
  if (!r.ok) throw new Error(`/platform/users/${userId} ${r.status}`)
  return r.json()
}
