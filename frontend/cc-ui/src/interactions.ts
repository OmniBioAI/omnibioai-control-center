// PR-B5-B (Control Center Interaction Admin View). Data layer, mirroring
// audit.ts's own shape exactly. Every call hits control-center's own
// backend at a relative path (routes_platform_interactions_proxy.py
// proxies to omnibioai-auth's GET /platform/interactions[/{id}] --
// PR-B5-A); no function here makes an authorization decision -- that's
// entirely omnibioai-auth's job (require_permission(manage_all_orgs),
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

// Mirrors omnibioai-auth's InteractionOut (app/schemas/interaction_read.py)
// exactly. No display-name enrichment exists on the upstream response
// (organization_id/user_id are returned as raw IDs, not resolved to a
// name/email -- unlike AuditEventOut's organization_name/actor_email) --
// see this PR's own report for why that's not added here. metadata is
// untyped JSON on purpose -- every service/interaction_type's payload
// shape differs, same reasoning AuditEvent's own metadata field has.
export interface Interaction {
  id: number
  interaction_id: string
  organization_id: number
  user_id: number | null
  session_id: string | null
  trace_id: string | null
  service: string
  interaction_type: string
  action: string
  resource_type: string | null
  resource_id: string | null
  status: string | null
  decision: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface InteractionListResponse {
  items: Interaction[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface InteractionFilters {
  organizationId?: number
  userId?: number
  service?: string
  interactionType?: string
  status?: string
  /** ISO 8601 -- passed straight through to the backend's start_date/
   * end_date query params, which parse it the same way. */
  startDate?: string
  endDate?: string
  page?: number
  pageSize?: number
}

export async function fetchInteractions(filters: InteractionFilters = {}): Promise<InteractionListResponse> {
  const qs = new URLSearchParams()
  qs.set('page', String(filters.page ?? 1))
  qs.set('page_size', String(filters.pageSize ?? 20))
  if (filters.organizationId != null) qs.set('organization_id', String(filters.organizationId))
  if (filters.userId != null) qs.set('user_id', String(filters.userId))
  if (filters.service) qs.set('service', filters.service)
  if (filters.interactionType) qs.set('interaction_type', filters.interactionType)
  if (filters.status) qs.set('status', filters.status)
  if (filters.startDate) qs.set('start_date', filters.startDate)
  if (filters.endDate) qs.set('end_date', filters.endDate)

  const r = await apiFetch(`/platform/interactions?${qs.toString()}`)
  if (!r.ok) throw new Error(`/platform/interactions ${r.status}`)
  return r.json()
}

export async function fetchInteraction(interactionId: string): Promise<Interaction> {
  const r = await apiFetch(`/platform/interactions/${encodeURIComponent(interactionId)}`)
  if (!r.ok) throw new Error(`/platform/interactions/${interactionId} ${r.status}`)
  return r.json()
}

// ── Defense-in-depth secret masking for the detail view ─────────────────
//
// The backend never writes a secret into an Interaction's metadata in
// the first place (interaction_service.py's own _redact_metadata,
// reused by app/workers/interaction_consumer.py for stream-sourced
// events -- verified directly, see PR-B5-B's own report). This is a
// second, independent layer on top of that guarantee, not a substitute
// for it -- identical in shape and intent to audit.ts's own
// maskSensitiveFields (same pattern, not re-derived): any key whose name
// merely *looks* sensitive is masked before ever reaching the DOM, so a
// future call site's mistake fails safe here too.
const SENSITIVE_KEY_PATTERN = /secret|token|password|api_?key|client_secret|hash/i

export function maskSensitiveFields(obj: Record<string, unknown> | null): Record<string, unknown> | null {
  if (!obj) return obj
  const masked: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(obj)) {
    masked[key] = SENSITIVE_KEY_PATTERN.test(key) ? '••••••••' : value
  }
  return masked
}
