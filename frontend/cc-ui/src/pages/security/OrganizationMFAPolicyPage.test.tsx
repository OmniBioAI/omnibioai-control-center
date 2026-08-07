import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OrganizationMFAPolicyPage from './OrganizationMFAPolicyPage'
import * as auth from '../../auth'
import * as security from '../../security'
import type { OrgMFAPolicy } from '../../security'
import * as organizations from '../../organizations'
import type { MyOrg } from '../../organizations'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, hasPermission: vi.fn(), hasPlatformAdminAccess: vi.fn() }
})

vi.mock('../../security', async () => {
  const actual = await vi.importActual<typeof import('../../security')>('../../security')
  return {
    ...actual,
    fetchOrgMFAPolicy: vi.fn(),
    createOrgMFAPolicy: vi.fn(),
    updateOrgMFAPolicy: vi.fn(),
    enableMFAPolicyOverride: vi.fn(),
    clearMFAPolicyOverride: vi.fn(),
  }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchMyOrg: vi.fn(), fetchPlatformOrgDetail: vi.fn() }
})

const disabledPolicy: OrgMFAPolicy = {
  required: false,
  created_at: '2026-08-01T00:00:00',
  updated_at: null,
  enabled_at: null,
  enabled_by_email: null,
  override_active: false,
  override_reason: null,
}

const requiredPolicy: OrgMFAPolicy = {
  ...disabledPolicy,
  required: true,
  enabled_at: '2026-08-01T00:00:00',
  enabled_by_email: 'admin@acme.test',
}

const myOrg: MyOrg = {
  id: 42, slug: 'acme', name: 'Acme Corp', plan: 'beta', status: 'active',
  status_changed_at: null, status_changed_reason: null, status_changed_by_user_id: null,
}

