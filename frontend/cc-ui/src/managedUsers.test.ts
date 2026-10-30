import { afterEach, expect, it, vi } from 'vitest'
import { fetchManagedUsers, managedUsersCsv, type ManagedUser } from './users'
afterEach(() => vi.unstubAllGlobals())
it('uses the aggregated API with distinct membership and user status filters', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [], total: 0 }) })
  vi.stubGlobal('fetch', fetch)
  await fetchManagedUsers({ search: '42', status: 'suspended', tenant: { status: 'active', plan: 'pro' }, sortBy: 'pct', sortOrder: 'desc' })
  const url = new URL(fetch.mock.calls[0][0], 'http://localhost')
  expect(url.pathname).toBe('/admin/tenants')
  expect(Object.fromEntries(url.searchParams)).toMatchObject({ q: '42', user_status: 'suspended', status: 'active', plan: 'pro', page_size: '50', sort: '-pct' })
})
it('exports identity and storage columns, escaping CSV quotes and formulas', () => {
  const csv = managedUsersCsv([{ id: 1, email: '=CMD()', username: 'a"b', global_roles: ['admin'], used_bytes: 123, allocated_bytes: 456 } as ManagedUser])
  expect(csv).toContain('last_login_at,authentication_method,created_at,effective_plan_id')
  expect(csv).toContain("\"'=CMD()\"")
  expect(csv).toContain('"a""b"')
  expect(csv).toContain('"123","456"')
})
