import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ManualLicensesPage from './ManualLicensesPage'
import * as licenses from '../licenses'

vi.mock('../licenses', async () => {
  const actual = await vi.importActual<typeof import('../licenses')>('../licenses')
  return {
    ...actual,
    fetchLicensePolicy: vi.fn(), fetchLicenses: vi.fn(), issueLicense: vi.fn(),
    fetchLicenseHistory: vi.fn(), renewLicense: vi.fn(), revokeLicense: vi.fn(), lookupLicenseIdentity: vi.fn(),
  }
})

const metadata: licenses.LicenseMetadata = {
  id: 7, key_prefix: 'OMNI-ABCD', masked_key: 'OMNI-ABCD-••••-••••-••••',
  recipient_name: 'Dev Person', email: 'dev@test', user_id: 10, organization_id: 1,
  persona: 'developer', iam_role: 'scientist', plan: 'beta', platform: 'both',
  created_at: '2026-10-16T12:00:00Z', expires_at: '2026-11-15T12:00:00Z',
  renewed_at: null, last_used_at: null, revoked_at: null, revoked_reason: null, status: 'active',
}

beforeEach(() => {
  vi.mocked(licenses.fetchLicensePolicy).mockReset().mockResolvedValue({
    validity_days: [30, 90], personas: ['developer', 'application_user'],
    issuance_enabled: true, unknown_identity_action: 'provisioning_required',
  })
  vi.mocked(licenses.fetchLicenses).mockReset().mockResolvedValue({ items: [metadata], total: 1 })
  vi.mocked(licenses.issueLicense).mockReset().mockResolvedValue({
    license: metadata, key: 'OMNI-ABCD-EFGH-JKMP-QRST', one_time_display: true, idempotent_replay: false,
  })
  vi.mocked(licenses.lookupLicenseIdentity).mockReset().mockResolvedValue({ user_id: 10, email: 'dev@test', organization_id: 1 })
})

