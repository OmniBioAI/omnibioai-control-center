import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SSOSettingsPage from './SSOSettingsPage'
import * as auth from '../../auth'
import * as sso from '../../sso'
import type { OrgSSOConfig } from '../../sso'
import * as organizations from '../../organizations'
import type { MyOrg } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPermission: vi.fn(), hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../sso', async () => {
  const actual = await vi.importActual<typeof import('../../sso')>('../../sso')
  return {
    ...actual,
    fetchOrgSSOConfig: vi.fn(),
    createOrgSSOConfig: vi.fn(),
    updateOrgSSOConfig: vi.fn(),
    enableSSOOverride: vi.fn(),
    clearSSOOverride: vi.fn(),
  }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchMyOrg: vi.fn(), fetchPlatformOrgDetail: vi.fn() }
})

const configuredConfig: OrgSSOConfig = {
  issuer: 'https://idp.acme.test',
  client_id: 'abc123',
  provider_type: 'oidc',
  allowed_domains: ['acme.test'],
  status: 'active',
  created_at: '2026-07-01T00:00:00',
  updated_at: '2026-07-02T00:00:00',
  enforced: false,
  sso_override_active: false,
}

const myOrg: MyOrg = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

describe('SSOSettingsPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPermission).mockReturnValue(false)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(sso.fetchOrgSSOConfig).mockReset()
    vi.mocked(sso.createOrgSSOConfig).mockReset()
    vi.mocked(sso.updateOrgSSOConfig).mockReset()
    vi.mocked(sso.enableSSOOverride).mockReset()
    vi.mocked(sso.clearSSOOverride).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
  })

  it('shows a loading state while the config fetch is in flight', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockReturnValue(new Promise(() => {}))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    // await flushes the (mocked, resolving) org-label fetch too, so its
    // state update lands inside this render pass rather than warning
    // outside act() -- the config fetch itself still never resolves.
    expect(await screen.findByText('Loading SSO configuration…')).toBeInTheDocument()
  })

  it('shows the no-configuration state and the create form when none exists yet', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 404'))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('No SSO configuration')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create SSO configuration' })).toBeInTheDocument()
    // Never shown before a config exists.
    expect(screen.queryByText('Current Configuration')).not.toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not the form', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 403'))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create SSO configuration' })).not.toBeInTheDocument()
    expect(screen.queryByText('Current Configuration')).not.toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a permission-denied one', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 401'))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Session expired')).toBeInTheDocument()
    expect(screen.queryByText('Permission denied')).not.toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValueOnce(new Error('/orgs/42/sso 503'))
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValueOnce(configuredConfig)
    const user = userEvent.setup()
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
  })

  it('displays the existing configuration without ever rendering a secret field', async () => {
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
    expect(screen.getByText('https://idp.acme.test')).toBeInTheDocument()
    expect(screen.getByText('abc123')).toBeInTheDocument()
    expect(screen.getByText('OIDC')).toBeInTheDocument()
    // No secret value is ever fetched or rendered -- OrgSSOConfig has no
    // client_secret field to begin with (see sso.ts).
    expect(screen.queryByText(/client_secret/i)).not.toBeInTheDocument()
    const secretInput = screen.getByLabelText(/Client secret/) as HTMLInputElement
    expect(secretInput.value).toBe('')
    expect(secretInput.type).toBe('password')
  })

  it('shows inline validation errors and does not submit for missing/invalid fields', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 404'))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SSO configuration')

    await user.type(screen.getByLabelText('Issuer URL'), 'not-a-url')
    await user.click(screen.getByRole('button', { name: 'Create SSO configuration' }))

    expect(await screen.findByText('Enter a valid http(s) URL.')).toBeInTheDocument()
    expect(screen.getByText('Client ID is required.')).toBeInTheDocument()
    expect(screen.getByText('Client secret is required.')).toBeInTheDocument()
    expect(sso.createOrgSSOConfig).not.toHaveBeenCalled()
  })

  it('creates a new SSO configuration on valid submit', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 404'))
    vi.mocked(sso.createOrgSSOConfig).mockResolvedValue(configuredConfig)
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SSO configuration')

    await user.type(screen.getByLabelText('Issuer URL'), 'https://idp.acme.test')
    await user.type(screen.getByLabelText('Client ID'), 'abc123')
    await user.type(screen.getByLabelText(/Client secret/), 's3cr3t')
    await user.click(screen.getByRole('button', { name: 'Create SSO configuration' }))

    await waitFor(() => expect(sso.createOrgSSOConfig).toHaveBeenCalledWith(42, {
      issuer: 'https://idp.acme.test', client_id: 'abc123', client_secret: 's3cr3t', allowed_domains: [],
    }))
    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
  })

  it('updates an existing configuration, omitting client_secret when left blank', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    vi.mocked(sso.updateOrgSSOConfig).mockResolvedValue({ ...configuredConfig, client_id: 'new-client' })
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    const clientIdInput = screen.getByLabelText('Client ID')
    await user.clear(clientIdInput)
    await user.type(clientIdInput, 'new-client')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(sso.updateOrgSSOConfig).toHaveBeenCalledWith(42, {
      issuer: 'https://idp.acme.test', client_id: 'new-client', allowed_domains: ['acme.test'],
    }))
  })

  it('surfaces the backend error message inline on a failed submit', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockRejectedValue(new Error('/orgs/42/sso 404'))
    vi.mocked(sso.createOrgSSOConfig).mockRejectedValue(new Error('could not reach discovery endpoint: timeout'))
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SSO configuration')

    await user.type(screen.getByLabelText('Issuer URL'), 'https://idp.acme.test')
    await user.type(screen.getByLabelText('Client ID'), 'abc123')
    await user.type(screen.getByLabelText(/Client secret/), 's3cr3t')
    await user.click(screen.getByRole('button', { name: 'Create SSO configuration' }))

    expect(await screen.findByText('could not reach discovery endpoint: timeout')).toBeInTheDocument()
  })

  it('requires confirmation before enabling SSO enforcement, and explains the backend guard', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    vi.mocked(sso.updateOrgSSOConfig).mockResolvedValue({ ...configuredConfig, enforced: true })
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Require SSO Login' }))
    expect(screen.getByText(/must already have at least one successful SSO login/)).toBeInTheDocument()
    expect(sso.updateOrgSSOConfig).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: require SSO login' }))
    await waitFor(() => expect(sso.updateOrgSSOConfig).toHaveBeenCalledWith(42, { enforced: true }))
  })

  it('surfaces the lockout-guard error verbatim when enabling enforcement is rejected', async () => {
    const user = userEvent.setup()
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    vi.mocked(sso.updateOrgSSOConfig).mockRejectedValue(
      new Error('cannot enforce SSO for this organization until at least one member has completed a successful SSO login'),
    )
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Require SSO Login' }))
    await user.click(screen.getByRole('button', { name: 'Confirm: require SSO login' }))

    expect(await screen.findByText(/until at least one member has completed/)).toBeInTheDocument()
  })

  it('hides the Break Glass card entirely without override_sso_enforcement', async () => {
    vi.mocked(auth.hasPermission).mockReturnValue(false)
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    expect(screen.queryByText('Break Glass Override')).not.toBeInTheDocument()
  })

  it('shows the Break Glass card with override_sso_enforcement, and requires a reason plus confirmation to enable', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPermission).mockImplementation(p => p === 'override_sso_enforcement')
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue(configuredConfig)
    vi.mocked(sso.enableSSOOverride).mockResolvedValue({ ...configuredConfig, sso_override_active: true })
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Break Glass Override')

    expect(screen.getByText('None')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Enable override' }))
    expect(screen.getByText(/only be used for account recovery/)).toBeInTheDocument()

    // No reason yet -- confirming should not call the backend.
    await user.click(screen.getByRole('button', { name: 'Confirm: enable override' }))
    expect(sso.enableSSOOverride).not.toHaveBeenCalled()
    expect(await screen.findByText(/reason is required/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Override reason'), 'admin locked out')
    await user.click(screen.getByRole('button', { name: 'Confirm: enable override' }))

    await waitFor(() => expect(sso.enableSSOOverride).toHaveBeenCalledWith(42, 'admin locked out'))
  })

  it('disables an active override after confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPermission).mockImplementation(p => p === 'override_sso_enforcement')
    vi.mocked(sso.fetchOrgSSOConfig).mockResolvedValue({ ...configuredConfig, sso_override_active: true })
    vi.mocked(sso.clearSSOOverride).mockResolvedValue({ ...configuredConfig, sso_override_active: false })
    render(<SSOSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Break Glass Override')

    await user.click(screen.getByRole('button', { name: 'Disable override' }))
    expect(sso.clearSSOOverride).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: disable override' }))
    await waitFor(() => expect(sso.clearSSOOverride).toHaveBeenCalledWith(42))
  })
})
