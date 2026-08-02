import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as auth from './auth'

// Minimal fake JWT: only the payload segment matters (decodeExpiry in
// auth.ts only reads segment [1]) -- header/signature are dummy values.
function makeToken(claims: Record<string, unknown>): string {
  return `dummy-header.${btoa(JSON.stringify(claims))}.dummy-signature`
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

interface MockResponse {
  ok: boolean
  json: () => Promise<unknown>
}

function jsonResponse(body: unknown, ok = true): MockResponse {
  return { ok, json: async () => body }
}

function mockFetchByUrl(routes: Record<string, MockResponse>) {
  return vi.fn(async (url: string) => {
    const response = routes[url]
    if (!response) throw new Error(`unexpected fetch to ${url}`)
    return response as unknown as Response
  })
}

const validUser = {
  valid: true,
  user_id: '1',
  email: 'admin@omnibioai.org',
  roles: ['admin'],
  permissions: ['manage_config'],
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// ── SSO Phase 2 PR13 ────────────────────────────────────────────────────────
//
// The refresh token is no longer stored in localStorage at all (it lives
// only in the server-set, HttpOnly omnibioai_session cookie -- PR10, made
// reachable through this app's own login/refresh proxy by PR13's backend
// fix). These tests assert the *absence* of `omnibioai_refresh_token` in
// localStorage throughout, and that /auth/refresh and /auth/logout calls
// carry no refresh_token in their body -- the browser's automatic
// same-origin cookie attachment is what a real browser does instead,
// which this vitest/jsdom environment doesn't simulate; asserting the
// client never tries to source or send the token itself is the correct,
// available proxy for "relies on the cookie instead."

describe('login', () => {
  it('stores only the access token, never the refresh token', async () => {
    const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
    }))

    await auth.login('admin@omnibioai.org', 'password')

    expect(localStorage.getItem('omnibioai_access_token')).toBe(accessToken)
    expect(localStorage.getItem('omnibioai_refresh_token')).toBeNull()
  })

  it('throws on a failed login without storing anything', async () => {
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ error: 'Invalid email or password' }, false),
    }))

    await expect(auth.login('admin@omnibioai.org', 'wrong')).rejects.toThrow(
      'Invalid email or password'
    )
    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })

  it('resolves the session user on success (existing UX preserved)', async () => {
    const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
    }))

    const user = await auth.login('admin@omnibioai.org', 'password')

    expect(user?.email).toBe('admin@omnibioai.org')
    expect(user?.roles).toEqual(['admin'])
  })
})

