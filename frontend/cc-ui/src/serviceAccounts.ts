// PR11.4: Service Accounts & API Keys data layer, mirroring roles.ts/
// teams.ts's own shape exactly. Every call hits control-center's own
// backend at a relative path (routes_service_accounts_proxy.py proxies
// the /orgs/{org_id}/api-keys*, /orgs/{org_id}/oauth-clients*, and
// /platform/permissions surfaces to omnibioai-auth); no function here
// makes an authorization decision -- that's entirely omnibioai-auth's
// job (require_org_permission_or_platform_admin(manage_api_keys /
// manage_oauth_clients), require_permission(manage_all_orgs)).
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

// Prefers the backend's own detail message (e.g. "Cannot grant scopes
// you don't hold: [...]", "Unknown service permission: ... Did you
// mean: ...?") over a bare "<path> <status>" -- those messages are
// already written to be shown directly to an org admin, same
// convention sso.ts established in PR11.3.
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

// ── API Keys ─────────────────────────────────────────────────────────────
// Mirrors omnibioai-auth's ApiKeyOut (app/schemas/apikeys.py) exactly --
// deliberately no `key`/`key_hash` field, because the backend response
// never includes one either (see docs/admin-console-pr11-service-
// accounts-discovery.md §1). No `created_by` field either -- the
// backend response has none to show.

export interface ApiKey {
  id: number
  name: string | null
  key_prefix: string
  scopes: string[]
  status: string // "active" | "revoked"
  created_at: string | null
  expires_at: string | null
  last_used_at: string | null
}

// Only returned once, from createApiKey -- never refetchable, and this
// type is never reused for a GET response.
export interface ApiKeyCreated {
  id: number
  name: string | null
  key_prefix: string
  scopes: string[]
  key: string
}

export async function fetchApiKeys(orgId: number): Promise<ApiKey[]> {
  const r = await apiFetch(`/orgs/${orgId}/api-keys`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/api-keys ${r.status}`)
  return r.json()
}

export async function createApiKey(orgId: number, name: string, scopes: string[]): Promise<ApiKeyCreated> {
  const r = await apiFetch(`/orgs/${orgId}/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, scopes }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/api-keys`))
  return r.json()
}

export async function revokeApiKey(orgId: number, keyId: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/api-keys/${keyId}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/api-keys/${keyId}`))
}

// ── OAuth Clients / Service Accounts ────────────────────────────────────
// Mirrors OAuthClientOut exactly -- no client_secret/client_secret_hash
// field, same reasoning as ApiKey above.

export interface OAuthClient {
  id: number
  name: string | null
  client_id: string
  scopes: string[]
  status: string // "active" | "revoked"
  created_at: string | null
  expires_at: string | null
  last_used_at: string | null
}

export interface OAuthClientCreated {
  id: number
  name: string | null
  client_id: string
  scopes: string[]
  client_secret: string
}

export async function fetchOAuthClients(orgId: number): Promise<OAuthClient[]> {
  const r = await apiFetch(`/orgs/${orgId}/oauth-clients`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/oauth-clients ${r.status}`)
  return r.json()
}

export async function createOAuthClient(orgId: number, name: string, scopes: string[]): Promise<OAuthClientCreated> {
  const r = await apiFetch(`/orgs/${orgId}/oauth-clients`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, scopes }),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/oauth-clients`))
  return r.json()
}

// key_id here is the OAuthClient row's numeric `id`, never the public
// `client_id` string -- see discovery doc §2 on that naming collision.
export async function revokeOAuthClient(orgId: number, id: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/oauth-clients/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/oauth-clients/${id}`))
}

// ── Permission registry (scope picker support, platform-admin only) ────
// GET /platform/permissions is gated upstream by require_permission
// (manage_all_orgs) -- a non-platform-admin caller gets a 403 from this,
// same as calling omnibioai-auth directly. Callers must treat that as an
// expected, silent "fall back to free text" signal, not an error to
// surface -- see ServiceAccountsPage.tsx's useScopeCatalog.

export interface PermissionDescriptor {
  name: string
  resource: string
  action: string
  scope: string
  category: string
  description: string
  legacy: boolean
  deprecated: boolean
  deprecated_reason: string | null
}

export async function fetchPermissionRegistry(): Promise<PermissionDescriptor[]> {
  const r = await apiFetch('/platform/permissions')
  if (!r.ok) throw new Error(`/platform/permissions ${r.status}`)
  return r.json()
}
