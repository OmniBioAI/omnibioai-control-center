import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import TeamRow from './TeamRow'
import * as teams from '../../teams'
import type { Team } from '../../teams'

vi.mock('../../teams', async () => {
  const actual = await vi.importActual<typeof import('../../teams')>('../../teams')
  return { ...actual, updateTeam: vi.fn() }
})

// TeamMembersPanel has its own full test coverage (TeamMembersPanel.test.tsx)
// -- stubbed here so these tests only prove TeamRow mounts it with the
// right orgId/teamId/orgMembers when "Manage Members" is toggled, same
// "don't re-prove a child's own behavior" precedent TeamsPage.test.tsx
// already established for TeamsCard.
vi.mock('./TeamMembersPanel', () => ({
  default: ({ orgId, teamId }: { orgId: number; teamId: number }) => (
    <div data-testid="TeamMembersPanel" data-org-id={orgId} data-team-id={teamId} />
  ),
}))

const team: Team = {
  id: 1, organization_id: 42, name: 'Genomics', member_user_ids: [7, 9],
  description: 'Sequencing pipeline owners', created_by_user_id: 7,
}

describe('TeamRow', () => {
  it('renders the team name, description, and member count', () => {
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={vi.fn()} onDelete={vi.fn()} />)

    expect(screen.getByText('Genomics')).toBeInTheDocument()
    expect(screen.getByText('Sequencing pipeline owners')).toBeInTheDocument()
    expect(screen.getByText('2 members')).toBeInTheDocument()
  })

  it('renders no description line for a team that has none', () => {
    render(
      <TeamRow
        orgId={42}
        team={{ ...team, description: null }}
        orgMembers={null}
        onChanged={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    expect(screen.queryByText('Sequencing pipeline owners')).not.toBeInTheDocument()
  })

  it('singularizes the member count for exactly one member', () => {
    render(
      <TeamRow
        orgId={42}
        team={{ ...team, member_user_ids: [7] }}
        orgMembers={null}
        onChanged={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    expect(screen.getByText('1 member')).toBeInTheDocument()
  })

  it('toggles Manage Members, mounting TeamMembersPanel scoped to this org/team', async () => {
    const user = userEvent.setup()
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={vi.fn()} onDelete={vi.fn()} />)

    expect(screen.queryByTestId('TeamMembersPanel')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Manage Members' }))

    const panel = screen.getByTestId('TeamMembersPanel')
    expect(panel).toHaveAttribute('data-org-id', '42')
    expect(panel).toHaveAttribute('data-team-id', '1')

    await user.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByTestId('TeamMembersPanel')).not.toBeInTheDocument()
  })

  it('edits name and description via the Edit form, then calls onChanged', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    vi.mocked(teams.updateTeam).mockResolvedValue({ ...team, name: 'Genomics Core', description: 'Updated' })
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={onChanged} onDelete={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const nameField = screen.getByLabelText('Team name')
    await user.clear(nameField)
    await user.type(nameField, 'Genomics Core')
    const descField = screen.getByLabelText('Team description')
    await user.clear(descField)
    await user.type(descField, 'Updated')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(teams.updateTeam).toHaveBeenCalledWith(42, 1, { name: 'Genomics Core', description: 'Updated' }),
    )
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
  })

  it('shows the backend error inline and keeps the form open when rename fails', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.updateTeam).mockRejectedValue(new Error('/orgs/42/teams/1 403'))
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={vi.fn()} onDelete={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
    expect(screen.getByLabelText('Team name')).toBeInTheDocument()
  })

  it('deletes only after two-step confirmation', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn().mockResolvedValue(undefined)
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={vi.fn()} onDelete={onDelete} />)

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onDelete).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(onDelete).toHaveBeenCalled())
  })

  it('shows an inline error when delete fails, without calling onChanged', async () => {
    const user = userEvent.setup()
    const onDelete = vi.fn().mockRejectedValue(new Error('/orgs/42/teams/1 403'))
    render(<TeamRow orgId={42} team={team} orgMembers={null} onChanged={vi.fn()} onDelete={onDelete} />)

    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
  })
})
