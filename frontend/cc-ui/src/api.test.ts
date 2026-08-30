import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./auth', () => ({
  authHeaders: () => ({ Authorization: 'Bearer <test-token>' }),
  reportUnauthorized: vi.fn(),
}))

import { fetchRegressionHealth, fetchSecurityPosture } from './api'

describe('fetchRegressionHealth', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('uses the API subpath separate from the SPA route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ schema_version: '1.0' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await fetchRegressionHealth()

    expect(fetchMock).toHaveBeenCalledWith(
      '/regression-health/data',
      expect.objectContaining({
        headers: { Authorization: 'Bearer <test-token>' },
      }),
    )
  })
})

describe('fetchSecurityPosture', () => {
  it('uses the browser data path separate from the SPA route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) })
    vi.stubGlobal('fetch', fetchMock)
    await fetchSecurityPosture()
    expect(fetchMock).toHaveBeenCalledWith('/security-posture/data', expect.objectContaining({
      headers: { Authorization: 'Bearer <test-token>' },
    }))
  })
})
