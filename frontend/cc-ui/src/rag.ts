// PR A4 (Admin Console Capability Parity -- RAG/PubMed): data layer
// mirroring tes.ts/billing.ts's shape exactly. Every call hits
// control-center's own backend at a relative path (routes_rag_proxy.py
// proxies the /rag/* surface to omnibioai-rag).
//
// Auth model: omnibioai-rag's HIPAA-V2-001 R4/R6 model. The backend proxy
// (routes_rag_proxy.py) forwards the *caller's own* IAM token to RAG, and
// RAG -- not control-center -- decides access: GET /v1/studies needs
// dataset.read (and returns only what the caller's organization may
// see), GET /v1/cache/stats needs manage_all_orgs. There is no shared
// service credential anywhere in this path. control-center's own
// platform.manage_infra gate still runs first, and hasAdminAccess() only
// controls whether the nav entry renders. A caller can therefore pass
// control-center's gate and still be refused by RAG (403), or -- rarely --
// have RAG reject the forwarded token (401).
//
// Field shapes mirror omnibioai-rag's own literal return dicts (list_
// studies(), redis_cache_stats() -> RAGCache.stats(), health()) -- read
// directly from ragbio/api/server.py and ragbio/cache/redis_cache.py,
// not guessed.
import { authHeaders, reportUnauthorized } from './auth'

// Set by routes_rag_proxy.py on every response it relays from RAG, never on
// a response control-center generates itself.
const UPSTREAM_SERVICE_HEADER = 'X-Upstream-Service'
const UPSTREAM_SERVICE_NAME = 'rag'

/** A non-2xx response from the RAG proxy. Callers decide what to show from
 * `status` (structured), never from `message` (backend wording). */
export class RagRequestError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'RagRequestError'
    this.status = status
  }
}

// A 401 from control-center's own require_permission means the admin's own
// session is invalid: same forced logout as every other domain file. A 401
// (or 403) that RAG returned after control-center accepted the session says
// nothing about the admin's session -- clearing a valid token and dropping
// the console back to the login screen for it was the bug this replaced --
// so it only ends the session when control-center itself produced it. The
// two are told apart by the proxy's origin marker, not by status or wording.
// The marker is written by the proxy alone (never copied from a request or
// from RAG's headers -- see test_routes_rag_proxy.py's spoofing tests), and if
// an intermediary ever stripped it the 401 would be read as control-center's
// own: the session would end, the fail-safe direction, never be wrongly kept.
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const r = await fetch(path, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (r.status === 401 && r.headers.get(UPSTREAM_SERVICE_HEADER) !== UPSTREAM_SERVICE_NAME) {
    reportUnauthorized()
  }
  return r
}

// ── Shapes ──────────────────────────────────────────────────────────────

export interface StudySummary {
  name: string
  abstract_count: number
}

export interface StudiesResult {
  studies: StudySummary[]
}

export interface CacheStats {
  enabled: boolean
  connected: boolean
  cached_queries?: number
  ttl_seconds?: number
  hits?: number
  misses?: number
  hit_rate?: number
  error?: string
}

export interface RagHealth {
  status: string
  version: string
  faiss_version: string | null
  cache: {
    enabled?: boolean
    connected?: boolean
    cached_queries?: number
    hit_rate?: number
  }
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchStudies(): Promise<StudiesResult> {
  const path = '/rag/studies'
  const r = await apiFetch(path)
  if (!r.ok) throw new RagRequestError(await _errorMessage(r, path), r.status)
  return r.json()
}

export async function fetchCacheStats(): Promise<CacheStats> {
  const path = '/rag/cache-stats'
  const r = await apiFetch(path)
  if (!r.ok) throw new RagRequestError(await _errorMessage(r, path), r.status)
  return r.json()
}

export async function fetchRagHealth(): Promise<RagHealth> {
  const path = '/rag/health'
  const r = await apiFetch(path)
  if (!r.ok) throw new RagRequestError(await _errorMessage(r, path), r.status)
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
