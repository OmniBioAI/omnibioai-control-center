// PR A2 (Admin Console Capability Parity -- AI Models): data layer
// mirroring tes.ts/billing.ts's shape exactly. Every call hits
// control-center's own backend at a relative path (routes_model_registry_
// proxy.py proxies the /model-registry/* surface to
// omnibioai-model-registry); no function here makes an authorization
// decision -- none of these three routes are gated at all on the
// model-registry side today (confirmed by reading its own
// service/app/main.py -- no Depends(require_auth) on list_models,
// health, or api_auth_status), unlike tes.ts's /runs calls.
//
// GET /v1/models returns one row per registered *version*, not per
// distinct model (model-registry globs every version's model_meta.json)
// -- both fetchModels() call sites in this app (Registered Models tab,
// grouped client-side by task+model_name, and Model Versions tab, shown
// flat) read this same single endpoint, there is no separate
// "distinct models" endpoint to call instead.
//
// Field shapes mirror model_meta.json's actual, verified contents:
// task/model_name/version/created_at are always present (set by
// register_model() at write time); stage is present only once a
// version has gone through POST /v1/stage at least once (absent
// otherwise, never fabricated as "none" here -- that normalization, if
// wanted, is a display-layer decision, not this file's). Every other
// key in a row comes from whatever the caller's own `metadata` dict
// held at registration time -- arbitrary and not enumerated here, so
// callers must not assume any field beyond the four above.
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

export interface ModelVersionRow {
  task: string
  model_name: string
  version: string
  created_at?: string
  stage?: string
  // Arbitrary additional metadata supplied at registration time --
  // never assumed to hold any particular key.
  [key: string]: unknown
}

export interface ModelRegistryHealth {
  ok: boolean
  service: string
  version: string
}

export interface ModelRegistryAuthStatus {
  auth_enabled: boolean
  mode: 'jwt' | 'open'
  iam_url: string | null
}

export interface ModelListFilters {
  task?: string
  model_name?: string
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchModels(filters: ModelListFilters = {}): Promise<ModelVersionRow[]> {
  const params = new URLSearchParams()
  if (filters.task) params.set('task', filters.task)
  if (filters.model_name) params.set('model_name', filters.model_name)
  const qs = params.toString()
  const path = `/model-registry/models${qs ? `?${qs}` : ''}`
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchModelRegistryHealth(): Promise<ModelRegistryHealth> {
  const path = '/model-registry/health'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchModelRegistryAuthStatus(): Promise<ModelRegistryAuthStatus> {
  const path = '/model-registry/auth-status'
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
