import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const organizations = vi.hoisted(() => ({ fetchOrgInvitations: vi.fn(), createOrgInvitation: vi.fn(), revokeOrgInvitation: vi.fn() }))
const roles = vi.hoisted(() => ({ fetchOrgRoles: vi.fn() }))
vi.mock('../../organizations', () => organizations)
vi.mock('../../roles', () => roles)
import OrganizationInvitationsCard from './OrganizationInvitationsCard'

describe('OrganizationInvitationsCard', () => {
  beforeEach(() => {
    organizations.fetchOrgInvitations.mockReset().mockResolvedValue([])
    organizations.createOrgInvitation.mockReset().mockResolvedValue({})
    organizations.revokeOrgInvitation.mockReset().mockResolvedValue(undefined)
    roles.fetchOrgRoles.mockReset().mockResolvedValue([{ id: 1, name: 'org_member', description: 'Member', permissions: [] }])
    window.history.replaceState(null, '', '/organizations/42?inviteEmail=synthetic%40example.test')
  })

  it('prepopulates the missing license identity and creates a scoped invitation', async () => {
    render(<OrganizationInvitationsCard orgId={42} />)
    expect(await screen.findByLabelText('Invitee email')).toHaveValue('synthetic@example.test')
    expect(window.location.search).toBe('')
    fireEvent.click(screen.getByRole('button', { name: 'Invite User' }))
    await waitFor(() => expect(organizations.createOrgInvitation).toHaveBeenCalledWith(42, 'synthetic@example.test', ['org_member']))
    expect(await screen.findByRole('status')).toHaveTextContent(/must accept it before membership/)
  })

  it('recovers from a delivery error and always re-enables the invite action', async () => {
    organizations.createOrgInvitation.mockRejectedValueOnce(new Error('Invitation delivery failed'))
    render(<OrganizationInvitationsCard orgId={42} />)
    await screen.findByLabelText('Invitee email')
    fireEvent.change(screen.getByLabelText('Invitee email'), { target: { value: 'target@example.test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Invite User' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invitation delivery failed')
    expect(screen.getByRole('button', { name: 'Invite User' })).toBeEnabled()
  })
})
