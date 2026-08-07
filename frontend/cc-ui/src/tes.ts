// PR A1 (Admin Console Capability Parity -- Tool Execution): data layer
// mirroring billing.ts's shape exactly. Every call hits control-center's
// own backend at a relative path (routes_tes_proxy.py proxies the
// /tes/* surface to omnibioai-tes); no function here makes an
// authorization decision -- GET /tes/runs and GET /tes/runs/{run_id} are
// entirely omnibioai-tes's own job (require_permission(WORKFLOW_EXECUTE),
// independent JWT verification, api/routes_runs.py); GET /tes/tools and
// GET /tes/tools/capabilities are unauthenticated upstream today.
//
// TES scopes GET /tes/runs to the caller's own organization_id
// server-side (api/routes_runs.py's list_runs) -- there is no org_id
// parameter to pass here, unlike billing.ts's org-scoped calls. A run
// belonging to a different org 404s (not 403s) on GET /tes/runs/{id},
// same enumeration-oracle avoidance convention used elsewhere in this
// ecosystem.
//
// Field shapes mirror omnibioai-tes's own Pydantic/dataclass models
// (ToolSpec, RunRecord) field-for-field.
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

export interface ToolSummary {
  tool_id: string
  name?: string
  description?: string
}

export interface ToolCapability {
  tool_id: string
  backends: string[]
}

export type RunState = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'

export interface RunRecord {
  run_id: string
  tool_id: string
  server_id: string
  state: RunState
  organization_id: number
  created_at?: string
  updated_at?: string
  remote_run_id?: string | null
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchTools(): Promise<ToolSummary[]> {
  const path = '/tes/tools'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchToolCapabilities(): Promise<ToolCapability[]> {
  const path = '/tes/tools/capabilities'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// No org_id parameter -- TES self-scopes to the caller's own
// organization_id from the forwarded JWT (see module comment above).
export async function fetchRuns(): Promise<RunRecord[]> {
  const path = '/tes/runs'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchRunDetail(runId: string): Promise<RunRecord> {
  const path = `/tes/runs/${runId}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// Prefers the backend's own detail message over a bare "<path> <status>"
// -- same convention billing.ts's own _errorMessage established.
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
