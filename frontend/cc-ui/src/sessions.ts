// PR-C (Control Center Sessions Integration). Data layer, mirroring
// audit.ts/serviceAccounts.ts's own shape exactly. Every call hits
// control-center's own backend at a relative path
// (routes_sessions_proxy.py proxies to omnibioai-auth's self-service
// /sessions endpoints -- Phase 4 PR-A); no function here makes an
// authorization decision -- that's entirely omnibioai-auth's job (every
// endpoint scopes to the caller's own `sub` claim server-side).
//
// Deliberately does not duplicate any session state client-side beyond
// what's needed to render the current response -- no local cache, no
// persisted copy across page loads. Source of truth is always the next
// fetch.
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

// Mirrors omnibioai-auth's SessionOut (app/schemas/session.py) exactly.
// No token/cookie/secret field exists here because none exists on the
// upstream response to begin with -- see that schema's own docstring.
export type SessionStatus = 'active' | 'expired' | 'revoked'

export interface PlatformSession {
  session_id: string
  organization_id: number | null
  auth_method: string | null
  mfa_verified: boolean
  status: SessionStatus
  created_at: string
  last_activity_at: string
  expires_at: string
  revoked_at: string | null
  revoked_reason: string | null
  client_ip: string | null
  user_agent: string | null
}

export async function fetchMySessions(): Promise<PlatformSession[]> {
  const r = await apiFetch('/sessions')
  if (!r.ok) throw new Error(`/sessions ${r.status}`)
  return r.json()
}

export async function fetchMySession(sessionId: string): Promise<PlatformSession> {
  const r = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}`)
  if (!r.ok) throw new Error(`/sessions/${sessionId} ${r.status}`)
  return r.json()
}

export async function revokeMySession(sessionId: string): Promise<PlatformSession> {
  const r = await apiFetch(`/sessions/${encodeURIComponent(sessionId)}/revoke`, { method: 'POST' })
  if (!r.ok) throw new Error(`/sessions/${sessionId}/revoke ${r.status}`)
  return r.json()
}

// "password" -> "Password", "oauth" -> "OAuth", "sso" -> "SSO" -- display
// only, same word-splitting/acronym-uppercasing convention audit.ts's
// formatEventType already established.
const AUTH_METHOD_LABEL_OVERRIDES: Record<string, string> = {
  oauth: 'OAuth',
  sso: 'SSO',
}

export function formatAuthMethod(authMethod: string | null): string {
  if (!authMethod) return '—'
  if (AUTH_METHOD_LABEL_OVERRIDES[authMethod]) return AUTH_METHOD_LABEL_OVERRIDES[authMethod]
  return authMethod[0].toUpperCase() + authMethod.slice(1)
}

// A short, readable device/browser summary from a raw User-Agent string
// -- display only, never round-tripped back to the API. Deliberately
// simple pattern matching (not a full UA-parsing dependency) covering
// the browsers/platforms this admin console's own audience actually
// uses; falls back to the raw string (truncated) rather than guessing
// wrong, and to an em dash if the API has nothing recorded at all.
export function formatUserAgent(userAgent: string | null): string {
  if (!userAgent) return '—'
  const ua = userAgent
  let browser = ''
  if (/Edg\//.test(ua)) browser = 'Edge'
  else if (/Chrome\//.test(ua)) browser = 'Chrome'
  else if (/Firefox\//.test(ua)) browser = 'Firefox'
  else if (/Safari\//.test(ua) && !/Chrome\//.test(ua)) browser = 'Safari'
  else if (/curl\//i.test(ua)) browser = 'curl'

  let platform = ''
  if (/Windows/.test(ua)) platform = 'Windows'
  else if (/Mac OS X/.test(ua)) platform = 'macOS'
  else if (/Linux/.test(ua)) platform = 'Linux'
  else if (/Android/.test(ua)) platform = 'Android'
  else if (/iPhone|iPad/.test(ua)) platform = 'iOS'

  if (browser && platform) return `${browser} on ${platform}`
  if (browser) return browser
  return ua.length > 60 ? `${ua.slice(0, 57)}…` : ua
}
