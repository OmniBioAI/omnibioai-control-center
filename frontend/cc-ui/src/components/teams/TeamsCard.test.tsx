import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TeamsCard from './TeamsCard'
import * as teams from '../../teams'
import type { Team } from '../../teams'
import * as organizations from '../../organizations'

vi.mock('../../teams', async () => {
  const actual = await vi.importActual<typeof import('../../teams')>('../../teams')
  return { ...actual, listTeams: vi.fn(), createTeam: vi.fn(), deleteTeam: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchOrgMembers: vi.fn() }
})

// TeamRow has its own full test coverage (TeamRow.test.tsx) -- stubbed
// here so TeamsCard's own tests only prove the list/create wiring, not
// TeamRow's internal rename/manage-members/delete behavior.
vi.mock('./TeamRow', () => ({
  default: ({ team }: { team: Team }) => <div data-testid="TeamRow">{team.name}</div>,
}))

const existingTeams: Team[] = [
  { id: 1, organization_id: 42, name: 'Genomics', member_user_ids: [7], description: null, created_by_user_id: 7 },
]

describe('TeamsCard', () => {
  beforeEach(() => {
    vi.mocked(teams.listTeams).mockReset()
    vi.mocked(teams.createTeam).mockReset()
    vi.mocked(teams.deleteTeam).mockReset()
    vi.mocked(organizations.fetchOrgMembers).mockReset()
    vi.mocked(organizations.fetchOrgMembers).mockRejectedValue(new Error('/orgs/42/members 403'))
  })

  it('renders one TeamRow per team', async () => {
    vi.mocked(teams.listTeams).mockResolvedValue(existingTeams)
    render(<TeamsCard orgId={42} />)

    expect(await screen.findByText('Genomics')).toBeInTheDocument()
  })

  it('shows "No teams yet." for an empty list', async () => {
    vi.mocked(teams.listTeams).mockResolvedValue([])
    render(<TeamsCard orgId={42} />)

    expect(await screen.findByText('No teams yet.')).toBeInTheDocument()
  })

  it('hides entirely when the teams fetch itself is forbidden (true non-member)', async () => {
    vi.mocked(teams.listTeams).mockRejectedValue(new Error('/orgs/42/teams 403'))
    const { container } = render(<TeamsCard orgId={42} />)

    await waitFor(() => expect(teams.listTeams).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('creates a team with a name and description, then refreshes the list', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.listTeams).mockResolvedValue([])
    vi.mocked(teams.createTeam).mockResolvedValue({
      id: 2, organization_id: 42, name: 'Proteomics', member_user_ids: [], description: 'New team', created_by_user_id: 7,
    })
    render(<TeamsCard orgId={42} />)
    await screen.findByText('No teams yet.')

    await user.type(screen.getByLabelText('New team name'), 'Proteomics')
    await user.type(screen.getByLabelText('New team description'), 'New team')
    await user.click(screen.getByRole('button', { name: 'Create Team' }))

    await waitFor(() =>
      expect(teams.createTeam).toHaveBeenCalledWith(42, { name: 'Proteomics', description: 'New team' }),
    )
    await waitFor(() => expect(teams.listTeams).toHaveBeenCalledTimes(2))
  })

  it('omits description from the create payload when left blank', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.listTeams).mockResolvedValue([])
    vi.mocked(teams.createTeam).mockResolvedValue({
      id: 2, organization_id: 42, name: 'Proteomics', member_user_ids: [], description: null, created_by_user_id: 7,
    })
    render(<TeamsCard orgId={42} />)
    await screen.findByText('No teams yet.')

    await user.type(screen.getByLabelText('New team name'), 'Proteomics')
    await user.click(screen.getByRole('button', { name: 'Create Team' }))

    await waitFor(() => expect(teams.createTeam).toHaveBeenCalledWith(42, { name: 'Proteomics', description: undefined }))
  })

  it('shows a create error inline without clearing the typed name', async () => {
    const user = userEvent.setup()
    vi.mocked(teams.listTeams).mockResolvedValue([])
    vi.mocked(teams.createTeam).mockRejectedValue(new Error('/orgs/42/teams 500'))
    render(<TeamsCard orgId={42} />)
    await screen.findByText('No teams yet.')

    await user.type(screen.getByLabelText('New team name'), 'Proteomics')
    await user.click(screen.getByRole('button', { name: 'Create Team' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('500')
    expect(screen.getByLabelText('New team name')).toHaveValue('Proteomics')
  })
})
