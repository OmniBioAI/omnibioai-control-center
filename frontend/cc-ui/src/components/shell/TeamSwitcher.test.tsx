import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TeamSwitcher from './TeamSwitcher'
import * as auth from '../../auth'
import type { SessionUser } from '../../auth'
import * as teamsModule from '../../teams'
import type { Team } from '../../teams'

vi.mock('../../auth', async () => {
  const actual = await vi.importActual<typeof import('../../auth')>('../../auth')
  return { ...actual, switchTeam: vi.fn() }
})

vi.mock('../../teams', async () => {
  const actual = await vi.importActual<typeof import('../../teams')>('../../teams')
  return { ...actual, listTeams: vi.fn() }
})

function makeUser(overrides: Partial<SessionUser> = {}): SessionUser {
  return {
    userId: '3', email: 'user@omnibioai.test', roles: [], permissions: [],
    orgId: '42', orgRoles: [], teamId: null, teamRole: null, schemaVersion: 2,
    ...overrides,
  }
}

const teams: Team[] = [
  { id: 1, organization_id: 42, name: 'Genomics', member_user_ids: [3, 4], description: null, created_by_user_id: null },
  { id: 2, organization_id: 42, name: 'Proteomics', member_user_ids: [3, 5], description: null, created_by_user_id: null },
  { id: 3, organization_id: 42, name: 'Not My Team', member_user_ids: [5, 6], description: null, created_by_user_id: null },
]

describe('TeamSwitcher', () => {
  let reloadSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.mocked(teamsModule.listTeams).mockReset()
    vi.mocked(auth.switchTeam).mockReset()
    vi.mocked(teamsModule.listTeams).mockResolvedValue(teams)
    reloadSpy = vi.fn()
    vi.stubGlobal('location', { ...window.location, reload: reloadSpy })
  })

  it('renders nothing without a session', () => {
    const { container } = render(<TeamSwitcher user={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing without an organization context', () => {
    const { container } = render(<TeamSwitcher user={makeUser({ orgId: null })} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('displays "Personal Workspace" when teamId is null', async () => {
    render(<TeamSwitcher user={makeUser({ teamId: null })} />)
    expect(await screen.findByText('Personal Workspace')).toBeInTheDocument()
  })

  it('displays the active team name when teamId is set', async () => {
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    expect(await screen.findByText('Genomics')).toBeInTheDocument()
  })

  it('lists only teams the current user is actually a member of', async () => {
    const user = userEvent.setup()
    render(<TeamSwitcher user={makeUser()} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))

    expect(await screen.findByText('Genomics')).toBeInTheDocument()
    expect(screen.getByText('Proteomics')).toBeInTheDocument()
    expect(screen.queryByText('Not My Team')).not.toBeInTheDocument()
  })

  it('marks the active team distinctly from other options', async () => {
    const user = userEvent.setup()
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))

    const genomics = await screen.findByRole('menuitemradio', { name: /Genomics/ })
    const proteomics = screen.getByRole('menuitemradio', { name: /Proteomics/ })
    expect(genomics).toHaveAttribute('aria-checked', 'true')
    expect(proteomics).toHaveAttribute('aria-checked', 'false')
  })

  it('selecting another team calls switchTeam with that team id, never a client-controlled header', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockResolvedValue(makeUser({ teamId: '2' }))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))

    expect(auth.switchTeam).toHaveBeenCalledWith(2)
    expect(auth.switchTeam).toHaveBeenCalledTimes(1)
  })

  it('successful switch triggers a page reload (rehydrates every team-scoped view from the new JWT)', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockResolvedValue(makeUser({ teamId: '2' }))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))

    await waitFor(() => expect(reloadSpy).toHaveBeenCalledTimes(1))
  })

  it('Team A -> Team B: selecting a different team switches to it', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockResolvedValue(makeUser({ teamId: '2' }))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))
    expect(auth.switchTeam).toHaveBeenCalledWith(2)
  })

  it('Team -> Personal: selecting Personal Workspace switches with team_id null', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockResolvedValue(makeUser({ teamId: null }))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: 'Personal Workspace' }))
    expect(auth.switchTeam).toHaveBeenCalledWith(null)
  })

  it('Personal -> Team: selecting a team switches from the personal workspace', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockResolvedValue(makeUser({ teamId: '1' }))
    render(<TeamSwitcher user={makeUser({ teamId: null })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Genomics/ }))
    expect(auth.switchTeam).toHaveBeenCalledWith(1)
  })

  it('clicking the already-active team is a no-op (no switchTeam call)', async () => {
    const user = userEvent.setup()
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Genomics/ }))
    expect(auth.switchTeam).not.toHaveBeenCalled()
  })

  it('failed switch shows an error, does not reload, and keeps showing the previous active team', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockRejectedValue(new Error('Unable to switch to that team. Please try again or contact your administrator.'))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to switch to that team')
    expect(reloadSpy).not.toHaveBeenCalled()
    // The top-bar button's own label still reflects the never-actually-
    // changed active team -- switchTeam was mocked to reject, so
    // cachedUser (and this component's own `user` prop, in a real app
    // re-render) never moved off Team A. "Genomics" also appears as a
    // menu item label (the dropdown stays open on failure), so scope
    // the assertion to the toggle button specifically.
    expect(screen.getByRole('button', { name: 'Switch workspace' })).toHaveTextContent('Genomics')
  })

  it('does not expose which org/team boundary caused a 403/404 denial', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockRejectedValue(new Error('Unable to switch to that team. Please try again or contact your administrator.'))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))

    const alertText = (await screen.findByRole('alert')).textContent ?? ''
    expect(alertText.toLowerCase()).not.toContain('organization')
    expect(alertText.toLowerCase()).not.toContain('not a member')
  })

  it('network failure during switch is handled, not reloaded, and reusable (switching re-enabled)', async () => {
    const user = userEvent.setup()
    vi.mocked(auth.switchTeam).mockRejectedValue(new Error('Unable to switch teams right now. Check your connection and try again.'))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    await user.click(await screen.findByRole('menuitemradio', { name: /Proteomics/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/connection/i)
    expect(reloadSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Switch workspace' })).not.toBeDisabled()
  })

  it('prevents duplicate simultaneous switch attempts', async () => {
    const user = userEvent.setup()
    let resolveSwitch: (u: SessionUser) => void = () => {}
    vi.mocked(auth.switchTeam).mockReturnValue(new Promise(resolve => { resolveSwitch = resolve }))
    render(<TeamSwitcher user={makeUser({ teamId: '1' })} />)
    await user.click(screen.getByRole('button', { name: 'Switch workspace' }))
    const proteomicsItem = await screen.findByRole('menuitemradio', { name: /Proteomics/ })
    await user.click(proteomicsItem)

    // The top button is disabled while switching -- a second click while
    // the first request is still in flight cannot fire another one.
    expect(screen.getByRole('button', { name: 'Switch workspace' })).toBeDisabled()
    expect(auth.switchTeam).toHaveBeenCalledTimes(1)

    resolveSwitch(makeUser({ teamId: '2' }))
    await waitFor(() => expect(reloadSpy).toHaveBeenCalledTimes(1))
  })
})