describe('silent refresh', () => {
  it('calls /auth/refresh with an empty body when the access token nears expiry', async () => {
    // Short-lived token so the scheduled refresh (fires 60s before exp)
    // is due almost immediately.
    const initialToken = makeToken({ sub: '1', exp: nowSeconds() + 65 })
    const rotatedToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })

    const fetchMock = mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: initialToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
      '/auth/refresh': jsonResponse({ access_token: rotatedToken, refresh_token: 'refresh-def' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await auth.login('admin@omnibioai.org', 'password')
    expect(localStorage.getItem('omnibioai_access_token')).toBe(initialToken)

    await vi.advanceTimersByTimeAsync(10_000)

    // No refresh_token anywhere in the request -- the browser's cookie
    // (invisible to this client, per the security requirement) is what
    // auth-service actually uses.
    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/refresh',
      expect.objectContaining({ body: JSON.stringify({}) })
    )
  })

  it('successful refresh updates the stored access token, still never the refresh token', async () => {
    const initialToken = makeToken({ sub: '1', exp: nowSeconds() + 65 })
    const rotatedToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })

    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: initialToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
      '/auth/refresh': jsonResponse({ access_token: rotatedToken, refresh_token: 'refresh-def' }),
    }))

    await auth.login('admin@omnibioai.org', 'password')
    await vi.advanceTimersByTimeAsync(10_000)

    expect(localStorage.getItem('omnibioai_access_token')).toBe(rotatedToken)
    expect(localStorage.getItem('omnibioai_refresh_token')).toBeNull()
  })

  it('failed refresh (no usable session) forces logout / returns to login state', async () => {
    const initialToken = makeToken({ sub: '1', exp: nowSeconds() + 65 })

    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: initialToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
      '/auth/refresh': jsonResponse({ error: 'invalid refresh token' }, false),
    }))

    let unauthorizedFired = false
    window.addEventListener(auth.UNAUTHORIZED_EVENT, () => {
      unauthorizedFired = true
    })

    await auth.login('admin@omnibioai.org', 'password')
    await vi.advanceTimersByTimeAsync(10_000)

    // App.tsx listens for this event to drop back to the login screen --
    // see App.tsx's UNAUTHORIZED_EVENT handler.
    expect(unauthorizedFired).toBe(true)
    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })

  it('a network failure during refresh fails open (no forced logout)', async () => {
    const initialToken = makeToken({ sub: '1', exp: nowSeconds() + 65 })

    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/auth/refresh') throw new Error('network down')
      if (url === '/auth/login') return jsonResponse({ access_token: initialToken, refresh_token: 'refresh-abc' }) as unknown as Response
      if (url === '/auth/validate') return jsonResponse(validUser) as unknown as Response
      throw new Error(`unexpected fetch to ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    await auth.login('admin@omnibioai.org', 'password')
    await vi.advanceTimersByTimeAsync(10_000)

    // Still present -- a transient network error must not clear the session.
    expect(localStorage.getItem('omnibioai_access_token')).toBe(initialToken)
  })
})

describe('logout', () => {
  it('calls POST /auth/logout with the access token, no refresh_token in the body', async () => {
    localStorage.setItem('omnibioai_access_token', 'access-xyz')

    const fetchMock = vi.fn(async () => jsonResponse({ message: 'Logged out' }) as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    await auth.logout()

    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/logout',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ access_token: 'access-xyz' }),
      })
    )
  })

  it('always calls the backend, even with no local access token', async () => {
    // No local refresh token to gate the call on anymore -- the backend
    // proxy resolves everything it needs from the cookie.
    const fetchMock = vi.fn(async () => jsonResponse({ message: 'Logged out' }) as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)

    await auth.logout()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('clears local access-token state after logout', async () => {
    localStorage.setItem('omnibioai_access_token', 'access-xyz')
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ message: 'Logged out' }) as unknown as Response))

    await auth.logout()

    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })

  it('fails open: still clears local session if the server call throws', async () => {
    localStorage.setItem('omnibioai_access_token', 'access-xyz')
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('network down')
    }))

    await auth.logout()

    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })
})

describe('clearToken', () => {
  it('clears cached session state (getSessionUser)', async () => {
    const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
    }))
    await auth.login('admin@omnibioai.org', 'password')
    expect(auth.getSessionUser()).not.toBeNull()

    auth.clearToken()

    expect(auth.getSessionUser()).toBeNull()
    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })

  it('cancels any pending scheduled refresh', async () => {
    const initialToken = makeToken({ sub: '1', exp: nowSeconds() + 65 })
    const fetchMock = mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: initialToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
    })
    vi.stubGlobal('fetch', fetchMock)

    await auth.login('admin@omnibioai.org', 'password')
    auth.clearToken()
    fetchMock.mockClear()

    await vi.advanceTimersByTimeAsync(10_000)

    // No refresh attempt should fire after the session was cleared.
    expect(fetchMock).not.toHaveBeenCalledWith('/auth/refresh', expect.anything())
  })
})

describe('no client-side cookie handling (security requirement)', () => {
  it('auth.ts exposes no getRefreshToken or cookie-reading export', () => {
    expect((auth as Record<string, unknown>).getRefreshToken).toBeUndefined()
  })

  it('never reads document.cookie', async () => {
    const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse(validUser),
    }))
    const cookieGetter = vi.spyOn(document, 'cookie', 'get')

    await auth.login('admin@omnibioai.org', 'password')
    await auth.logout()

    expect(cookieGetter).not.toHaveBeenCalled()
  })
})
