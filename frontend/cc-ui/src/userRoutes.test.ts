import { afterEach, expect, it } from 'vitest'
import { redirectLegacyTenants } from './userRoutes'
afterEach(() => window.history.replaceState(null, '', '/'))
it('replaces the legacy list URL', () => {
  window.history.replaceState(null, '', '/tenants')
  const count = window.history.length
  redirectLegacyTenants()
  expect(window.location.pathname).toBe('/users')
  expect(window.history.length).toBe(count)
})
it('opens Plan & storage from a legacy detail bookmark', () => {
  window.history.replaceState(null, '', '/tenants/42?tab=profile')
  redirectLegacyTenants()
  expect(window.location.pathname + window.location.search).toBe('/users/42?tab=plan-storage')
})
it('preserves ordinary user links', () => {
  window.history.replaceState(null, '', '/users/42?tab=security')
  redirectLegacyTenants()
  expect(window.location.search).toBe('?tab=security')
})
