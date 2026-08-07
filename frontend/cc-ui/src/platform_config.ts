// PR E1 (Admin Settings integration): data layer mirroring tes.ts's/
// rag.ts's shape exactly. Every call hits control-center's own backend
// at a relative path (routes_platform_config_proxy.py proxies
// GET /auth/config to omnibioai-auth); no function here makes an
// authorization decision -- GET /auth/config requires only a valid
// token upstream (no permission check, confirmed by reading
// omnibioai-auth's own app/api/routes_config.py directly), the same
// "backend is the real gate" posture every other domain file in this
// app already documents.
//
// Read-only in this PR -- no update function. omnibioai-auth's own
// PUT /auth/config (gated by manage_config) is not proxied yet; see
// routes_platform_config_proxy.py's own module comment for the
// deliberate scope decision. Credential fields (llm_api_key,
// cloud_credentials) do not exist on this response shape at all --
// GlobalConfigOut never echoes them back regardless of caller role,
// only has_llm_api_key/has_cloud_credentials booleans -- so there is
// nothing for this file to redact either.
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

// Field shapes mirror omnibioai-auth's own app/schemas/config.py
// GlobalConfigOut exactly.
export interface PlatformConfig {
  llm_provider: string | null
  has_llm_api_key: boolean
  cloud_provider: string | null
  has_cloud_credentials: boolean
  work_directory: string | null
  data_directory: string | null
  updated_at: string | null
  updated_by_email: string | null
}

// ── Calls ───────────────────────────────────────────────────────────────

export async function fetchPlatformConfig(): Promise<PlatformConfig> {
  const path = '/auth/config'
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
