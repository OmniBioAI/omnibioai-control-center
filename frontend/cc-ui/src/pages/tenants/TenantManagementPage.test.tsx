import { render, screen } from '@testing-library/react'
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
    expect(screen.getByText('6')).toBeInTheDocument()
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
  })
})
