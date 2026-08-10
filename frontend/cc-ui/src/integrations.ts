// PR-B6: data layer mirroring platform_config.ts's/rag.ts's shape
// exactly. Every call hits control-center's own backend at a relative
// path (routes_integrations.py answers GET /integrations directly --
// no upstream service involved, same as cloud.ts's implicit /cloud
// call in CloudPage.tsx). No function here makes an authorization
// decision -- GET /integrations requires no permission at all, by
// design (see routes_integrations.py's own module comment: booleans
// and static labels only, no internal topology, matching GET /cloud's
// same ungated posture).
//
// Field shapes mirror control_center/api/routes_integrations.py's own
// literal response dict exactly, not guessed. There is no credential
// field on this response shape at all -- nothing here to redact.
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

// ── Shapes ──────────────────────────────────────────────────────────────

export interface IntegrationStatus {
  label: string
  purpose: string
  configured: boolean
  /** sentry only -- absent on discord_notifications/discord_alerts. */
  report_aggregation_configured?: boolean
}

export interface IntegrationsResult {
  sentry: IntegrationStatus
  discord_notifications: IntegrationStatus
  discord_alerts: IntegrationStatus
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchIntegrations(): Promise<IntegrationsResult> {
  const path = '/integrations'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// Prefers the backend's own detail message over a bare "<path> <status>"
// -- same convention every other domain file in this app already
// established.
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
