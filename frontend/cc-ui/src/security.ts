// PR11.5.6 (Admin Console Security UI): Organization MFA Policy and
// platform-admin MFA reset data layer, mirroring audit.ts/sso.ts's own
// shape exactly. Every call hits control-center's own backend at a
// relative path (routes_org_mfa_proxy.py / routes_user_proxy.py's new
// route proxy the /orgs/{org_id}/mfa-policy* and
// /platform/users/{id}/mfa/reset surface to omnibioai-auth); no function
// here makes an authorization decision -- that's entirely
// omnibioai-auth's job (require_org_permission_or_platform_admin
// (MANAGE_SSO) for the 3 CRUD functions, require_permission
// (MANAGE_ALL_ORGS) for the 2 override functions and the reset
// function), all from PR11.5.5/PR11.5.4 and unmodified here. See
// docs/pr11-5-6-security-ui-discovery.md.
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

// Mirrors omnibioai-auth's OrgMFAPolicyOut (app/schemas/org_mfa.py)
// exactly -- there is no secret/credential concept on this resource at
// all, unlike OrgSSOConfig, so there is nothing here that could ever
// leak one by omission or otherwise.
export interface OrgMFAPolicy {
  required: boolean
  created_at: string | null
  updated_at: string | null
  enabled_at: string | null
  enabled_by_email: string | null
  override_active: boolean
  override_reason: string | null
}

export async function fetchOrgMFAPolicy(orgId: number): Promise<OrgMFAPolicy> {
  const r = await apiFetch(`/orgs/${orgId}/mfa-policy`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/mfa-policy ${r.status}`)
  return r.json()
}

export async function createOrgMFAPolicy(orgId: number, required: boolean): Promise<OrgMFAPolicy> {
  const r = await apiFetch(`/orgs/${orgId}/mfa-policy`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ required }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/mfa-policy`))
  return r.json()
}

export async function updateOrgMFAPolicy(orgId: number, required: boolean, reason?: string): Promise<OrgMFAPolicy> {
  const r = await apiFetch(`/orgs/${orgId}/mfa-policy`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ required, ...(reason ? { reason } : {}) }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/mfa-policy`))
  return r.json()
}

// ── Break-glass override (manage_all_orgs, global-admin only) ──────────────

export async function enableMFAPolicyOverride(orgId: number, reason: string): Promise<OrgMFAPolicy> {
  const r = await apiFetch(`/orgs/${orgId}/mfa-policy/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/mfa-policy/override`))
  return r.json()
}

export async function clearMFAPolicyOverride(orgId: number): Promise<OrgMFAPolicy> {
  const r = await apiFetch(`/orgs/${orgId}/mfa-policy/override`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/mfa-policy/override`))
  return r.json()
}

// ── Platform-admin MFA reset (reuses PR11.5.4's existing endpoint) ─────────

export interface MFAResetResult {
  user_id: number
  mfa_enabled: boolean
  mfa_status: string
}

export async function resetUserMFA(userId: number): Promise<MFAResetResult> {
  const r = await apiFetch(`/platform/users/${userId}/mfa/reset`, { method: 'POST' })
  if (!r.ok) throw new Error(await _errorMessage(r, `/platform/users/${userId}/mfa/reset`))
  return r.json()
}

// Same helper as sso.ts's own -- prefers the backend's own detail
// message over a bare "<path> <status>" fallback.
async function _errorMessage(r: Response, path: string): Promise<string> {
  try {
    const data = await r.json()
    if (typeof data?.detail === 'string') return data.detail
    if (typeof data?.error === 'string') return data.error
  } catch {
    // fall through to the generic message below
  }
  return `${path} ${r.status}`
}
