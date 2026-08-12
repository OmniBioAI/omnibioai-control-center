import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SAMLSettingsPage from './SAMLSettingsPage'
import * as auth from '../../auth'
import * as saml from '../../saml'
import type { OrgSAMLConfig } from '../../saml'
import * as organizations from '../../organizations'
import type { MyOrg } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../saml', async () => {
  const actual = await vi.importActual<typeof import('../../saml')>('../../saml')
  return {
    ...actual,
    fetchOrgSAMLConfig: vi.fn(),
    createOrgSAMLConfig: vi.fn(),
    updateOrgSAMLConfig: vi.fn(),
    deleteOrgSAMLConfig: vi.fn(),
    downloadSpMetadata: vi.fn(),
  }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchMyOrg: vi.fn(), fetchPlatformOrgDetail: vi.fn() }
})

const CERT = '-----BEGIN CERTIFICATE-----\nMIIB...fake...\n-----END CERTIFICATE-----'

const activeConfig: OrgSAMLConfig = {
  entity_id: 'https://idp.acme.test/entity',
  sso_url: 'https://idp.acme.test/sso',
  x509_certificate: CERT,
  attribute_mapping: { email: 'NameID' },
  enabled: false,
  status: 'active',
  created_at: '2026-08-01T00:00:00',
  updated_at: '2026-08-01T00:00:00',
}

const disabledConfig: OrgSAMLConfig = { ...activeConfig, status: 'disabled' }

const myOrg: MyOrg = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

