import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./auth', () => ({ authHeaders: () => ({ Authorization: 'Bearer <test-token>' }), reportUnauthorized: vi.fn() }))

import { fetchIntegrationHealth } from './api'

describe('fetchIntegrationHealth', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('uses the distinct browser API path and never accepts provider destinations', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ schema_version: '1.0' }) })
    vi.stubGlobal('fetch', fetchMock)
    await fetchIntegrationHealth()
    expect(fetchMock).toHaveBeenCalledWith('/integration-health/data', expect.objectContaining({ headers: { Authorization: 'Bearer <test-token>' } }))
    expect(fetchMock.mock.calls[0][0]).not.toMatch(/[?&](url|host|endpoint)=/)
  })
})
