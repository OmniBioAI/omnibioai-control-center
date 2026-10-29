import { describe, expect, it } from 'vitest'
import { DECIMAL_GB, filterMockTenants, formatGB, storageStatus, tenantsCsv } from './tenants'
import type { TenantDetail } from './tenants'

const row = (changes: Partial<TenantDetail> = {}): TenantDetail => ({
  tenant_id: '1', username: 'maya', email: 'maya@example.org', plan_id: 'plus', membership_status: 'active', effective_plan_id: 'plus', valid_from: null, valid_until: null, auto_renew: true, days_remaining: 5, allocated_bytes: 20 * DECIMAL_GB, allocation_source: 'plan', used_bytes: 16 * DECIMAL_GB, reserved_bytes: 0, pct: 80, storage_status: 'near', last_plan_change: null, last_activity_at: null, plan_history: [], override: null, top_allocations: [], workflow_output_bytes: 0, usage_trend_30d: [], ...changes,
})

describe('tenant contract helpers', () => {
  it('uses decimal GB and exact status thresholds', () => {
    expect(formatGB(DECIMAL_GB)).toBe('1 GB')
    expect(storageStatus(799_999_999, DECIMAL_GB)).toBe('ok')
    expect(storageStatus(800_000_000, DECIMAL_GB)).toBe('near')
    expect(storageStatus(DECIMAL_GB + 1, DECIMAL_GB)).toBe('over_allocation')
  })
  it('filters search, validity, status and sorts', () => {
    const rows = [row(), row({ tenant_id: '2', username: 'zed', email: 'zed@example.org', days_remaining: -1, membership_status: 'canceled', effective_plan_id: 'free', storage_status: 'ok' })]
    expect(filterMockTenants(rows, { q: 'MAYA', validity: 'expiring_7d', plan: 'plus', status: 'active', storage_status: 'near' })).toHaveLength(1)
    expect(filterMockTenants(rows, { validity: 'expired' })[0].tenant_id).toBe('2')
    expect(filterMockTenants(rows, { sort: '-username' })[0].username).toBe('zed')
  })
  it('exports the current rows as escaped CSV', () => {
    expect(tenantsCsv([row({ username: 'Maya "M"' })])).toContain('"Maya ""M"""')
  })
})
