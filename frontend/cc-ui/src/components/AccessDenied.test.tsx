import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import AccessDenied from './AccessDenied'
import type { SessionUser } from '../auth'

const user: SessionUser = {
  userId: '2', email: 'no-perms@omnibioai.org', roles: ['user'],
  permissions: [], orgId: null, orgRoles: [], schemaVersion: 2,
}

describe('AccessDenied', () => {
  it('shows the permission-denied message and the signed-in email', () => {
    render(<AccessDenied user={user} onSignOut={vi.fn()} />)
    expect(
      screen.getByText('Your account does not have permission to access the Admin Portal.')
    ).toBeInTheDocument()
    expect(screen.getByText(/no-perms@omnibioai\.org/)).toBeInTheDocument()
  })

  it('calls onSignOut when the sign-out button is clicked', async () => {
    const onSignOut = vi.fn()
    const u = userEvent.setup()
    render(<AccessDenied user={user} onSignOut={onSignOut} />)
    await u.click(screen.getByRole('button', { name: /Sign out/i }))
    expect(onSignOut).toHaveBeenCalledTimes(1)
  })
})
