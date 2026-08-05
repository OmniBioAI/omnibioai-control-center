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
  // PR11.1: null means no live source (never logged in since the
  // backend migration that added these, or predates it) -- rendered as
  // "Not available", never fabricated. See routes_dashboard.py's own
  // convention, reused here.
  last_login_at: string | null
  authentication_method: string | null
  // PR11.5.6 (Admin Console Security UI): live User.mfa_enabled column
  // (PR11.5.1), same null-means-no-data convention this file already
  // uses for last_login_at above -- see security.ts /
  // docs/pr11-5-6-security-ui-discovery.md.
  mfa_enabled: boolean
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
  // PR11.1: all three optional and independent, matching
  // GET /platform/users' own backward-compatible query params
  // (routes_platform_users.py) -- omitted means unfiltered, same as before.
  organizationId?: number
  status?: string
  role?: string
}

export async function fetchPlatformUsers(params: PlatformUserListParams = {}): Promise<PlatformUserListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(params.page ?? 1))
  qs.set('page_size', String(params.pageSize ?? 20))
  if (params.search) qs.set('search', params.search)
  if (params.organizationId != null) qs.set('organization_id', String(params.organizationId))
  if (params.status) qs.set('status', params.status)
  if (params.role) qs.set('role', params.role)
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

// PR11.5.6: mirrors omnibioai-auth's PlatformMFADeviceSummary
// (app/schemas/user_admin.py) exactly -- no id, no encrypted_secret,
// see that schema's own docstring for why.
export interface PlatformMFADeviceSummary {
  device_type: string
  label: string | null
  created_at: string
  last_used_at: string | null
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
  last_login_at: string | null
  authentication_method: string | null
  // PR11.5.6: live User.mfa_* columns (PR11.5.1) plus two small,
  // already-scoped queries against MFADevice/MFARecoveryCode -- never a
  // TOTP secret or a recovery code. See security.ts /
  // docs/pr11-5-6-security-ui-discovery.md.
  mfa_enabled: boolean
  mfa_status: string
  mfa_primary_method: string | null
  mfa_enabled_at: string | null
  mfa_last_verified_at: string | null
  mfa_devices: PlatformMFADeviceSummary[]
  mfa_recovery_codes_remaining: number
}

// PR11.1: display labels for the persisted authentication_method
// vocabulary (password/oauth/oidc/unknown -- see omnibioai-auth's
// auth_service._persisted_auth_method for where these values come from).
// A value outside this map (shouldn't happen, but this is API data, not
// a closed TS union) falls back to the raw string rather than hiding it.
const AUTH_METHOD_LABELS: Record<string, string> = {
  password: 'Password',
  oauth: 'OAuth',
  oidc: 'OIDC',
  unknown: 'Unknown',
}

export function authMethodLabel(method: string | null): string {
  if (method == null) return 'Not available'
  return AUTH_METHOD_LABELS[method] ?? method
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
