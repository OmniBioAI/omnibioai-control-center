import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPlatformOrganization } from './organizations'

vi.mock('./auth', () => ({
  authHeaders: () => ({ Authorization: 'Bearer test-admin-token' }),
  reportUnauthorized: vi.fn(),
}))

describe('createPlatformOrganization', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts the tenant name and slug to the authenticated platform endpoint', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 12, name: 'Acme', slug: 'acme', plan: 'beta', status: 'active',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)

    await expect(createPlatformOrganization('Acme', 'acme')).resolves.toMatchObject({ id: 12, slug: 'acme' })
    expect(fetch).toHaveBeenCalledWith('/platform/orgs', expect.objectContaining({
      method: 'POST',
      headers: { Authorization: 'Bearer test-admin-token', 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Acme', slug: 'acme' }),
    }))
  })

  it('surfaces server duplicate and permission errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Organization slug already exists' }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    )))
    await expect(createPlatformOrganization('Acme', 'acme')).rejects.toThrow('Organization slug already exists')
  })
})
