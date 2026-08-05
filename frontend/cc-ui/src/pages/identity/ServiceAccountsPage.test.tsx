import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ServiceAccountsPage from './ServiceAccountsPage'
import * as auth from '../../auth'
import * as serviceAccounts from '../../serviceAccounts'
import type { ApiKey, OAuthClient } from '../../serviceAccounts'
import * as organizations from '../../organizations'
import type { MyOrg } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../serviceAccounts', async () => {
  const actual = await vi.importActual<typeof import('../../serviceAccounts')>('../../serviceAccounts')
  return {
    ...actual,
    fetchApiKeys: vi.fn(),
    createApiKey: vi.fn(),
    revokeApiKey: vi.fn(),
    fetchOAuthClients: vi.fn(),
    createOAuthClient: vi.fn(),
    revokeOAuthClient: vi.fn(),
    fetchPermissionRegistry: vi.fn(),
  }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchMyOrg: vi.fn(), fetchPlatformOrgDetail: vi.fn() }
})

const myOrg: MyOrg = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

const apiKey: ApiKey = {
  id: 1, name: 'CI pipeline', key_prefix: 'omni_sk_ab12', scopes: ['dataset.read'],
  status: 'active', created_at: '2026-07-01T00:00:00', expires_at: null, last_used_at: null,
}

const oauthClient: OAuthClient = {
  id: 1, name: 'ETL worker', client_id: 'omni_client_ab12', scopes: ['dataset.read'],
  status: 'active', created_at: '2026-07-01T00:00:00', expires_at: null, last_used_at: '2026-07-05T00:00:00',
}

let clipboardWriteText: ReturnType<typeof vi.fn>

