import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import TenantManagementPage from './TenantManagementPage'

afterEach(() => vi.unstubAllEnvs())

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
