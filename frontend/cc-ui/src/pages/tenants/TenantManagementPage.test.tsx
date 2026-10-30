import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as tenants from '../../tenants'
import TenantManagementPage from './TenantManagementPage'

afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

describe('TenantManagementPage mock mode', () => {
  it('renders the summary and tenant rows without calling upstream services', async () => {
    vi.stubEnv('VITE_TENANTS_MOCKS', 'true')
    const fetchSpy = vi.spyOn(globalThis, 'fetch')

    render(<TenantManagementPage tenantId={null} onSelect={() => undefined} onBack={() => undefined} />)

    expect(await screen.findByRole('heading', { name: 'Tenant management' })).toBeInTheDocument()
    expect(await screen.findByText('maya@example.org')).toBeInTheDocument()
    expect(screen.getByText('Total tenants')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })

  it('renders a tenant detail from the typed mocks', async () => {
    vi.stubEnv('VITE_TENANTS_MOCKS', 'true')

    render(<TenantManagementPage tenantId="1042" onSelect={() => undefined} onBack={() => undefined} />)

    expect(await screen.findByRole('heading', { name: 'maya' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Plan & validity' })).toBeInTheDocument()
    expect(screen.getByText(/not counted toward personal storage usage/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compute' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'API' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Grant promo plan' }))
    expect(screen.getByRole('dialog', { name: 'Grant promo plan' })).toBeInTheDocument()
    expect(screen.getByText(/Plus until .* with 100 GB allocated storage/i)).toBeInTheDocument()
    expect(screen.getByText(/storage override remains in control/i)).toBeInTheDocument()
  })

  it('renders an active promo badge and revoke action', async () => {
    vi.stubEnv('VITE_TENANTS_MOCKS', 'true')

    render(<TenantManagementPage tenantId="1048" onSelect={() => undefined} onBack={() => undefined} />)

    expect(await screen.findByRole('heading', { name: 'priya' })).toBeInTheDocument()
    expect(screen.getByText(/Promo until/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Revoke promo' })).toBeInTheDocument()
  })
})


describe('Tenant management presentation', () => {
  async function promoFixture() {
    vi.stubEnv('VITE_TENANTS_MOCKS', 'true')
    return { ...await tenants.fetchTenant('1048'), promo_expires_at: '2026-12-01T23:30:00-05:00', valid_until: '2026-10-01T00:00:00Z', days_remaining: -10, auto_renew: true }
  }

  it('uses promo validity, UTC dates, default membership and resolved history actors', async () => {
    const tenant = await promoFixture()
    tenant.plan_history[0].actor = 'user:42'
    tenant.plan_history[0].actor_display = 'admin@example.org'
    vi.spyOn(tenants, 'fetchTenant').mockResolvedValue(tenant)
    render(<TenantManagementPage tenantId="1048" onSelect={() => {}} onBack={() => {}} />)
    await screen.findByRole('heading', { name: 'priya' })
    const expected = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(tenant.promo_expires_at)) + ' UTC'
    expect(screen.getByText('Valid until').nextElementSibling).toHaveTextContent(expected)
    expect(screen.getByText('Renewal').nextElementSibling).toHaveTextContent('Promo — reverts to Free')
    expect(screen.getByText('Free (default)')).toBeInTheDocument()
    expect(screen.getByText('admin@example.org')).toBeInTheDocument()
    expect(screen.queryByText('user:42')).not.toBeInTheDocument()
  })

  it('uses promo expiry in the list and navigates once from row, keyboard or View', async () => {
    const tenant = await promoFixture()
    vi.spyOn(tenants, 'fetchTenants').mockResolvedValue({ items: [tenant], total: 1 })
    const onSelect = vi.fn()
    render(<TenantManagementPage tenantId={null} onSelect={onSelect} onBack={() => {}} />)
    const row = (await screen.findByText('priya@example.org')).closest('tr')!
    expect(within(row).getByText('Free (default)')).toBeInTheDocument()
    expect(row.cells[5]).toHaveTextContent('UTC')
    expect(row.cells[5]).toHaveTextContent('Promo — reverts to Free')
    expect(row.cells[5]).not.toHaveTextContent('Expired')
    const user = userEvent.setup()
    await user.click(row)
    expect(onSelect).toHaveBeenCalledTimes(1)
    await user.click(within(row).getByRole('button', { name: 'View priya' }))
    expect(onSelect).toHaveBeenCalledTimes(2)
    row.focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledTimes(3)
    await user.keyboard(' ')
    expect(onSelect).toHaveBeenCalledTimes(4)
    expect(onSelect).toHaveBeenLastCalledWith('1048')
  })
})
