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

// ── PR12: authorization-adjacent helpers ────────────────────────────────────
//
// hasAdminAccess/hasPermission/hasPlatformAdminAccess/hasOrganizationsAccess
// were previously only exercised indirectly through page-level tests
// (UsersPage, OrganizationDetailPage, RolesPage, ...) -- these are the
// helpers every one of those pages' platform-vs-org gating decisions
// actually goes through, so they get their own direct coverage here. All
// are UX-only signals (see their own doc comments in auth.ts) -- the
// backend independently re-checks every one of these via its own
// require_permission/require_admin/require_org_permission, which is what
// actually decides whether a request succeeds.

async function loginAs(user: {
  roles: string[]
  permissions: string[]
  org_id?: string | null
}) {
  const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
  vi.stubGlobal('fetch', mockFetchByUrl({
    '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'r' }),
    '/auth/validate': jsonResponse({
      valid: true,
      user_id: '1',
      email: 'user@omnibioai.org',
      ...user,
    }),
  }))
  await auth.login('user@omnibioai.org', 'password')
}

describe('hasAdminAccess', () => {
  it('is true for the admin role', async () => {
    await loginAs({ roles: ['admin'], permissions: [] })
    expect(auth.hasAdminAccess()).toBe(true)
  })

  it('is false without the admin role, even with other permissions', async () => {
    await loginAs({ roles: ['org_admin'], permissions: ['manage_org'] })
    expect(auth.hasAdminAccess()).toBe(false)
  })
})

describe('hasPermission', () => {
  it('is true when the permission is present', async () => {
    await loginAs({ roles: [], permissions: ['manage_roles'] })
    expect(auth.hasPermission('manage_roles')).toBe(true)
  })

  it('is false when the permission is absent', async () => {
    await loginAs({ roles: [], permissions: ['manage_roles'] })
    expect(auth.hasPermission('manage_all_orgs')).toBe(false)
  })
})

describe('hasPlatformAdminAccess (Platform Owner tier)', () => {
  it('is true only with the manage_all_orgs permission', async () => {
    await loginAs({ roles: ['platform_admin'], permissions: ['manage_all_orgs'] })
    expect(auth.hasPlatformAdminAccess()).toBe(true)
  })

  it('is false for an org_admin without manage_all_orgs (Org Admin tier is org-scoped, not global)', async () => {
    await loginAs({ roles: ['org_admin'], permissions: ['manage_org'], org_id: 'org-1' })
    expect(auth.hasPlatformAdminAccess()).toBe(false)
  })

  it('is false for the legacy admin role alone (permission-based, not role-name-based)', async () => {
    await loginAs({ roles: ['admin'], permissions: [] })
    expect(auth.hasPlatformAdminAccess()).toBe(false)
  })
})

describe('hasOrganizationsAccess', () => {
  it('admits a platform admin', async () => {
    await loginAs({ roles: [], permissions: ['manage_all_orgs'] })
    expect(auth.hasOrganizationsAccess()).toBe(true)
  })

  it('admits the legacy admin role', async () => {
    await loginAs({ roles: ['admin'], permissions: [] })
    expect(auth.hasOrganizationsAccess()).toBe(true)
  })

  it('admits any org member via a non-null org_id', async () => {
    await loginAs({ roles: ['org_member'], permissions: [], org_id: 'org-1' })
    expect(auth.hasOrganizationsAccess()).toBe(true)
  })

  it('denies a user with no admin role, no platform permission, and no org', async () => {
    await loginAs({ roles: [], permissions: [], org_id: null })
    expect(auth.hasOrganizationsAccess()).toBe(false)
  })
})

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

// ── Mode B Phase 2: Workspace Switcher ──────────────────────────────────────

