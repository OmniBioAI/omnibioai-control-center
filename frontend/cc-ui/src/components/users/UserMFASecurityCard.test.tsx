import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UserMFASecurityCard from './UserMFASecurityCard'
import * as security from '../../security'
import type { PlatformUserDetail } from '../../users'

vi.mock('../../security', async () => {
  const actual = await vi.importActual<typeof import('../../security')>('../../security')
  return { ...actual, resetUserMFA: vi.fn() }
})

const baseUser: PlatformUserDetail = {
  id: 42, email: 'someone@acme.test', status: 'active', created_at: '2026-07-15T10:00:00',
  global_roles: [], memberships: [],
  status_changed_at: null, status_changed_reason: null, status_changed_by_email: null,
  last_login_at: null, authentication_method: null,
  mfa_enabled: false, mfa_status: 'disabled', mfa_primary_method: null,
  mfa_enabled_at: null, mfa_last_verified_at: null, mfa_devices: [], mfa_recovery_codes_remaining: 0,
}

const enrolledUser: PlatformUserDetail = {
  ...baseUser,
  mfa_enabled: true, mfa_status: 'enabled', mfa_primary_method: 'totp',
  mfa_enabled_at: '2026-07-20T09:00:00', mfa_last_verified_at: '2026-08-01T14:00:00',
  mfa_devices: [
    { device_type: 'totp', label: 'iPhone', created_at: '2026-07-20T09:00:00', last_used_at: '2026-08-01T14:00:00' },
  ],
  mfa_recovery_codes_remaining: 7,
}

describe('UserMFASecurityCard', () => {
  beforeEach(() => {
    vi.mocked(security.resetUserMFA).mockReset()
  })

  it('shows MFA disabled with no devices or recovery codes when nothing is enrolled', () => {
    render(<UserMFASecurityCard user={baseUser} onChanged={vi.fn()} />)
    expect(screen.getByText('No')).toBeInTheDocument()
    expect(screen.getByText('Recovery Codes Remaining')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
    // No Reset MFA action when nothing is enrolled -- nothing to reset.
    expect(screen.queryByRole('button', { name: 'Reset MFA' })).not.toBeInTheDocument()
  })

  it('shows MFA enabled with the primary method, enabled-at, and last-verified timestamps', () => {
    render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)
    expect(screen.getByText('Yes')).toBeInTheDocument()
    expect(screen.getByText('Authenticator App')).toBeInTheDocument()
    // Rendered twice: the Enabled At field and the device's own Added
    // field share the same enrollment timestamp in this fixture.
    expect(screen.getAllByText(new Date('2026-07-20T09:00:00').toLocaleString(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    }))).toHaveLength(2)
  })

  it('lists each enrolled device with added/last-used timestamps', () => {
    render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)
    expect(screen.getByText('Devices')).toBeInTheDocument()
    expect(screen.getByText('iPhone')).toBeInTheDocument()
  })

  it('shows the remaining recovery code count', () => {
    render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)
    expect(screen.getByText('Recovery Codes Remaining')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('requires confirmation before resetting MFA, with the removal warning', async () => {
    const user = userEvent.setup()
    render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Reset MFA' }))
    expect(screen.getByText(/will remove all MFA devices and invalidate recovery codes/)).toBeInTheDocument()
    expect(security.resetUserMFA).not.toHaveBeenCalled()
  })

  it('resets MFA on confirmation and calls onChanged', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    vi.mocked(security.resetUserMFA).mockResolvedValue({ user_id: 42, mfa_enabled: false, mfa_status: 'disabled' })
    render(<UserMFASecurityCard user={enrolledUser} onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Reset MFA' }))
    await user.click(screen.getByRole('button', { name: 'Confirm reset' }))

    await waitFor(() => expect(security.resetUserMFA).toHaveBeenCalledWith(42))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('surfaces a permission-denied error inline without calling onChanged', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    vi.mocked(security.resetUserMFA).mockRejectedValue(new Error('Forbidden'))
    render(<UserMFASecurityCard user={enrolledUser} onChanged={onChanged} />)

    await user.click(screen.getByRole('button', { name: 'Reset MFA' }))
    await user.click(screen.getByRole('button', { name: 'Confirm reset' }))

    expect(await screen.findByText('Forbidden')).toBeInTheDocument()
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('cancels the reset without calling resetUserMFA', async () => {
    const user = userEvent.setup()
    render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Reset MFA' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.getByRole('button', { name: 'Reset MFA' })).toBeInTheDocument()
    expect(security.resetUserMFA).not.toHaveBeenCalled()
  })

  it('never renders a secret, recovery code value, or token anywhere on this card', () => {
    const { container } = render(<UserMFASecurityCard user={enrolledUser} onChanged={vi.fn()} />)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/otpauth:\/\//i)
    expect(text).not.toMatch(/encrypted_secret/i)
    expect(text).not.toMatch(/challenge_token/i)
  })
})
