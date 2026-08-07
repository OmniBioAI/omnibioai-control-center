// PR A4 (Admin Console Capability Parity -- RAG/PubMed): data layer
// mirroring tes.ts/billing.ts's shape exactly. Every call hits
// control-center's own backend at a relative path (routes_rag_proxy.py
// proxies the /rag/* surface to omnibioai-rag).
//
// IMPORTANT, unlike every other domain file in this app: the functions
// here do NOT carry per-user RAG authorization. fetchStudies() and
// fetchCacheStats() are answered upstream using a control-center-held
// RAGBIO_API_KEY service credential, not the calling admin's own token
// -- omnibioai-rag's own `_verify` dependency on GET /v1/studies and
// GET /v1/cache/stats requires the bearer token to literally equal that
// shared secret (see routes_rag_proxy.py's module comment for the full
// citation). Admin Console visibility for the page built on this file
// is controlled entirely by control-center's own nav permission
// (hasAdminAccess), not a per-admin RAG-side check. This file does not
// introduce per-user RAG authorization -- RAG's real per-user model
// (dataset.read, independently JWT-verified) exists on /v1/query and
// /v1/kg/* only, deliberately not called from here; that's scoped to a
// future dedicated PR.
//
// Field shapes mirror omnibioai-rag's own literal return dicts (list_
// studies(), redis_cache_stats() -> RAGCache.stats(), health()) -- read
// directly from ragbio/api/server.py and ragbio/cache/redis_cache.py,
// not guessed.
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
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchCacheStats(): Promise<CacheStats> {
  const path = '/rag/cache-stats'
  const r = await apiFetch(path)
  if (!r.ok) throw new Error(await _errorMessage(r, path))
  return r.json()
}

export async function fetchRagHealth(): Promise<RagHealth> {
  const path = '/rag/health'
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
