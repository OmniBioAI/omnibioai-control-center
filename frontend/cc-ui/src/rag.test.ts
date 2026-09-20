import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as auth from './auth'
import { fetchStudies, fetchCacheStats, fetchRagHealth, RagRequestError } from './rag'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({ Authorization: 'Bearer admin-own-token' })), reportUnauthorized: vi.fn() }
})

// The origin marker routes_rag_proxy.py sets on every response it relays
// from RAG (and never on a response control-center generates itself).
const FROM_RAG = { 'X-Upstream-Service': 'rag' }

function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(body), { status, headers })))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function rejection(promise: Promise<unknown>): Promise<RagRequestError> {
  try {
    await promise
  } catch (e) {
    expect(e).toBeInstanceOf(RagRequestError)
    return e as RagRequestError
  }
  throw new Error('expected the call to reject')
}

describe('rag.ts data layer', () => {
  beforeEach(() => {
    vi.mocked(auth.reportUnauthorized).mockClear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("sends the viewing admin's own bearer token, nothing else", async () => {
    const fetchMock = stubFetch(200, { studies: [] })
    await fetchStudies()
    expect(fetchMock).toHaveBeenCalledWith('/rag/studies', expect.objectContaining({
      headers: { Authorization: 'Bearer admin-own-token' },
    }))
  })

  describe('a 401 that control-center itself produced (invalid admin session)', () => {
    it('still forces the logout, for every RAG call', async () => {
      for (const call of [fetchStudies, fetchCacheStats, fetchRagHealth]) {
        vi.mocked(auth.reportUnauthorized).mockClear()
        stubFetch(401, { detail: 'Missing or malformed Authorization header' })
        const error = await rejection(call())
        expect(error.status).toBe(401)
        expect(auth.reportUnauthorized).toHaveBeenCalledTimes(1)
      }
    })
  })

  describe('a 401/403 relayed from RAG after control-center accepted the session', () => {
    it('does NOT clear the admin session, whatever the error wording', async () => {
      for (const detail of ['Invalid, expired, or revoked token', 'anything else at all', undefined]) {
        for (const call of [fetchStudies, fetchCacheStats]) {
          stubFetch(401, detail === undefined ? {} : { detail }, FROM_RAG)
          const error = await rejection(call())
          expect(error.status).toBe(401)
        }
      }
      expect(auth.reportUnauthorized).not.toHaveBeenCalled()
    })

    it('does NOT clear the admin session on a 403, and exposes the status', async () => {
      for (const call of [fetchStudies, fetchCacheStats]) {
        stubFetch(403, { detail: 'Insufficient permissions' }, FROM_RAG)
        const error = await rejection(call())
        expect(error.status).toBe(403)
      }
      expect(auth.reportUnauthorized).not.toHaveBeenCalled()
    })
  })

  it('a control-center 403 (own permission gate) never triggers logout either', async () => {
    stubFetch(403, { detail: 'Insufficient permissions' })
    const error = await rejection(fetchStudies())
    expect(error.status).toBe(403)
    expect(auth.reportUnauthorized).not.toHaveBeenCalled()
  })

  it('carries the HTTP status on non-auth failures too', async () => {
    stubFetch(503, { error: 'rag-service unreachable: ConnectError' })
    const error = await rejection(fetchStudies())
    expect(error.status).toBe(503)
    expect(error.message).toBe('rag-service unreachable: ConnectError')
  })

  it('returns parsed data on success', async () => {
    stubFetch(200, { studies: [{ name: 'covid19', abstract_count: 5 }] }, FROM_RAG)
    await expect(fetchStudies()).resolves.toEqual({ studies: [{ name: 'covid19', abstract_count: 5 }] })
    expect(auth.reportUnauthorized).not.toHaveBeenCalled()
  })
})