describe('SAMLSettingsPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(saml.fetchOrgSAMLConfig).mockReset()
    vi.mocked(saml.createOrgSAMLConfig).mockReset()
    vi.mocked(saml.updateOrgSAMLConfig).mockReset()
    vi.mocked(saml.deleteOrgSAMLConfig).mockReset()
    vi.mocked(saml.downloadSpMetadata).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
  })

  // ── 1. Loading state ──────────────────────────────────────────────

  it('shows a loading state while the config fetch is in flight', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockReturnValue(new Promise(() => {}))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('Loading SAML configuration…')).toBeInTheDocument()
  })

  // ── 2. Empty state ────────────────────────────────────────────────

  it('shows the no-configuration state and the create form on a 404', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('No SAML configuration')).toBeInTheDocument()
    expect(screen.getByText('Create SAML configuration')).toBeInTheDocument()
    expect(screen.queryByText('Current Configuration')).not.toBeInTheDocument()
    // No metadata card without a config yet -- nothing to hand to an IdP.
    expect(screen.queryByText('Service Provider Metadata')).not.toBeInTheDocument()
  })

  // ── 3. Existing configuration loads correctly ────────────────────

  it('displays the existing configuration', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
    expect(screen.getByText('https://idp.acme.test/entity')).toBeInTheDocument()
    expect(screen.getByText('https://idp.acme.test/sso')).toBeInTheDocument()
    // Rendered twice: the Current Configuration card's Status field, and
    // the SAML Login Status card's own "currently Active" line.
    expect(screen.getAllByText('Active')).toHaveLength(2)
    expect(screen.getByText('1 configured')).toBeInTheDocument()
    // enabled shown informationally, never as a working toggle.
    expect(screen.getByText(/Enabled flag \(informational only, not enforced by login\): false/)).toBeInTheDocument()
  })

  // ── 8/9. 403 / 404 on load ────────────────────────────────────────

  it('shows a permission-denied state on a 403, not the config', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 403'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('Current Configuration')).not.toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a permission-denied one', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 401'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Session expired')).toBeInTheDocument()
    expect(screen.queryByText('Permission denied')).not.toBeInTheDocument()
  })

  // ── 11. Network/server failure ───────────────────────────────────

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValueOnce(new Error('/orgs/42/saml 503'))
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValueOnce(activeConfig)
    const user = userEvent.setup()
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
  })

  // ── 4. Create configuration ───────────────────────────────────────

  it('creates a configuration from the empty state', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    vi.mocked(saml.createOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'https://idp.acme.test/sso')
    await user.type(screen.getByLabelText('IdP signing certificate'), CERT)
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    await waitFor(() => expect(saml.createOrgSAMLConfig).toHaveBeenCalledWith(42, {
      entity_id: 'https://idp.acme.test/entity',
      sso_url: 'https://idp.acme.test/sso',
      x509_certificate: CERT,
      attribute_mapping: null,
    }))
    expect(await screen.findByText('Current Configuration')).toBeInTheDocument()
  })

  it('shows the backend 409 message inline when a configuration already exists', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    vi.mocked(saml.createOrgSAMLConfig).mockRejectedValue(new Error('this organization already has a SAML configuration'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'https://idp.acme.test/sso')
    await user.type(screen.getByLabelText('IdP signing certificate'), CERT)
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    expect(await screen.findByText('this organization already has a SAML configuration')).toBeInTheDocument()
  })

  // ── 5. Update configuration ───────────────────────────────────────

  it('updates an existing configuration, pre-filling the certificate', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.updateOrgSAMLConfig).mockResolvedValue({ ...activeConfig, sso_url: 'https://idp2.acme.test/sso' })
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    // Certificate pre-filled from the GET response (public, safe to
    // show back -- unlike a secret field).
    expect(screen.getByLabelText('IdP signing certificate')).toHaveValue(CERT)

    const ssoUrlInput = screen.getByLabelText('IdP SSO URL')
    await user.clear(ssoUrlInput)
    await user.type(ssoUrlInput, 'https://idp2.acme.test/sso')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(saml.updateOrgSAMLConfig).toHaveBeenCalledWith(42, {
      entity_id: activeConfig.entity_id,
      sso_url: 'https://idp2.acme.test/sso',
      x509_certificate: CERT,
      attribute_mapping: { email: 'NameID' },
    }))
  })

  // ── 7. Validation errors ──────────────────────────────────────────

  it('shows client-side validation errors before ever calling the backend', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    expect(await screen.findByText('Entity ID is required.')).toBeInTheDocument()
    expect(screen.getByText('IdP SSO URL is required.')).toBeInTheDocument()
    expect(screen.getByText('IdP signing certificate is required.')).toBeInTheDocument()
    expect(saml.createOrgSAMLConfig).not.toHaveBeenCalled()
  })

  it('rejects a non-PEM certificate client-side', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'https://idp.acme.test/sso')
    await user.type(screen.getByLabelText('IdP signing certificate'), 'not a real certificate')
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    expect(await screen.findByText(/Enter a PEM-encoded certificate/)).toBeInTheDocument()
    expect(saml.createOrgSAMLConfig).not.toHaveBeenCalled()
  })

  it('rejects an invalid SSO URL client-side', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'not-a-url')
    await user.type(screen.getByLabelText('IdP signing certificate'), CERT)
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    expect(await screen.findByText('Enter a valid http(s) URL.')).toBeInTheDocument()
  })

  it('surfaces the backend 422 validation message when client-side validation passes but the backend still rejects it', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    vi.mocked(saml.createOrgSAMLConfig).mockRejectedValue(new Error('sso_url must use HTTPS'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'http://idp.acme.test/sso')
    await user.type(screen.getByLabelText('IdP signing certificate'), CERT)
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    expect(await screen.findByText('sso_url must use HTTPS')).toBeInTheDocument()
  })

  // ── 12. Attribute mapping add/edit/remove ─────────────────────────

  it('adds, edits, and removes attribute mapping rows, serialized on submit', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 404'))
    vi.mocked(saml.createOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('No SAML configuration')

    await user.click(screen.getByRole('button', { name: '+ Add mapping' }))
    await user.type(screen.getByLabelText('Attribute mapping key'), 'email')
    await user.type(screen.getByLabelText('Attribute mapping value'), 'NameID')

    await user.click(screen.getByRole('button', { name: '+ Add mapping' }))
    const keys = screen.getAllByLabelText('Attribute mapping key')
    const values = screen.getAllByLabelText('Attribute mapping value')
    await user.type(keys[1], 'first_name')
    await user.type(values[1], 'givenName')

    // Remove the second row before submitting.
    await user.click(screen.getAllByRole('button', { name: /Remove mapping/ })[1])
    expect(screen.getAllByLabelText('Attribute mapping key')).toHaveLength(1)

    await user.type(screen.getByLabelText('Entity ID'), 'https://idp.acme.test/entity')
    await user.type(screen.getByLabelText('IdP SSO URL'), 'https://idp.acme.test/sso')
    await user.type(screen.getByLabelText('IdP signing certificate'), CERT)
    await user.click(screen.getByRole('button', { name: 'Create SAML configuration' }))

    await waitFor(() => expect(saml.createOrgSAMLConfig).toHaveBeenCalledWith(42, expect.objectContaining({
      attribute_mapping: { email: 'NameID' },
    })))
  })

  it('pre-populates the mapping editor from an existing configuration', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    expect(screen.getByDisplayValue('email')).toBeInTheDocument()
    expect(screen.getByDisplayValue('NameID')).toBeInTheDocument()
  })

  // ── 14. Status display/edit ───────────────────────────────────────

  it('shows Active status and offers to disable it', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    expect(screen.getByText('SAML Login Status')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable SAML Login' })).toBeInTheDocument()
  })

  it('disabling SAML login requires confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.updateOrgSAMLConfig).mockResolvedValue(disabledConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Disable SAML Login' }))
    expect(screen.getByText(/stops members from signing in/)).toBeInTheDocument()
    expect(saml.updateOrgSAMLConfig).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: disable SAML login' }))
    await waitFor(() => expect(saml.updateOrgSAMLConfig).toHaveBeenCalledWith(42, { status: 'disabled' }))
  })

  it('offers to activate a disabled configuration', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(disabledConfig)
    vi.mocked(saml.updateOrgSAMLConfig).mockResolvedValue(activeConfig)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Activate SAML Login' }))
    await user.click(screen.getByRole('button', { name: 'Confirm: activate SAML login' }))
    await waitFor(() => expect(saml.updateOrgSAMLConfig).toHaveBeenCalledWith(42, { status: 'active' }))
  })

  // ── 6. Delete configuration ────────────────────────────────────────

  it('deletes the configuration after confirmation, returning to the empty state', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.deleteOrgSAMLConfig).mockResolvedValue(undefined)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Delete SAML configuration' }))
    expect(saml.deleteOrgSAMLConfig).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: delete configuration' }))
    await waitFor(() => expect(saml.deleteOrgSAMLConfig).toHaveBeenCalledWith(42))
    expect(await screen.findByText('No SAML configuration')).toBeInTheDocument()
  })

  it('surfaces a delete failure inline instead of silently clearing the config', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.deleteOrgSAMLConfig).mockRejectedValue(new Error('/orgs/42/saml 403'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Delete SAML configuration' }))
    await user.click(screen.getByRole('button', { name: 'Confirm: delete configuration' }))

    expect(await screen.findByText('/orgs/42/saml 403')).toBeInTheDocument()
    expect(screen.getByText('Current Configuration')).toBeInTheDocument()
  })

  // ── 15. Metadata download ─────────────────────────────────────────

  it('offers a metadata download once a configuration exists, using the trusted org slug', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.downloadSpMetadata).mockResolvedValue(undefined)
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    expect(await screen.findByText('Service Provider Metadata')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Download SP Metadata' }))
    await waitFor(() => expect(saml.downloadSpMetadata).toHaveBeenCalledWith('acme'))
  })

  it('surfaces a metadata download failure inline', async () => {
    const user = userEvent.setup()
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    vi.mocked(saml.downloadSpMetadata).mockRejectedValue(new Error('/auth/saml/acme/metadata 503'))
    render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    await user.click(screen.getByRole('button', { name: 'Download SP Metadata' }))
    expect(await screen.findByText('/auth/saml/acme/metadata 503')).toBeInTheDocument()
  })

  // ── Security / rendering hygiene ──────────────────────────────────

  it('never renders an actual private key or secret value anywhere on this page', async () => {
    // Deliberately concrete leak signatures (a real PEM private-key
    // marker, an actual secret/token field), not the bare word "private
    // key" -- this page's own certificate field legitimately explains
    // "this is not a private key, never paste one here," which a naive
    // /private[_ ]?key/i check would misflag as the leak it's warning
    // against. Same reasoning OrganizationMFAPolicyPage.test.tsx's own
    // version of this test uses concrete signatures
    // (otpauth://, challenge_token, encrypted_secret).
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValue(activeConfig)
    const { container } = render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/BEGIN (RSA )?PRIVATE KEY/i)
    expect(text).not.toMatch(/client_secret/i)
    expect(text).not.toMatch(/encrypted_secret/i)
  })

  // ── Organization switching ────────────────────────────────────────

  it('re-fetches when the orgId prop changes to a different organization', async () => {
    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValueOnce(activeConfig)
    const { rerender } = render(<SAMLSettingsPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Configuration')
    expect(saml.fetchOrgSAMLConfig).toHaveBeenCalledWith(42)

    vi.mocked(saml.fetchOrgSAMLConfig).mockResolvedValueOnce({ ...activeConfig, entity_id: 'https://idp.other.test/entity' })
    rerender(<SAMLSettingsPage orgId={99} onBack={vi.fn()} />)

    await waitFor(() => expect(saml.fetchOrgSAMLConfig).toHaveBeenCalledWith(99))
    expect(await screen.findByText('https://idp.other.test/entity')).toBeInTheDocument()
  })
})