describe('ManualLicensesPage', () => {
  it('renders only policy-backed personas/validities and never historical plaintext', async () => {
    render(<ManualLicensesPage />)
    expect(await screen.findByRole('heading', { name: 'License Management' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Issue New License' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'License Registry' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Developer' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Application User' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '30 days' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '90 days' })).toBeInTheDocument()
    expect(screen.getByText('OMNI-ABCD-••••-••••-••••')).toBeInTheDocument()
  })

  it('issues with confirmation fields and displays the returned key once', async () => {
    const user = userEvent.setup()
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'License Management' })
    await user.type(screen.getByRole('textbox', { name: /full name/i }), 'Dev Person')
    await user.type(screen.getByRole('textbox', { name: /email/i }), 'dev@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '1')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))
    await screen.findByRole('combobox', { name: 'Select verified identity' })
    const issueButton = screen.getByRole('button', { name: 'Issue License' })
    expect(issueButton.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    await user.click(issueButton)
    await waitFor(() => expect(licenses.issueLicense).toHaveBeenCalledWith(
      expect.objectContaining({
        full_name: 'Dev Person', email: 'dev@test', persona: 'developer',
        validity_days: 30, organization_id: 1,
      }),
      expect.any(String),
    ))
    expect(await screen.findByText('OMNI-ABCD-EFGH-JKMP-QRST')).toBeInTheDocument()
  })

  it('keeps generation disabled when issuance policy is not configured', async () => {
    vi.mocked(licenses.fetchLicensePolicy).mockResolvedValue({
      validity_days: [], personas: ['developer', 'application_user'],
      issuance_enabled: false, unknown_identity_action: 'provisioning_required',
    })
    render(<ManualLicensesPage />)

    expect(await screen.findByRole('option', { name: 'Policy not configured' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Issue License' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent(
      'The authoritative license policy has no supported validity options configured.',
    )
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('names a policy failure and disables the entire issuance form', async () => {
    vi.mocked(licenses.fetchLicensePolicy).mockRejectedValue(Object.assign(
      new Error('Not Found'),
      { status: 404, path: '/platform/licenses/policy' },
    ))
    render(<ManualLicensesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Couldn’t load the license policy: the API route is unavailable (404 from /platform/licenses/policy).',
    )
    expect(screen.getByRole('group', { name: 'Issue New License fields' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: /full name/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Check identity' })).toBeDisabled()
    const issueButton = screen.getByRole('button', { name: 'Issue License' })
    expect(issueButton).toBeDisabled()

    fireEvent.submit(issueButton.closest('form')!)
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('names a registry failure and prevents issuance even with a valid policy', async () => {
    vi.mocked(licenses.fetchLicenses).mockRejectedValue(Object.assign(
      new Error('Not Found'),
      { status: 404, path: '/platform/licenses' },
    ))
    render(<ManualLicensesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Couldn’t load the license registry: the API route is unavailable (404 from /platform/licenses).',
    )
    expect(screen.getByRole('group', { name: 'Issue New License fields' })).toBeDisabled()
    const issueButton = screen.getByRole('button', { name: 'Issue License' })
    expect(issueButton).toBeDisabled()

    fireEvent.submit(issueButton.closest('form')!)
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('recovers through Retry after a missing policy route becomes available', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.fetchLicensePolicy).mockRejectedValueOnce(Object.assign(
      new Error('Not Found'),
      { status: 404, path: '/platform/licenses/policy' },
    ))
    render(<ManualLicensesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('the API route is unavailable')
    expect(screen.getByRole('group', { name: 'Issue New License fields' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByRole('option', { name: '30 days' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Issue New License fields' })).toBeEnabled()
    expect(licenses.fetchLicensePolicy).toHaveBeenCalledTimes(2)
    expect(licenses.fetchLicenses).toHaveBeenCalledTimes(2)
  })

  it.each([
    [401, 'authentication is required'],
    [403, 'this account is not authorized'],
    [503, 'the service or one of its dependencies is unavailable'],
  ])('distinguishes a %i registry failure for the operator', async (status, message) => {
    vi.mocked(licenses.fetchLicenses).mockRejectedValue(Object.assign(
      new Error('load failed'),
      { status, path: '/platform/licenses' },
    ))
    render(<ManualLicensesPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(screen.getByRole('group', { name: 'Issue New License fields' })).toBeDisabled()
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('explains missing identities and links to organization onboarding without issuing', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.lookupLicenseIdentity).mockRejectedValue(Object.assign(
      new Error('No account exists for this email. Complete the approved user invitation/onboarding workflow before issuing a license.'),
      { code: 'identity_missing' },
    ))
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'Issue New License' })
    await user.type(screen.getByRole('textbox', { name: /existing identity email/i }), 'new@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '1')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/No account exists/)
    expect(screen.getByRole('link', { name: 'Invite User through organization onboarding' })).toHaveAttribute('href', '/organizations/1?inviteEmail=new%40test')
    expect(screen.getByRole('button', { name: 'Issue License' })).toBeDisabled()
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('does not allow an identity with no active membership in the selected tenant', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.lookupLicenseIdentity).mockRejectedValue(Object.assign(
      new Error('This account does not have an accepted, active membership in the selected organization.'),
      { code: 'identity_membership_required' },
    ))
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'Issue New License' })
    await user.type(screen.getByRole('textbox', { name: /existing identity email/i }), 'dev@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '2')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/accepted, active membership/)
    expect(screen.getByRole('button', { name: 'Issue License' })).toBeDisabled()
    expect(licenses.issueLicense).not.toHaveBeenCalled()
  })

  it('surfaces unauthorized issuance and always releases the submitting state', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.issueLicense).mockRejectedValue(new Error('403 Forbidden'))
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'Issue New License' })
    await user.type(screen.getByRole('textbox', { name: /full name/i }), 'Dev Person')
    await user.type(screen.getByRole('textbox', { name: /existing identity email/i }), 'dev@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '1')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))
    await screen.findByRole('combobox', { name: 'Select verified identity' })
    await user.click(screen.getByRole('button', { name: 'Issue License' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('403 Forbidden')
    expect(screen.getByRole('button', { name: 'Issue License' })).toBeEnabled()
    expect(licenses.issueLicense).toHaveBeenCalledTimes(1)
  })

  it('keeps the legacy Admin path available when directory lookup is forbidden, with Auth as final gate', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.lookupLicenseIdentity).mockRejectedValue(new Error('/platform/users 403'))
    vi.mocked(licenses.issueLicense).mockRejectedValue(Object.assign(
      new Error('No identity exists for this email; use the approved invitation workflow first'),
      { code: 'provisioning_required' },
    ))
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'Issue New License' })
    await user.type(screen.getByRole('textbox', { name: /full name/i }), 'New User')
    await user.type(screen.getByRole('textbox', { name: /existing identity email/i }), 'new@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '1')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Auth will verify account and organization eligibility/)
    const issueButton = screen.getByRole('button', { name: 'Issue License' })
    expect(issueButton).toBeEnabled()
    await user.click(issueButton)
    expect(await screen.findByRole('alert')).toHaveTextContent(/approved invitation workflow first/)
    expect(screen.getByRole('link', { name: 'Invite User through organization onboarding' })).toHaveAttribute('href', '/organizations/1?inviteEmail=new%40test')
    expect(issueButton).toBeEnabled()
  })

  it('shows an actionable backend failure and releases the submitting state', async () => {
    const user = userEvent.setup()
    vi.mocked(licenses.issueLicense).mockRejectedValue(new Error('Service temporarily unavailable'))
    render(<ManualLicensesPage />)
    await screen.findByRole('heading', { name: 'Issue New License' })
    await user.type(screen.getByRole('textbox', { name: /full name/i }), 'Dev Person')
    await user.type(screen.getByRole('textbox', { name: /existing identity email/i }), 'dev@test')
    await user.type(screen.getByRole('spinbutton', { name: /organization id/i }), '1')
    await user.click(screen.getByRole('button', { name: 'Check identity' }))
    await screen.findByRole('combobox', { name: 'Select verified identity' })
    await user.click(screen.getByRole('button', { name: 'Issue License' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Service temporarily unavailable')
    expect(screen.getByRole('button', { name: 'Issue License' })).toBeEnabled()
  })
})
