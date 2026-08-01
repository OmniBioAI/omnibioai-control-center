// Admin-login flow for cc-ui's own gated endpoints (/summary, /config,
// /docker/*, /services -- see main.py's require_admin gate).
// Same localStorage key name as workbench's lib/web/session.js so a
// future shared-cookie SSO pass can line the two up; this flow itself
// stays local-only (no cookie mirroring) since cc-ui is served standalone
// at control.omnibioai.org, not just under webstudio's /_svc/control.
const TOKEN_KEY = 'omnibioai_access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  cachedUser = null
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── Session (omnibioai-auth Phase 1 PR3: org-aware JWT) ─────────────────────
//
// A v2 token (token_version=2) carries org_id/org_role/auth_method on top of
// the original sub/email/roles/permissions; a v1 token (issued before PR3,
// still valid for up to its 15-minute lifetime after any deploy) has none of
// those fields at all. /auth/validate degrades v1 tokens to schemaVersion=1
// with orgId=null/orgRoles=[] rather than erroring, so this client mirrors
// that: every field below is optional/defaulted, never assumed present.
export interface SessionUser {
  userId: string
  email: string
  roles: string[]
  permissions: string[]
  orgId: string | null
  orgRoles: string[]
  schemaVersion: number
}

// Permissions the auth-service seeds onto the "admin" role (see
// omnibioai-auth's db/init_admin.py). Kept here only for future
// page-level gating -- the actual admin boundary enforced both
// server-side (core/auth.py's require_admin) and by hasAdminAccess()
// below is still the coarser "admin" role, so the two can never disagree
// about whether a request will succeed.
export const ADMIN_PERMISSIONS = ['manage_config', 'manage_roles', 'manage_licenses'] as const

let cachedUser: SessionUser | null = null

export function getSessionUser(): SessionUser | null {
  return cachedUser
}

export function hasAdminAccess(): boolean {
  return !!cachedUser?.roles.includes('admin')
}

export function hasPermission(permission: string): boolean {
  return !!cachedUser?.permissions.includes(permission)
}

// Fired whenever a gated request comes back 401 (missing/expired/invalid
// token) so App.tsx can drop back to the login screen without every
// call site needing to know about auth.
export const UNAUTHORIZED_EVENT = 'omnibioai:unauthorized'

export function reportUnauthorized(): void {
  clearToken()
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
}

// Resolves the token already in localStorage into a SessionUser, or clears
// it if it's missing/expired/revoked. Called on every mount (not just after
// login) since a token survives a browser restart but cachedUser doesn't.
export async function ensureSession(): Promise<SessionUser | null> {
  const token = getToken()
  if (!token) return null
  if (cachedUser) return cachedUser
  return validateSession(token)
}

async function validateSession(token: string): Promise<SessionUser | null> {
  try {
    const r = await fetch('/auth/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok || !data.valid) {
      clearToken()
      return null
    }
    cachedUser = {
      userId: data.user_id,
      email: data.email,
      roles: data.roles ?? [],
      permissions: data.permissions ?? [],
      orgId: data.org_id ?? null,
      orgRoles: data.org_role ?? [],
      schemaVersion: data.schema_version ?? 1,
    }
    return cachedUser
  } catch {
    // Network/parse failure -- leave the token in place (don't punish an
    // offline blip with a forced logout) and report "no user resolved yet".
    return null
  }
}

export async function login(email: string, password: string): Promise<SessionUser | null> {
  const r = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    // authenticate_user() in omnibioai-auth returns the same generic 401
    // for a wrong password AND a disabled account -- deliberately, to
    // avoid leaking account status to an unauthenticated caller. There is
    // no server signal to build a distinct "account disabled" message
    // from at this step; surfacing one here would just be UI fiction.
    throw new Error(body.error || body.detail || 'Authentication failed')
  }
  if (!body.access_token) {
    throw new Error('Login response missing access_token')
  }
  localStorage.setItem(TOKEN_KEY, body.access_token)
  return validateSession(body.access_token)
}
