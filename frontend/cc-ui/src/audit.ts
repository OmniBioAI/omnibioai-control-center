// PR11.4b: Audit Logs data layer, mirroring serviceAccounts.ts/sso.ts's
// own shape exactly. Every call hits control-center's own backend at a
// relative path (routes_audit_proxy.py proxies GET /platform/audit-events
// to omnibioai-auth); no function here makes an authorization decision --
// that's entirely omnibioai-auth's job (require_permission(manage_all_orgs),
// reused unchanged, no new permission).
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

// Mirrors omnibioai-auth's AuditEventOut (app/schemas/audit.py) exactly.
// actor_email/target_email/organization_name are best-effort display
// resolution done server-side (audit_service.resolve_display_fields) --
// null if the referenced user/org no longer exists, never fabricated
// here. before_state/after_state/metadata are untyped JSON on purpose --
// every event_type's payload shape differs, same reasoning
// AuditEvent's own model docstring gives.
export interface AuditEvent {
  id: number
  event_type: string
  actor_user_id: number | null
  actor_email: string | null
  target_user_id: number | null
  target_email: string | null
  organization_id: number | null
  organization_name: string | null
  resource_type: string | null
  resource_id: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  created_at: string | null
}

export interface AuditEventListResponse {
  items: AuditEvent[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface AuditEventFilters {
  organizationId?: number
  actorUserId?: number
  eventType?: string
  /** ISO 8601 -- passed straight through to the backend's start_date/
   * end_date query params, which parse it the same way. */
  startDate?: string
  endDate?: string
  page?: number
  pageSize?: number
}

export async function fetchAuditEvents(filters: AuditEventFilters = {}): Promise<AuditEventListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(filters.page ?? 1))
  qs.set('page_size', String(filters.pageSize ?? 20))
  if (filters.organizationId != null) qs.set('organization_id', String(filters.organizationId))
  if (filters.actorUserId != null) qs.set('actor_user_id', String(filters.actorUserId))
  if (filters.eventType) qs.set('event_type', filters.eventType)
  if (filters.startDate) qs.set('start_date', filters.startDate)
  if (filters.endDate) qs.set('end_date', filters.endDate)

  const r = await apiFetch(`/platform/audit-events?${qs.toString()}`)
  if (!r.ok) throw new Error(`/platform/audit-events ${r.status}`)
  return r.json()
}

// Every event_type this PR's backend services actually emit -- kept here
// as a plain string list (not re-derived from the response, which has no
// registry-style listing endpoint of its own) purely so the filter
// dropdown has real, known-valid options instead of a free-text field
// that could typo into "0 results" silently. Matches
// omnibioai-auth's AuditEventType exactly; a future event type added
// there without a matching entry here still round-trips fine (the
// filter would just need updating to offer it as a dropdown choice).
export const KNOWN_EVENT_TYPES = [
  'login_success', 'login_failure',
  'role_created', 'role_assigned', 'role_removed',
  'permission_granted', 'permission_revoked',
  'organization_membership_changed',
  'user_enabled', 'user_disabled',
  'api_key_created', 'api_key_revoked',
  'oauth_client_created', 'oauth_client_revoked',
  'sso_configuration_created', 'sso_configuration_updated', 'sso_enforcement_changed',
] as const

/** "api_key_created" -> "API Key Created" -- display only. */
export function formatEventType(eventType: string): string {
  return eventType
    .split('_')
    .map(word => (word.toUpperCase() === 'SSO' || word.toUpperCase() === 'API' ? word.toUpperCase() : word[0].toUpperCase() + word.slice(1)))
    .join(' ')
}

// ── Defense-in-depth secret masking for the detail view ─────────────────
//
// The backend never writes a secret into before_state/after_state/
// metadata in the first place (verified directly -- see
// docs/pr11-identity-audit-discovery.md and every log_event call site's
// own "never client_secret/api_key/tokens" comment, plus
// tests/test_pr11_identity_audit.py's _assert_no_secret_leakage
// coverage in omnibioai-auth). This is a second, independent layer on
// top of that guarantee, not a substitute for it -- any key whose name
// merely *looks* sensitive is masked before ever reaching the DOM,
// so a future call site's mistake fails safe here too.
const SENSITIVE_KEY_PATTERN = /secret|token|password|api_?key|client_secret|hash/i

export function maskSensitiveFields(obj: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!obj) return obj
  const masked: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(obj)) {
    masked[key] = SENSITIVE_KEY_PATTERN.test(key) ? '••••••••' : value
  }
  return masked
}
