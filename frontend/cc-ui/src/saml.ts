// PR9 (SAML Admin UI): Organization SAML Configuration data layer,
// mirroring sso.ts/security.ts's own shape exactly. Every call hits
// control-center's own backend at a relative path
// (routes_org_saml_proxy.py proxies the /orgs/{org_id}/saml surface,
// plus GET /auth/saml/{org_slug}/metadata, to omnibioai-auth); no
// function here makes an authorization decision -- that's entirely
// omnibioai-auth's job (require_org_permission_or_platform_admin
// (MANAGE_SSO), PR8/auth#49, unmodified).
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

// Mirrors omnibioai-auth's OrgSAMLConfigOut (app/schemas/org_saml.py)
// exactly. x509_certificate is a public IdP signing certificate, not a
// secret (unlike sso.ts's deliberate omission of client_secret) -- see
// PR8's own schema docstring -- so it round-trips here as-is.
export interface OrgSAMLConfig {
  entity_id: string
  sso_url: string
  x509_certificate: string
  attribute_mapping: Record<string, string> | null
  // Persisted on the backend but NOT read by the SAML login/ACS path --
  // only `status` gates authentication (see omnibioai-auth's PR8
  // report). Kept here for schema completeness / because the backend
  // returns it, never presented as a working "disable login" control.
  enabled: boolean
  status: string // "pending_verification" | "active" | "disabled"
  created_at: string | null
  updated_at: string | null
}

export interface OrgSAMLConfigCreateInput {
  entity_id: string
  sso_url: string
  x509_certificate: string
  attribute_mapping?: Record<string, string> | null
}

export interface OrgSAMLConfigUpdateInput {
  entity_id?: string
  sso_url?: string
  x509_certificate?: string
  attribute_mapping?: Record<string, string> | null
  enabled?: boolean
  status?: string
}

export async function fetchOrgSAMLConfig(orgId: number): Promise<OrgSAMLConfig> {
  const r = await apiFetch(`/orgs/${orgId}/saml`)
  if (!r.ok) throw new Error(`/orgs/${orgId}/saml ${r.status}`)
  return r.json()
}

export async function createOrgSAMLConfig(orgId: number, body: OrgSAMLConfigCreateInput): Promise<OrgSAMLConfig> {
  const r = await apiFetch(`/orgs/${orgId}/saml`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/saml`))
  return r.json()
}

export async function updateOrgSAMLConfig(orgId: number, body: OrgSAMLConfigUpdateInput): Promise<OrgSAMLConfig> {
  const r = await apiFetch(`/orgs/${orgId}/saml`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await _errorMessage(r, `/orgs/${orgId}/saml`))
  return r.json()
}

export async function deleteOrgSAMLConfig(orgId: number): Promise<void> {
  const r = await apiFetch(`/orgs/${orgId}/saml`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`/orgs/${orgId}/saml ${r.status}`)
}

// ── SP metadata (for handing to the IdP administrator) ──────────────────
//
// Deliberately just a same-origin authenticated download of the existing
// GET /auth/saml/{org_slug}/metadata document (proxied, see
// routes_org_saml_proxy.py) -- no client-side XML construction, no IdP
// metadata import/discovery, no arbitrary URL fetch. Same
// fetch->blob->temporary-<a>-click pattern compliance.ts's own
// downloadHipaaReportPdf/Csv already established, reused verbatim rather
// than inventing a second one.
export async function downloadSpMetadata(orgSlug: string): Promise<void> {
  const path = `/auth/saml/${encodeURIComponent(orgSlug)}/metadata`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${orgSlug}-saml-sp-metadata.xml`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function spMetadataUrl(orgSlug: string): string {
  return `/auth/saml/${encodeURIComponent(orgSlug)}/metadata`
}

// Same helper as sso.ts's/security.ts's own -- prefers the backend's own
// detail message over a bare "<path> <status>" fallback.
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