describe('switchTeam', () => {
  it('POSTs /auth/switch-team with team_id and no X-Team-Id/X-Workspace-Id header', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    const fetchMock = mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: newToken, refresh_token: 'refresh-new' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: '7', team_role: 'admin' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await auth.switchTeam(7)

    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/switch-team',
      expect.objectContaining({ body: JSON.stringify({ team_id: 7 }) }),
    )
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['X-Team-Id']).toBeUndefined()
    expect(headers['X-Workspace-Id']).toBeUndefined()
  })

  it('sends team_id: null (not omitted) for "switch to personal workspace"', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: newToken, refresh_token: 'r' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: null, team_role: null }),
    }))

    await auth.switchTeam(null)

    const fetchMock = vi.mocked(fetch)
    expect(fetchMock).toHaveBeenCalledWith(
      '/auth/switch-team',
      expect.objectContaining({ body: JSON.stringify({ team_id: null }) }),
    )
  })

  it('on success, persists the new access token and rehydrates teamId/teamRole', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: newToken, refresh_token: 'r' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: '7', team_role: 'admin' }),
    }))

    const user = await auth.switchTeam(7)

    expect(localStorage.getItem('omnibioai_access_token')).toBe(newToken)
    expect(user.teamId).toBe('7')
    expect(user.teamRole).toBe('admin')
    expect(auth.getSessionUser()?.teamId).toBe('7')
  })

  it('Team A -> Team B: teamId updates to the newly selected team', async () => {
    const tokenB = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: tokenB, refresh_token: 'r2' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: '2', team_role: 'member' }),
    }))

    const user = await auth.switchTeam(2)
    expect(user.teamId).toBe('2')
  })

  it('Team -> Personal: teamId becomes null', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: newToken, refresh_token: 'r' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: null, team_role: null }),
    }))

    const user = await auth.switchTeam(null)
    expect(user.teamId).toBeNull()
    expect(user.teamRole).toBeNull()
  })

  it('Personal -> Team: teamId becomes the selected team', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/switch-team': jsonResponse({ access_token: newToken, refresh_token: 'r' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: '5', team_role: 'viewer' }),
    }))

    const user = await auth.switchTeam(5)
    expect(user.teamId).toBe('5')
  })

  it('401: reports unauthorized and throws a session-expired message, without leaking which team/org', async () => {
    localStorage.setItem('omnibioai_access_token', 'stale-token')
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 401, ok: false, json: async () => ({ detail: 'Invalid refresh token' }),
    } as unknown as Response)))

    let thrown: Error | null = null
    try {
      await auth.switchTeam(7)
    } catch (e) {
      thrown = e as Error
    }
    expect(thrown?.message).toMatch(/session has expired/i)
    // reportUnauthorized() already clears the token -- same forced-logout
    // path every other 401 in this app goes through.
    expect(localStorage.getItem('omnibioai_access_token')).toBeNull()
  })

  it('403: throws a generic denial message that does not name the org/team boundary', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 403, ok: false, json: async () => ({ detail: 'Not a member of this team' }),
    } as unknown as Response)))

    let thrown: Error | null = null
    try {
      await auth.switchTeam(7)
    } catch (e) {
      thrown = e as Error
    }
    expect(thrown?.message).not.toMatch(/not a member/i)
    expect(thrown?.message).not.toMatch(/organization/i)
    expect(thrown?.message).toBeTruthy()
  })

  it('404: throws the same generic denial message as 403 -- does not reveal existence', async () => {
    let thrown403: Error | null = null
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 403, ok: false, json: async () => ({}) } as unknown as Response)))
    try { await auth.switchTeam(7) } catch (e) { thrown403 = e as Error }

    let thrown404: Error | null = null
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 404, ok: false, json: async () => ({ detail: 'Team not found' }) } as unknown as Response)))
    try { await auth.switchTeam(7) } catch (e) { thrown404 = e as Error }

    expect(thrown404?.message).toBe(thrown403?.message)
  })

  it('network failure: throws a generic connectivity message, does not clear the session', async () => {
    localStorage.setItem('omnibioai_access_token', 'still-valid-token')
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    let thrown: Error | null = null
    try {
      await auth.switchTeam(7)
    } catch (e) {
      thrown = e as Error
    }
    expect(thrown).not.toBeNull()
    // Unlike a 401, a network blip is not a session problem -- the
    // previously valid token must survive it (same fail-open posture
    // silent refresh's own network-failure path already has).
    expect(localStorage.getItem('omnibioai_access_token')).toBe('still-valid-token')
  })

  it('successful switch followed by a validate failure throws rather than silently succeeding', async () => {
    const newToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    let call = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      call += 1
      if (url === '/auth/switch-team') {
        return jsonResponse({ access_token: newToken, refresh_token: 'r' }) as unknown as Response
      }
      // /auth/validate network failure right after a successful switch.
      throw new TypeError('Failed to fetch')
    }))

    let thrown: Error | null = null
    try {
      await auth.switchTeam(7)
    } catch (e) {
      thrown = e as Error
    }
    expect(thrown).not.toBeNull()
    expect(call).toBeGreaterThanOrEqual(2)
    // The new token is still persisted (switch itself did succeed) even
    // though this call couldn't confirm it -- not rolled back, matching
    // validateSession's own existing fail-open behavior for a network
    // blip.
    expect(localStorage.getItem('omnibioai_access_token')).toBe(newToken)
  })
})

describe('logout clears team state', () => {
  it('getSessionUser().teamId is gone after logout (cachedUser fully cleared, not merged)', async () => {
    const accessToken = makeToken({ sub: '1', exp: nowSeconds() + 900 })
    vi.stubGlobal('fetch', mockFetchByUrl({
      '/auth/login': jsonResponse({ access_token: accessToken, refresh_token: 'refresh-abc' }),
      '/auth/validate': jsonResponse({ ...validUser, team_id: '7', team_role: 'admin' }),
    }))
    await auth.login('admin@omnibioai.org', 'password')
    expect(auth.getSessionUser()?.teamId).toBe('7')

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ message: 'Logged out' }) as unknown as Response))
    await auth.logout()

    expect(auth.getSessionUser()).toBeNull()
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
