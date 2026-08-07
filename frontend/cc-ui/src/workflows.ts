// PR A3 (Admin Console Capability Parity -- Workflows): data layer
// mirroring tes.ts's shape exactly. Every call hits control-center's
// own backend at a relative path (routes_workflow_bundles_proxy.py
// proxies the /workflow-bundles/* surface to
// omnibioai-workflow-bundles); no function here makes an authorization
// decision -- GET /v1/workflows[/{name}], GET /v1/categories, and
// GET /v1/workflows/{id}/inputs are gated by workflow.read upstream,
// GET /v1/runs[/{id}] by workflow.execute, both independently enforced
// by workflow-bundles itself (require_permission, api/iam.py).
//
// IMPORTANT: fetchRuns() has no organization parameter and this file
// performs no client-side filtering by organization_id -- GET /v1/runs
// is not organization-scoped upstream today (its own source comment:
// organization_id on each run is "logging/audit context only -- not an
// access-control boundary," isolation is a tracked upstream follow-up).
// A response can legitimately span multiple organizations; this file
// relays it exactly as received. WorkflowsPage.tsx's Runs tab surfaces
// this to the viewer explicitly rather than silently narrowing it,
// which would misrepresent a boundary that doesn't actually exist
// server-side.
//
// Field shapes mirror workflow-bundles' own Pydantic models
// (WorkflowRow, CategoryStat) and its GET /v1/runs / GET /v1/runs/{id}
// handlers' literal return dicts (no response_model declared for either
// -- these fields are read directly from that code, not guessed).
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

export interface WorkflowRow {
  id: number
  category: string
  engine: string
  name: string
  display_name: string
  version: string
  entrypoint: string
  description?: string | null
  container_image?: string | null
  object_id: string
  enabled: boolean
  created_by?: string | null
  created_at?: string | null
}

export interface CategoryStat {
  category: string
  count: number
  enabled_count: number
}

export interface WorkflowInputs {
  inputs: Record<string, unknown>
  engine: string
  container_image: string
  entrypoint: string
  config_file: string
  inputs_schema: unknown
  manifest: { name: string; display_name: string; version: string; category: string }
}

export type RunStatus = 'running' | 'success' | 'failed'

// Every field here is optional beyond run_id/status because GET
// /v1/runs has no response_model upstream -- these are the keys the
// in-memory RUNS store is actually populated with (run_workflow()'s own
// dict literal), not a guaranteed contract.
export interface WorkflowRun {
  run_id: string
  status: RunStatus | string
  workflow_id?: number
  workflow_name?: string
  display_name?: string
  engine?: string
  requested_by?: string
  organization_id?: number | null
  started_at?: string
  finished_at?: string
  returncode?: number | null
  logs?: string[]
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchWorkflows(): Promise<WorkflowRow[]> {
  const path = '/workflow-bundles/workflows'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchCategories(): Promise<CategoryStat[]> {
  const path = '/workflow-bundles/categories'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchWorkflowInputs(workflowId: number): Promise<WorkflowInputs> {
  const path = `/workflow-bundles/workflows/${workflowId}/inputs`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// No organization parameter -- see module comment above. This is a
// platform-wide read (like AuditLogsPage.tsx's fetchAuditEvents()), not
// an org-scoped one (unlike tes.ts's fetchRuns(), which self-scopes
// upstream).
export async function fetchRuns(): Promise<WorkflowRun[]> {
  const path = '/workflow-bundles/runs'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchRunDetail(runId: string): Promise<WorkflowRun> {
  const path = `/workflow-bundles/runs/${runId}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

// Prefers the backend's own detail message over a bare "<path> <status>"
// -- same convention billing.ts's/tes.ts's own _errorMessage established.
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
