import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TeamMembersPanel from './TeamMembersPanel'
import * as teams from '../../teams'
import type { TeamMember } from '../../teams'
import * as auth from '../../auth'
import type { OrgMember } from '../../organizations'

vi.mock('../../teams', async () => {
  const actual = await vi.importActual<typeof import('../../teams')>('../../teams')
  return {
    ...actual,
    fetchTeamMembers: vi.fn(),
    inviteTeamMember: vi.fn(),
    updateTeamMemberRole: vi.fn(),
    removeTeamMember: vi.fn(),
    leaveTeam: vi.fn(),
  }
})

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, getSessionUser: vi.fn() }
})

const orgMembers: OrgMember[] = [
  { user_id: 3, email: 'alice@acme.test', status: 'active', roles: ['org_admin'] },
  { user_id: 4, email: 'bob@acme.test', status: 'active', roles: ['org_member'] },
  { user_id: 5, email: 'carol@acme.test', status: 'active', roles: ['org_member'] },
]

const roster: TeamMember[] = [
  { user_id: 3, role: 'admin', invited_by_user_id: null, joined_at: '2026-08-01T10:00:00' },
  { user_id: 4, role: 'member', invited_by_user_id: 3, joined_at: '2026-08-02T10:00:00' },
]

function sessionAs(userId: number | null) {
  vi.mocked(auth.getSessionUser).mockReturnValue(
    userId == null ? null : {
      userId: String(userId), email: 'x@acme.test', roles: [], permissions: [],
      orgId: '42', orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
    },
  )
}

