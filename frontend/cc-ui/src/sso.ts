// PR11.3: Enterprise SSO Management data layer, mirroring roles.ts/teams.ts's
// own shape exactly. Every call hits control-center's own backend at a
// relative path (routes_org_sso_proxy.py proxies the /orgs/{org_id}/sso*
// surface to omnibioai-auth); no function here makes an authorization
// decision -- that's entirely omnibioai-auth's job
// (require_org_permission_or_platform_admin(MANAGE_SSO) for the 4 CRUD
// functions, require_permission(OVERRIDE_SSO_ENFORCEMENT) for the 2
// override functions).
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

// Mirrors omnibioai-auth's OrgSSOConfigOut (app/schemas/org_sso.py)
// exactly -- deliberately no client_secret / client_secret_encrypted
// field exists here, because the backend response never includes one
// either. See docs/admin-console-pr11-sso-discovery.md.
export interface OrgSSOConfig {
  issuer: string
  client_id: string
  provider_type: string
  allowed_domains: string[]
  status: string // "pending_verification" | "active" | "disabled"
  created_at: string | null
  updated_at: string | null
  enforced: boolean
  sso_override_active: boolean
}

export interface OrgSSOConfigInput {
  issuer: string
  client_id: string
  // Only present on create, or on update when the admin is rotating it --
  // never pre-filled from a GET response (the backend never returns one to
  // pre-fill it with in the first place).
  client_secret: string
  allowed_domains?: string[]
}

export interface OrgSSOConfigUpdateInput {
  issuer?: string
  client_id?: string
  client_secret?: string
  allowed_domains?: string[]
  enforced?: boolean
}

export async function fetchOrgSSOConfig(orgId: number): Promise<OrgSSOConfig> {
  const r = await apiFetch(`/orgs/${orgId}/sso`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/sso ${r.status}`)
  return r.json()
}

export async function createOrgSSOConfig(orgId: number, body: OrgSSOConfigInput): Promise<OrgSSOConfig> {
  const r = await apiFetch(`/orgs/${orgId}/sso`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/sso`))
  return r.json()
}

export async function updateOrgSSOConfig(orgId: number, body: OrgSSOConfigUpdateInput): Promise<OrgSSOConfig> {
  const r = await apiFetch(`/orgs/${orgId}/sso`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/sso`))
  return r.json()
}

export async function deleteOrgSSOConfig(orgId: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/sso`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/orgs/${orgId}/sso ${r.status}`)
}

// ── Break-glass override (override_sso_enforcement, global-admin only) ────

export async function enableSSOOverride(orgId: number, reason: string): Promise<OrgSSOConfig> {
  const r = await apiFetch(`/orgs/${orgId}/sso/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/sso/override`))
  return r.json()
}

export async function clearSSOOverride(orgId: number): Promise<OrgSSOConfig> {
  const r = await apiFetch(`/orgs/${orgId}/sso/override`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/sso/override`))
  return r.json()
}

// Prefers the backend's own detail message (issuer validation, discovery
// failure, lockout guard, ...) over a bare "<path> <status>" -- those
// messages are already written to be shown directly to an org admin (see
// omnibioai-auth's SSODiscoveryError docstring), so surfacing them as-is
// gives a far more useful inline form error than the generic fallback.
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
