import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LoginScreen from './LoginScreen'
import * as auth from '../auth'

vi.mock('../auth', async () => {
  const actual = await vi.importActual<typeof import('../auth')>('../auth')
  return { ...actual, login: vi.fn() }
})

describe('LoginScreen', () => {
  beforeEach(() => {
    vi.mocked(auth.login).mockReset()
  })

  it('renders the admin portal branding and form', () => {
    render(<LoginScreen onSuccess={vi.fn()} />)
    expect(screen.getByText(/Admin Portal/)).toBeInTheDocument()
    expect(screen.getByText('Ecosystem Management Console')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sign In/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Continue with Google/i })).toBeDisabled()
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
})