describe('TeamMembersPanel', () => {
  beforeEach(() => {
    vi.mocked(teams.fetchTeamMembers).mockReset()
    vi.mocked(teams.inviteTeamMember).mockReset()
    vi.mocked(teams.updateTeamMemberRole).mockReset()
    vi.mocked(teams.removeTeamMember).mockReset()
    vi.mocked(teams.leaveTeam).mockReset()
    sessionAs(9) // a viewer not on the roster, by default
  })

  it('loads and renders the roster with resolved emails, roles, and joined dates', async () => {
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)

    expect(await screen.findByText('alice@acme.test', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('bob@acme.test', { exact: false })).toBeInTheDocument()
    expect(screen.getByLabelText('Role for alice@acme.test')).toHaveValue('admin')
    expect(screen.getByLabelText('Role for bob@acme.test')).toHaveValue('member')
    expect(teams.fetchTeamMembers).toHaveBeenCalledWith(42, 1)
  })

  it('falls back to raw user ids when the org roster is unavailable', async () => {
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={null} onRosterChanged={vi.fn()} />)

    expect(await screen.findByText('User #3', { exact: false })).toBeInTheDocument()
    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
  })

  it('shows a generic "no longer available" message on 404, never a permission-denied message', async () => {
    vi.mocked(teams.fetchTeamMembers).mockRejectedValue(new Error('/orgs/42/teams/1/members 404'))
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)

    expect(await screen.findByText('This team is no longer available.')).toBeInTheDocument()
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/organization/i)).not.toBeInTheDocument()
  })

  it('shows an inline error, not the 404 fallback, for a non-404 roster load failure', async () => {
    vi.mocked(teams.fetchTeamMembers).mockRejectedValue(new Error('/orgs/42/teams/1/members 500'))
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('500')
    expect(screen.queryByText('This team is no longer available.')).not.toBeInTheDocument()
  })

  it('invites an eligible org member (excluded from the picker once already on the roster) and refreshes', async () => {
    const user = userEvent.setup()
    const onRosterChanged = vi.fn()
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.inviteTeamMember).mockResolvedValue({ user_id: 5, role: 'member', invited_by_user_id: 3, joined_at: '2026-08-03T10:00:00' })
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={onRosterChanged} />)
    await screen.findByText('alice@acme.test', { exact: false })

    const picker = screen.getByLabelText('Member to invite')
    // alice/bob are already on the roster -- only carol should be offered.
    expect(screen.queryByRole('option', { name: 'alice@acme.test' })).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'carol@acme.test' })).toBeInTheDocument()

    await user.selectOptions(picker, 'carol@acme.test')
    await user.click(screen.getByRole('button', { name: 'Invite' }))

    await waitFor(() => expect(teams.inviteTeamMember).toHaveBeenCalledWith(42, 1, { email: 'carol@acme.test', role: 'member' }))
    await waitFor(() => expect(onRosterChanged).toHaveBeenCalled())
    expect(await screen.findByText('Invited.')).toBeInTheDocument()
  })

  it('shows the backend detail message inline when an invite is rejected', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.inviteTeamMember).mockRejectedValue(new Error('User is not a member of this organization: carol@acme.test'))
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)
    await screen.findByText('alice@acme.test', { exact: false })

    await user.selectOptions(screen.getByLabelText('Member to invite'), 'carol@acme.test')
    await user.click(screen.getByRole('button', { name: 'Invite' }))

    expect(await screen.findByText('User is not a member of this organization: carol@acme.test')).toBeInTheDocument()
  })

  it('changes a member role via its select and refreshes', async () => {
    const user = userEvent.setup()
    const onRosterChanged = vi.fn()
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.updateTeamMemberRole).mockResolvedValue({ ...roster[1], role: 'admin' })
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={onRosterChanged} />)
    await screen.findByText('bob@acme.test', { exact: false })

    await user.selectOptions(screen.getByLabelText('Role for bob@acme.test'), 'admin')

    await waitFor(() => expect(teams.updateTeamMemberRole).toHaveBeenCalledWith(42, 1, 4, 'admin'))
    await waitFor(() => expect(onRosterChanged).toHaveBeenCalled())
  })

  it('shows a 403 inline for a denied role change, without hiding the row', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.updateTeamMemberRole).mockRejectedValue(new Error('/orgs/42/teams/1/members/4/role 403'))
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)
    await screen.findByText('bob@acme.test', { exact: false })

    await user.selectOptions(screen.getByLabelText('Role for bob@acme.test'), 'admin')

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
    expect(screen.getByText('bob@acme.test', { exact: false })).toBeInTheDocument()
  })

  it('removes a member after two-step confirmation, not before', async () => {
    const user = userEvent.setup()
    const onRosterChanged = vi.fn()
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.removeTeamMember).mockResolvedValue(undefined)
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={onRosterChanged} />)
    await screen.findByText('bob@acme.test', { exact: false })

    await user.click(screen.getByRole('button', { name: 'Remove bob@acme.test' }))
    expect(teams.removeTeamMember).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm remove bob@acme.test' }))
    await waitFor(() => expect(teams.removeTeamMember).toHaveBeenCalledWith(42, 1, 4))
    await waitFor(() => expect(onRosterChanged).toHaveBeenCalled())
  })

  it('offers Leave (not Remove) for the current viewer\'s own row, and calls the leave endpoint', async () => {
    const user = userEvent.setup()
    const onRosterChanged = vi.fn()
    sessionAs(4) // bob is the current viewer
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.leaveTeam).mockResolvedValue(undefined)
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={onRosterChanged} />)
    await screen.findByText('bob@acme.test', { exact: false })

    expect(screen.queryByRole('button', { name: 'Remove bob@acme.test' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Leave' }))
    await user.click(screen.getByRole('button', { name: 'Confirm leave' }))

    await waitFor(() => expect(teams.leaveTeam).toHaveBeenCalledWith(42, 1))
    await waitFor(() => expect(onRosterChanged).toHaveBeenCalled())
  })

  it('surfaces a backend-refused leave (e.g. last admin) inline instead of silently removing the row', async () => {
    const user = userEvent.setup()
    sessionAs(3) // alice, the team's only admin in this fixture
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue(roster)
    vi.mocked(teams.leaveTeam).mockRejectedValue(new Error('The last team admin cannot leave -- transfer ownership or delete the team instead'))
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)
    await screen.findByText('alice@acme.test', { exact: false })

    await user.click(screen.getByRole('button', { name: 'Leave' }))
    await user.click(screen.getByRole('button', { name: 'Confirm leave' }))

    expect(await screen.findByText(/last team admin cannot leave/)).toBeInTheDocument()
  })

  it('shows "No members yet." for an empty roster', async () => {
    vi.mocked(teams.fetchTeamMembers).mockResolvedValue([])
    render(<TeamMembersPanel orgId={42} teamId={1} orgMembers={orgMembers} onRosterChanged={vi.fn()} />)

    expect(await screen.findByText('No members yet.')).toBeInTheDocument()
  })
})