describe('OrganizationMFAPolicyPage', () => {
  beforeEach(() => {
    vi.mocked(auth.hasPermission).mockReturnValue(false)
    vi.mocked(auth.hasPlatformAdminAccess).mockReturnValue(false)
    vi.mocked(security.fetchOrgMFAPolicy).mockReset()
    vi.mocked(security.createOrgMFAPolicy).mockReset()
    vi.mocked(security.updateOrgMFAPolicy).mockReset()
    vi.mocked(security.enableMFAPolicyOverride).mockReset()
    vi.mocked(security.clearMFAPolicyOverride).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockReset()
    vi.mocked(organizations.fetchPlatformOrgDetail).mockReset()
    vi.mocked(organizations.fetchMyOrg).mockResolvedValue(myOrg)
  })

  it('shows a loading state while the policy fetch is in flight', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockReturnValue(new Promise(() => {}))
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    expect(await screen.findByText('Loading MFA policy…')).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not the policy', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockRejectedValue(new Error('/orgs/42/mfa-policy 403'))
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('Current Policy')).not.toBeInTheDocument()
  })

  it('shows a session-expired state on a 401, not a permission-denied one', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockRejectedValue(new Error('/orgs/42/mfa-policy 401'))
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Session expired')).toBeInTheDocument()
    expect(screen.queryByText('Permission denied')).not.toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockRejectedValueOnce(new Error('/orgs/42/mfa-policy 503'))
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValueOnce(disabledPolicy)
    const user = userEvent.setup()
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByText('Current Policy')).toBeInTheDocument()
  })

  it('shows the no-policy state and lets an admin configure one', async () => {
    const user = userEvent.setup()
    vi.mocked(security.fetchOrgMFAPolicy).mockRejectedValue(new Error('/orgs/42/mfa-policy 404'))
    vi.mocked(security.createOrgMFAPolicy).mockResolvedValue(disabledPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('No MFA policy')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Configure MFA policy' }))

    await waitFor(() => expect(security.createOrgMFAPolicy).toHaveBeenCalledWith(42, false))
    expect(await screen.findByText('Current Policy')).toBeInTheDocument()
  })

  it('displays the disabled-policy state', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(disabledPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Current Policy')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText('OFF')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Enable MFA Requirement' })).toBeInTheDocument()
  })

  it('displays the enabled-policy state with who enabled it', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)

    expect(await screen.findByText('Current Policy')).toBeInTheDocument()
    expect(screen.getByText('Enabled')).toBeInTheDocument()
    expect(screen.getByText('ON')).toBeInTheDocument()
    expect(screen.getByText('admin@acme.test')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable MFA Requirement' })).toBeInTheDocument()
  })

  it('requires confirmation before enabling the MFA requirement, and shows the warning', async () => {
    const user = userEvent.setup()
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(disabledPolicy)
    vi.mocked(security.updateOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Policy')

    await user.click(screen.getByRole('button', { name: 'Enable MFA Requirement' }))
    expect(screen.getByText(/may prevent users without enrolled MFA from logging in/)).toBeInTheDocument()
    expect(security.updateOrgMFAPolicy).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: enable MFA requirement' }))
    await waitFor(() => expect(security.updateOrgMFAPolicy).toHaveBeenCalledWith(42, true))
  })

  it('disables the MFA requirement without a confirmation step', async () => {
    const user = userEvent.setup()
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    vi.mocked(security.updateOrgMFAPolicy).mockResolvedValue(disabledPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Policy')

    await user.click(screen.getByRole('button', { name: 'Disable MFA Requirement' }))
    await waitFor(() => expect(security.updateOrgMFAPolicy).toHaveBeenCalledWith(42, false))
  })

  it('hides the Break Glass card entirely without manage_all_orgs', async () => {
    vi.mocked(auth.hasPermission).mockReturnValue(false)
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Policy')

    expect(screen.queryByText('Break Glass Override')).not.toBeInTheDocument()
  })

  it('shows the Break Glass card with manage_all_orgs, and requires a reason plus confirmation to enable', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPermission).mockImplementation(p => p === 'manage_all_orgs')
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    vi.mocked(security.enableMFAPolicyOverride).mockResolvedValue({ ...requiredPolicy, override_active: true, override_reason: 'admin locked out' })
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Break Glass Override')

    // Rendered twice: the Current Policy card's Override Status field,
    // and the Break Glass card's own "Current override status" line.
    expect(screen.getAllByText('Inactive')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Enable override' }))
    expect(screen.getByText(/temporarily disables MFA enforcement/)).toBeInTheDocument()

    // No reason yet -- confirming should not call the backend.
    await user.click(screen.getByRole('button', { name: 'Confirm: enable override' }))
    expect(security.enableMFAPolicyOverride).not.toHaveBeenCalled()
    expect(await screen.findByText(/reason is required/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Override reason'), 'admin locked out')
    await user.click(screen.getByRole('button', { name: 'Confirm: enable override' }))

    await waitFor(() => expect(security.enableMFAPolicyOverride).toHaveBeenCalledWith(42, 'admin locked out'))
  })

  it('removes an active override after confirmation', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPermission).mockImplementation(p => p === 'manage_all_orgs')
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue({ ...requiredPolicy, override_active: true, override_reason: 'temp' })
    vi.mocked(security.clearMFAPolicyOverride).mockResolvedValue({ ...requiredPolicy, override_active: false, override_reason: null })
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Break Glass Override')

    await user.click(screen.getByRole('button', { name: 'Disable override' }))
    expect(security.clearMFAPolicyOverride).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm: disable override' }))
    await waitFor(() => expect(security.clearMFAPolicyOverride).toHaveBeenCalledWith(42))
  })

  it('permission denied: the override endpoint failing with 403 surfaces inline, not silently', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.hasPermission).mockImplementation(p => p === 'manage_all_orgs')
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    vi.mocked(security.enableMFAPolicyOverride).mockRejectedValue(new Error('Forbidden'))
    render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Break Glass Override')

    await user.click(screen.getByRole('button', { name: 'Enable override' }))
    await user.type(screen.getByLabelText('Override reason'), 'x')
    await user.click(screen.getByRole('button', { name: 'Confirm: enable override' }))

    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
  })

  it('never renders a secret, recovery code, or token anywhere on this page', async () => {
    vi.mocked(security.fetchOrgMFAPolicy).mockResolvedValue(requiredPolicy)
    const { container } = render(<OrganizationMFAPolicyPage orgId={42} onBack={vi.fn()} />)
    await screen.findByText('Current Policy')

    const text = container.textContent ?? ''
    expect(text).not.toMatch(/otpauth:\/\//i)
    expect(text).not.toMatch(/challenge_token/i)
    expect(text).not.toMatch(/encrypted_secret/i)
  })
})
