import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import LoginScreen from './LoginScreen'
import * as auth from '../auth'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return { ...actual, login: vi.fn(), completeMFAChallenge: vi.fn(), resendMFAEmailCode: vi.fn() }
})

describe('LoginScreen', () => {
  beforeEach(() => {
    vi.mocked(auth.login).mockReset()
    vi.mocked(auth.completeMFAChallenge).mockReset()
    vi.mocked(auth.resendMFAEmailCode).mockReset()
  })

  afterEach(() => vi.unstubAllEnvs())

  it('renders email and password login without unavailable provider buttons', () => {
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByText(/Admin Portal/)).toBeInTheDocument()
    expect(screen.getByText('Ecosystem Management Console')).toBeInTheDocument()
    expect(screen.getByText('Development')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveAttribute('type', 'email')
    expect(document.querySelector('input[type="password"]')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sign In/i })).toBeInTheDocument()
    expect(screen.queryByText('Continue with')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Continue with (Google|Microsoft|GitHub)/i })).not.toBeInTheDocument()
  })

  it('uses the configured environment label when provided', () => {
    vi.stubEnv('VITE_ENVIRONMENT_LABEL', 'Staging')
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByText('Staging')).toBeInTheDocument()
    expect(screen.queryByText('Production Control Plane')).not.toBeInTheDocument()
  })

  it('calls onSuccess with the resolved session user on successful login', async () => {
    const user = userEvent.setup()
    const sessionUser: auth.SessionUser = {
      userId: '1', email: 'admin@omnibioai.org', roles: ['admin'],
      permissions: ['manage_config'], orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
    }
    vi.mocked(auth.login).mockResolvedValue(sessionUser)
    const onSuccess = vi.fn()

    render(<LoginScreen onSuccess={onSuccess} />)
    await user.type(screen.getByRole('textbox'), 'admin@omnibioai.org')
    await user.type(document.querySelector('input[type="password"]')!, 'hunter2')
    await user.click(screen.getByRole('button', { name: /Sign In/i }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith(sessionUser))
  })

  it('shows the generic authentication-failure message on invalid credentials', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.login).mockRejectedValue(new Error('Authentication failed'))

    render(<LoginScreen onSuccess={vi.fn()} />)
    await user.type(screen.getByRole('textbox'), 'nobody@omnibioai.org')
    await user.type(document.querySelector('input[type="password"]')!, 'wrong')
    await user.click(screen.getByRole('button', { name: /Sign In/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Authentication failed')
  })

  it('completes an MFA challenge without displaying its challenge token', async () => {
    const user = userEvent.setup()
    const sessionUser: auth.SessionUser = {
      userId: '1', email: 'mfa-user@example.invalid', roles: ['admin'],
      permissions: [], orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
    }
    vi.mocked(auth.login).mockRejectedValue(
      new auth.MFAChallengeRequiredError('isolated-test-challenge', ['totp', 'recovery_code']),
    )
    vi.mocked(auth.completeMFAChallenge).mockResolvedValue(sessionUser)
    const onSuccess = vi.fn()

    render(<LoginScreen onSuccess={onSuccess} />)
    await user.type(screen.getByRole('textbox'), 'mfa-user@example.invalid')
    await user.type(document.querySelector('input[type="password"]')!, 'test-only')
    await user.click(screen.getByRole('button', { name: /Sign In/i }))

    const code = await screen.findByRole('textbox', { name: /verification code/i })
    expect(screen.queryByText('isolated-test-challenge')).not.toBeInTheDocument()
    await user.type(code, '000000')
    await user.click(screen.getByRole('button', { name: 'Verify' }))

    await waitFor(() => expect(auth.completeMFAChallenge).toHaveBeenCalledWith('isolated-test-challenge', '000000'))
    expect(onSuccess).toHaveBeenCalledWith(sessionUser)
  })

  it('requires email first and then preserves the enrolled authenticator step', async () => {
    const user = userEvent.setup()
    const sessionUser: auth.SessionUser = {
      userId: '1', email: 'admin@omnibioai.org', roles: ['admin'], permissions: [],
      orgId: null, orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
    }
    vi.mocked(auth.login).mockRejectedValue(
      new auth.MFAChallengeRequiredError('email-test-challenge', ['email']),
    )
    vi.mocked(auth.completeMFAChallenge)
      .mockRejectedValueOnce(new auth.MFAChallengeRequiredError('totp-test-challenge', ['totp', 'recovery_code']))
      .mockResolvedValueOnce(sessionUser)
    const onSuccess = vi.fn()

    render(<LoginScreen onSuccess={onSuccess} />)
    await user.type(screen.getByRole('textbox'), 'admin@omnibioai.org')
    await user.type(document.querySelector('input[type="password"]')!, 'test-only')
    await user.click(screen.getByRole('button', { name: /Sign In/i }))

    expect(await screen.findByText(/six-digit code sent/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Google Authenticator' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Resend Code \(60s\)/ })).toBeDisabled()
    await user.type(screen.getByRole('textbox', { name: /verification code/i }), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(auth.completeMFAChallenge).toHaveBeenCalledWith(
      'email-test-challenge', '123456', 'email',
    ))
    expect(await screen.findByText(/Google Authenticator or one of your recovery codes/i)).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /verification code/i }), '654321')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(auth.completeMFAChallenge).toHaveBeenLastCalledWith(
      'totp-test-challenge', '654321',
    ))
    expect(onSuccess).toHaveBeenCalledWith(sessionUser)
  })
})
