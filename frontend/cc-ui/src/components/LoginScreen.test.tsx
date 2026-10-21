import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    vi.mocked(auth.login).mockReset()
    vi.mocked(auth.completeMFAChallenge).mockReset()
    vi.mocked(auth.resendMFAEmailCode).mockReset()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })

  it('renders email and password login without unavailable provider buttons', () => {
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getAllByText(/Admin Portal/).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: 'Control the ecosystem with confidence.' })).toBeInTheDocument()
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

  it.each([
    ['Development', 'admin-environment-development'],
    ['Staging', 'admin-environment-staging'],
    ['Production', 'admin-environment-production'],
  ])('uses the %s environment badge tone', (label, className) => {
    vi.stubEnv('VITE_ENVIRONMENT_LABEL', label)
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByText(label)).toHaveClass(className)
  })

  it('offers an accessible show-password toggle and Caps Lock warning', async () => {
    const user = userEvent.setup()
    render(<LoginScreen onSuccess={vi.fn()} />)
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Show password' }))
    expect(password).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Hide password' })).toHaveAttribute('aria-pressed', 'true')

    password.focus()
    await user.keyboard('{CapsLock}')
    expect(screen.getByRole('status')).toHaveTextContent('Caps Lock is on.')
    const capsOff = createEvent.keyUp(password, { key: 'CapsLock' })
    Object.defineProperty(capsOff, 'getModifierState', { value: () => false })
    fireEvent(password, capsOff)
    expect(screen.queryByText('Caps Lock is on.')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Hide password' }))
    expect(password).toHaveAttribute('type', 'password')
  })

  it('shows the platform-owner contact because password reset is not available', () => {
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByRole('link', { name: 'Contact your platform owner' })).toHaveAttribute('href', expect.stringContaining('mailto:'))
  })

  it('shows build metadata and the requested footer destinations', () => {
    vi.stubEnv('VITE_APP_VERSION', 'v1.2.3')
    vi.stubEnv('VITE_BUILD_COMMIT', '1234567890abcdef')
    render(<LoginScreen onSuccess={vi.fn()} />)
    const footer = screen.getByRole('navigation', { name: 'Footer links' })
    expect(footer).toHaveTextContent('Docs')
    expect(footer).toHaveTextContent('Status')
    expect(footer).toHaveTextContent('Privacy')
    expect(footer).toHaveTextContent('Support')
    expect(footer.querySelectorAll('a')).toHaveLength(4)
    expect(screen.getByRole('link', { name: 'Open Studio' })).toHaveAttribute('href', 'https://webstudio.omnibioai.org')
    expect(document.querySelector('.admin-login-footer')).toHaveTextContent(/v1\.2\.3 · 12345678/)
  })

  it('loads public system status quietly and links to Health', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ overall_status: 'WARN' }) }))
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(await screen.findByText(/Platform status:/)).toHaveTextContent('WARN')
    expect(fetch).toHaveBeenCalledWith('/summary', expect.objectContaining({ credentials: 'omit' }))
    expect(screen.getByRole('link', { name: 'Health' })).toHaveAttribute('href', '/platform-health')
  })

  it('keeps sign-in usable when the public summary is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeEnabled()
    expect(screen.queryByText(/Platform status:/)).not.toBeInTheDocument()
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

  it('shows a generic authentication-failure message without leaking server details', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.login).mockRejectedValue(new Error('privileged backend detail'))

    render(<LoginScreen onSuccess={vi.fn()} />)
    await user.type(screen.getByRole('textbox'), 'nobody@omnibioai.org')
    await user.type(document.querySelector('input[type="password"]')!, 'wrong')
    await user.click(screen.getByRole('button', { name: /Sign In/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to sign in. Check your details or contact your platform owner.')
    expect(screen.queryByText('privileged backend detail')).not.toBeInTheDocument()
  })

  it('shows a specific wait message for rate limits', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.login).mockRejectedValue(new auth.AuthRateLimitError())

    render(<LoginScreen onSuccess={vi.fn()} />)
    await user.type(screen.getByLabelText('Email address'), 'admin@omnibioai.org')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many sign-in attempts. Please wait before trying again.')
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
    expect(code).toHaveFocus()
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
    expect(await screen.findByText(/authenticator app or one of your recovery codes/i)).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: /verification code/i }), '654321')
    await user.click(screen.getByRole('button', { name: 'Verify' }))
    await waitFor(() => expect(auth.completeMFAChallenge).toHaveBeenLastCalledWith(
      'totp-test-challenge', '654321',
    ))
    expect(onSuccess).toHaveBeenCalledWith(sessionUser)
  })
})
