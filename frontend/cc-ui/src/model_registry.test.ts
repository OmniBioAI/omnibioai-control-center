import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchModels, fetchModelRegistryHealth } from './model_registry'
import { classifyAuthError } from './format'
import * as auth from './auth'

vi.mock('./auth', async () => {
  const actual = await vi.importActual<typeof import('./auth')>('./auth')
  return { ...actual, authHeaders: vi.fn(() => ({})), reportUnauthorized: vi.fn() }
})

// Regression coverage for the bug fixed alongside this file's
// _errorMessage(): AIModelsPage.test.tsx's own "shows permission-denied"
// test mocks fetchModels() directly, so it only ever exercised
// classifyAuthError() against the generic "<path> <status>" fallback
// shape -- never the real detail-bearing 403 body model-registry's
// list_models actually returns once model.use is enforced. That gap is
// exactly why the bug (raw "Missing required permission: model.use"
// under a bare "Error" heading, instead of the page's own DeniedState)
// shipped unnoticed. These tests go through the real fetch -> Response ->
// _errorMessage() path instead.
describe('fetchModels error messages', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.mocked(auth.reportUnauthorized).mockClear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('classifies as denied a real backend 403 detail message, not just the generic fallback shape', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Missing required permission: model.use' }), { status: 403 }),
    )
    try {
      await fetchModels()
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe('Missing required permission: model.use 403')
      expect(classifyAuthError((e as Error).message)).toBe('denied')
    }
  })

  it('classifies as session a real backend 401 detail message, and reports the unauthorized session', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid, expired, or revoked token' }), { status: 401 }),
    )
    try {
      await fetchModels()
      expect.unreachable()
    } catch (e) {
      expect(classifyAuthError((e as Error).message)).toBe('session')
    }
    expect(auth.reportUnauthorized).toHaveBeenCalled()
  })

  it('leaves a non-auth status detail message unsuffixed, and does not classify it as denied/session', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'registry filesystem unavailable' }), { status: 500 }),
    )
    try {
      await fetchModelRegistryHealth()
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe('registry filesystem unavailable')
      const kind = classifyAuthError((e as Error).message)
      expect(kind).not.toBe('denied')
      expect(kind).not.toBe('session')
      expect(kind).toBe('error')
    }
  })

  it('still falls back to "<path> <status>" when the body has no detail/error string', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('', { status: 403 }))
    await expect(fetchModels()).rejects.toThrow('/model-registry/models 403')
  })

  // Deliberately narrow: this fix's scope is the 401/403 distinction the
  // bug report was about, not "always suffix the status for any
  // detail-bearing 4xx". A 404 detail message stays exactly as it was
  // (classifyAuthError's 'not-found' bucket was never the broken one
  // here, and widening past 401/403 was explicitly out of scope).
  it('leaves a 404 detail message unsuffixed (out of this fix\'s scope)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'model not found' }), { status: 404 }),
    )
    try {
      await fetchModels()
      expect.unreachable()
    } catch (e) {
      expect((e as Error).message).toBe('model not found')
    }
  })
})
