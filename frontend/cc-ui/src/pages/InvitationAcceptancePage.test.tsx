import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const api = vi.hoisted(() => ({ postInvitationToken: vi.fn() }))
vi.mock('../organizations', () => api)
vi.mock('../auth', () => ({ getToken: () => null }))
import InvitationAcceptancePage from './InvitationAcceptancePage'

describe('InvitationAcceptancePage', () => {
  beforeEach(() => {
    api.postInvitationToken.mockReset()
    window.history.replaceState(null, '', '/invitations/accept#token=opaque-test-token')
  })

  it('creates the account and accepts only after token preview succeeds', async () => {
    api.postInvitationToken
      .mockResolvedValueOnce({ organization_name: 'Synthetic Org', email: 'new@example.test', roles: ['org_member'], expires_at: '2030-01-01', existing_user: false, mfa_required: false })
      .mockResolvedValueOnce({ status: 'accepted' })
    render(<InvitationAcceptancePage />)
    expect(await screen.findByText(/Synthetic Org/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Create password'), { target: { value: 'long-test-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account and accept invitation' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/membership is active/))
    expect(api.postInvitationToken).toHaveBeenNthCalledWith(2, 'accept', expect.objectContaining({ token: 'opaque-test-token', password: 'long-test-password' }))
  })

  it('removes the bearer token from the address and reports invalid links', async () => {
    window.history.replaceState(null, '', '/invitations/accept')
    render(<InvitationAcceptancePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/missing its secure token/)
    expect(window.location.hash).toBe('')
  })

  it('leaves the form usable after an acceptance backend error', async () => {
    api.postInvitationToken
      .mockResolvedValueOnce({ organization_name: 'Synthetic Org', email: 'new@example.test', roles: ['org_member'], expires_at: '2030-01-01', existing_user: false, mfa_required: false })
      .mockRejectedValueOnce(new Error('Invitation expired'))
    render(<InvitationAcceptancePage />)
    await screen.findByText(/Synthetic Org/)
    fireEvent.change(screen.getByLabelText('Create password'), { target: { value: 'long-test-password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create account and accept invitation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invitation expired')
    expect(screen.getByRole('button', { name: 'Create account and accept invitation' })).toBeEnabled()
  })
})