describe('ServiceAccountsPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(serviceAccounts.fetchApiKeys).mockReset()
    vi.mocked(serviceAccounts.createApiKey).mockReset()
    vi.mocked(serviceAccounts.revokeApiKey).mockReset()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockReset()
    vi.mocked(serviceAccounts.createOAuthClient).mockReset()
    vi.mocked(serviceAccounts.revokeOAuthClient).mockReset()
    vi.mocked(serviceAccounts.fetchPermissionRegistry).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockReset().mockResolvedValue(myOrg)
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
  })

  it('shows a loading state while the OAuth clients fetch is in flight', async () => {
    vi.mocked(serviceAccounts.fetchOAuthClients).mockReturnValue(new Promise(() => {}))
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('Loading service accounts…')).toBeInTheDocument()
  })

  it('shows the empty state when no OAuth clients exist yet', async () => {
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('No service accounts yet.')).toBeInTheDocument()
  })

  it('renders the OAuth client list with client id, scopes, and last used', async () => {
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([oauthClient])
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('ETL worker')).toBeInTheDocument()
    expect(screen.getByText('omni_client_ab12')).toBeInTheDocument()
    expect(screen.getByText('dataset.read')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('renders the API key list on the API Keys tab, with "Never" for an unused key', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([apiKey])
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')

    await user.click(screen.getByRole('button', { name: 'API Keys' }))

    expect(await screen.findByText('CI pipeline')).toBeInTheDocument()
    expect(screen.getByText('Never')).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not the create button', async () => {
    vi.mocked(serviceAccounts.fetchOAuthClients).mockRejectedValue(new Error('/orgs/42/oauth-clients 403'))
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.getByText("You don't have manage_oauth_clients for this organization.")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Create Service Account' })).not.toBeInTheDocument()
  })

  it('shows a permission-denied state on a 404 (non-member) with a distinct message', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchApiKeys).mockRejectedValue(new Error('/orgs/42/api-keys 404'))
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')
    await user.click(screen.getByRole('button', { name: 'API Keys' }))

    expect(await screen.findByText("This organization's API keys aren't accessible to you.")).toBeInTheDocument()
  })

  it('creates an OAuth client, shows the secret exactly once, and clears it on Done', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.createOAuthClient).mockResolvedValue({
      id: 2, name: 'New Worker', client_id: 'omni_client_xyz', scopes: [], client_secret: 's3cr3t-value',
    })
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')

    await user.click(screen.getByRole('button', { name: 'Create Service Account' }))
    const dialog = screen.getByRole('dialog', { name: 'Create Service Account' })
    await user.type(within(dialog).getByLabelText('Client name'), 'New Worker')
    await user.click(within(dialog).getByRole('button', { name: 'Create Service Account' }))

    await waitFor(() => expect(serviceAccounts.createOAuthClient).toHaveBeenCalledWith(42, 'New Worker', []))

    expect(await screen.findByText(/only be shown once/)).toBeInTheDocument()
    expect(screen.getByText('omni_client_xyz')).toBeInTheDocument()
    expect(screen.getByText('s3cr3t-value')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Done' }))
    // Cleared from the DOM entirely -- not just hidden -- once dismissed.
    expect(screen.queryByText('s3cr3t-value')).not.toBeInTheDocument()
  })

  it('copies the revealed secret to the clipboard', async () => {
    const user = userEvent.setup()
    // Defined after userEvent.setup() deliberately -- setup() installs
    // its own clipboard stub, which would otherwise shadow one defined
    // in beforeEach by the time the click below actually runs.
    clipboardWriteText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: clipboardWriteText },
      configurable: true,
    })
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.createApiKey).mockResolvedValue({
      id: 3, name: 'New Key', key_prefix: 'omni_sk_xyz1', scopes: [], key: 'omni_sk_xyz1fullsecretvalue',
    })
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')
    await user.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('No API keys yet.')

    await user.click(screen.getByRole('button', { name: 'Create API Key' }))
    const createDialog = screen.getByRole('dialog', { name: 'Create API Key' })
    await user.type(within(createDialog).getByLabelText('Name'), 'New Key')
    await user.click(within(createDialog).getByRole('button', { name: 'Create API Key' }))

    await screen.findByText('omni_sk_xyz1fullsecretvalue')
    await user.click(screen.getByRole('button', { name: /Copy API key/ }))

    expect(clipboardWriteText).toHaveBeenCalledWith('omni_sk_xyz1fullsecretvalue')
  })

  it('requires a name before creating an API key', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')
    await user.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('No API keys yet.')

    await user.click(screen.getByRole('button', { name: 'Create API Key' }))
    const dialog = screen.getByRole('dialog', { name: 'Create API Key' })
    await user.click(within(dialog).getByRole('button', { name: 'Create API Key' }))

    expect(await screen.findByText('Name is required.')).toBeInTheDocument()
    expect(serviceAccounts.createApiKey).not.toHaveBeenCalled()
  })

  it('surfaces the backend scope-rejection message inline on a failed create', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.createApiKey).mockRejectedValue(
      new Error("Cannot grant scopes you don't hold: ['manage_org']"),
    )
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')
    await user.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('No API keys yet.')

    await user.click(screen.getByRole('button', { name: 'Create API Key' }))
    const dialog = screen.getByRole('dialog', { name: 'Create API Key' })
    await user.type(within(dialog).getByLabelText('Name'), 'x')
    await user.click(within(dialog).getByRole('button', { name: 'Create API Key' }))

    expect(await screen.findByText(/Cannot grant scopes you don't hold/)).toBeInTheDocument()
  })

  it('revokes an API key after confirmation, not before', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([])
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([apiKey])
    vi.mocked(serviceAccounts.revokeApiKey).mockResolvedValue(undefined)
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No service accounts yet.')
    await user.click(screen.getByRole('button', { name: 'API Keys' }))
    await screen.findByText('CI pipeline')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(serviceAccounts.revokeApiKey).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: /Confirm revoke/ }))
    await waitFor(() => expect(serviceAccounts.revokeApiKey).toHaveBeenCalledWith(42, 1))
  })

  it('revokes an OAuth client by its numeric id, not its public client_id, after confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(serviceAccounts.fetchOAuthClients).mockResolvedValue([oauthClient])
    vi.mocked(serviceAccounts.revokeOAuthClient).mockResolvedValue(undefined)
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('ETL worker')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await user.click(screen.getByRole('button', { name: /Confirm revoke/ }))

    await waitFor(() => expect(serviceAccounts.revokeOAuthClient).toHaveBeenCalledWith(42, oauthClient.id))
  })

  it('opens directly on the API Keys tab when initialTab is set', async () => {
    vi.mocked(serviceAccounts.fetchApiKeys).mockResolvedValue([apiKey])
    render(<ServiceAccountsPage orgId={42} onBack={vi.fn()} initialTab="api-keys" />)

    expect(await screen.findByText('CI pipeline')).toBeInTheDocument()
    expect(serviceAccounts.fetchOAuthClients).not.toHaveBeenCalled()
  })
})
