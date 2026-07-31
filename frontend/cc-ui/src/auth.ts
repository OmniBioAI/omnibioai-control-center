// Minimal admin-login flow for cc-ui's own gated endpoints (/summary,
// /config, /docker/*, /services -- see main.py's require_admin gate).
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
}

export function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function login(email: string, password: string): Promise<void> {
  const r = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    throw new Error(body.error || body.detail || `Login failed (${r.status})`)
  }
  if (!body.access_token) {
    throw new Error('Login response missing access_token')
  }
  localStorage.setItem(TOKEN_KEY, body.access_token)
}

// Fired whenever a gated request comes back 401 (missing/expired/invalid
// token) so App.tsx can drop back to the login screen without every
// call site needing to know about auth.
export const UNAUTHORIZED_EVENT = 'omnibioai:unauthorized'

export function reportUnauthorized(): void {
  clearToken()
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
}
