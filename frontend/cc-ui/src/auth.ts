// Admin-login flow for cc-ui's own gated endpoints (/summary, /config,
// /docker/*, /services -- see main.py's require_admin gate).
// Same localStorage key name as workbench's lib/web/session.js so a
// future shared-cookie SSO pass can line the two up.
const TOKEN_KEY = 'omnibioai_access_token'

// SSO Phase 2 PR13: the refresh token is deliberately NEVER stored here
// (or anywhere else in JS-reachable storage). PR10 made auth-service set
// it as a second, server-set, HttpOnly `omnibioai_session` cookie
// (Domain=.omnibioai.org) on every /auth/login and /auth/refresh
// response; PR13's own hardening (routes_auth_proxy.py::_proxy_to_auth,
// backend repo) makes that cookie actually reach the browser through
// this app's own login/refresh proxy calls too. A browser holding that
// cookie sends it automatically on every same-origin request -- no JS
// needs to read, store, or forward it, and per the security requirement
// this PR was given, none does. PR5 (this file's previous version) did
// store it in localStorage, matching the ecosystem's pre-cookie
// convention at the time; that duplication is exactly what this PR
// removes now that the cookie exists.
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
  cancelScheduledRefresh()
  cachedUser = null
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// ── Silent refresh ───────────────────────────────────────────────────────
//
// workbench's lib/web/session.js already has a working refresh() (POSTs
// /auth/refresh, rotates the stored tokens) but nothing in that app's own
// UI ever calls it proactively -- no timer, no interceptor (confirmed by
// grep across src/ui; only its logout() is actually wired to a button).
// This service does schedule it: the access token's own `exp` claim is
// decoded client-side (no signature verification needed for scheduling
// purposes -- the token is opaque to us either way until the server
// re-validates it) and a refresh is scheduled a little before it expires.
const REFRESH_BUFFER_MS = 60_000 // refresh 60s before actual expiry

let refreshTimer: ReturnType<typeof setTimeout> | null = null

function cancelScheduledRefresh(): void {
  if (refreshTimer) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function decodeExpiry(token: string): number | null {
  try {
    const payloadSegment = token.split('.')[1]
    if (!payloadSegment) return null
    const base64 = payloadSegment.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const payload = JSON.parse(atob(padded))
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

function scheduleRefresh(accessToken: string): void {
  cancelScheduledRefresh()
  const exp = decodeExpiry(accessToken)
  if (exp == null) return // no usable exp claim -- nothing to schedule against
  const msUntilExpiry = exp * 1000 - Date.now()
  const delay = Math.max(msUntilExpiry - REFRESH_BUFFER_MS, 0)
  refreshTimer = setTimeout(() => {
    void refreshAccessToken()
  }, delay)
}

function persistAccessToken(accessToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken)
  scheduleRefresh(accessToken)
}

// Attempts to rotate the access token. SSO Phase 2 PR13: no refresh_token
// in the request body at all -- the browser attaches the omnibioai_session
// cookie automatically (same-origin request), and the backend proxy
// (routes_auth_proxy.py) forwards it to auth-service, whose own
// /auth/refresh already has a body-or-cookie fallback (PR10). A non-ok
// server response means there's no usable session (missing/expired/
// revoked) -- forces logout (reportUnauthorized), matching workbench's
// refresh()'s own "!res.ok -> clearSession()" behavior. A network/parse
// failure fails open (no forced logout, mirrors validateSession's own
// "don't punish an offline blip") -- no retry is scheduled for that case;
// the next mount (ensureSession) or the token's natural expiry
// re-establishes scheduling or forces a real login.
async function refreshAccessToken(): Promise<void> {
  try {
    const r = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    if (!r.ok) {
      reportUnauthorized()
      return
    }
    const data = await r.json().catch(() => ({}))
    if (!data.access_token) {
      reportUnauthorized()
      return
    }
    persistAccessToken(data.access_token)
  } catch {
    // network/parse failure -- fail open, see comment above
  }
}

// Explicit, user-initiated sign-out. POSTs /auth/logout with the access
// token only -- no refresh_token in the body (never stored client-side,
// per this PR's security requirement); the backend proxy fills it in
// server-side from the omnibioai_session cookie the browser already
// attached to this request. Revokes the refresh token server-side and
// blacklists the access token's jti for its remaining lifetime
// (routes_auth.py's LogoutRequest/_blacklist_access_token), and the
// backend proxy also relays auth-service's clearing Set-Cookie back to
// this browser -- see routes_auth_proxy.py. Fails open on any network/
// server error -- never let a logout attempt get stuck; clearToken()
// below always runs regardless.
export async function logout(): Promise<void> {
  const accessToken = getToken()
  try {
    await fetch('/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ access_token: accessToken }),
    })
  } catch {
    // fail open -- clearToken() below still runs
  }
  clearToken()
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

// Phase 3 PR0.4's global permission -- checked here exactly as the
// backend checks it (a permission string, never a role name), never
// re-derived or guessed. This is a UX signal only: it decides which
// backend endpoint the Organizations page *tries* first
// (/platform/orgs vs /orgs), never whether a request is actually
// allowed -- omnibioai-auth's own require_permission(MANAGE_ALL_ORGS)
// re-checks this independently and is the only check that matters for
// security. See OrganizationsPage.tsx.
export function hasPlatformAdminAccess(): boolean {
  return hasPermission('manage_all_orgs')
}

// Phase 3 PR2. Broader than hasAdminAccess(): admits anyone with real
// organizational context (a member of at least one org, reflected by a
// non-null orgId -- Phase 1 PR3) in addition to the existing global
// "admin" role, so the Organizations page has an audience beyond
// ops staff. This is a deliberate, minimal widening of the single
// existing App-level gate below, not the full admin.omnibioai.org /
// control.omnibioai.org build-and-domain split the original Phase 3
// blueprint (~/phase3_design.md) envisioned for this purpose -- that
// split has not been implemented in this repository as of this PR
// (confirmed directly, not assumed) and remains a larger, separate
// piece of follow-up work; see this PR's implementation report for the
// full reasoning. Existing ops pages (Health/Docker/Config/LLM/Cloud/
// Ecosystem) still check hasAdminAccess() specifically, unchanged.
export function hasOrganizationsAccess(): boolean {
  return hasAdminAccess() || hasPlatformAdminAccess() || cachedUser?.orgId != null
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
    // SSO Phase 2 PR5: (re)schedule silent refresh here rather than only
    // after login -- validateSession also runs on every app mount
    // (ensureSession), so a token restored from localStorage after a
    // browser restart gets scheduling too, not just a freshly issued one.
    scheduleRefresh(token)
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
  // SSO Phase 2 PR13: the response still includes refresh_token (auth-
  // service's response contract is unchanged -- routes_auth.py's
  // LoginResponse), but it's deliberately not read/stored here. The
  // browser already received it as the omnibioai_session HttpOnly cookie
  // via this same response (PR10 sets it server-side; PR13's backend
  // proxy fix relays it through) -- storing it again in localStorage
  // would duplicate a secret this app has no need to ever see in JS.
  persistAccessToken(body.access_token)
  return validateSession(body.access_token)
}
