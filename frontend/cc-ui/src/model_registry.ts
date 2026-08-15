// PR A2 (Admin Console Capability Parity -- AI Models): data layer
// mirroring tes.ts/billing.ts's shape exactly. Every call hits
// control-center's own backend at a relative path (routes_model_registry_
// proxy.py proxies the /model-registry/* surface to
// omnibioai-model-registry); no function here makes an authorization
// decision. health and api_auth_status remain fully open upstream (no
// Depends(...) on either, confirmed by reading service/app/main.py
// directly) but list_models no longer is -- omnibioai-model-registry's
// later HIPAA hardening series (Phase 2A-2D) put it behind
// require_auth_with_context, which enforces the same model.use
// permission as every write route (see that repo's auth.py module
// docstring: "Almost every route checks the existing model.use
// permission"). A caller without model.use now gets a real 403 with a
// `detail` message here, same as tes.ts's /runs calls always could --
// _errorMessage() below has to preserve that classifyability, see its
// own comment.
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
//
// format.ts's classifyAuthError() (shared by every page's error handling,
// including AIModelsPage's) only recognizes a 401/403 by this message
// literally ending in " 401"/" 403" -- the shape the generic fallback
// below has always had, but not what a real backend `detail`/`error`
// message gives it. Since model-registry's list_models started
// enforcing model.use (see this file's module comment), a caller
// without it got a genuinely helpful 403 body here -- {"detail":
// "Missing required permission: model.use"} -- that this function
// returned completely unsuffixed. classifyAuthError() then silently
// fell through to its generic 'error' bucket instead of 'denied', so
// AIModelsPage rendered the raw string under a bare "Error" heading
// (ErrorState) instead of the DeniedState it already has built
// specifically for this case. Appending the status code for exactly
// these two auth-outcome codes restores that classification without
// changing this function's message for any other status (404/500/503/
// ... keep the bare detail text, unsuffixed) -- narrowly scoped to the
// 401/403 distinction this bug report was actually about, not a general
// "always suffix the status" change.
const CLASSIFIABLE_STATUSES = [401, 403]

async function _errorMessage(r: Response, path: string): Promise<string> {
  try {
    const data = await r.json()
    const detail = typeof data?.detail === 'string' ? data.detail
      : typeof data?.error === 'string' ? data.error
      : null
    if (detail !== null) {
      return CLASSIFIABLE_STATUSES.includes(r.status) ? `${detail} ${r.status}` : detail
    }
  } catch {
    // fall through to the generic message below
  }
  return `${path} ${r.status}`
}
