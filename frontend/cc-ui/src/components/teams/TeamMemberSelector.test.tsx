import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import TeamMemberSelector from './TeamMemberSelector'
import type { OrgMember } from '../../organizations'

const members: OrgMember[] = [
  { user_id: 3, email: 'alice@acme.test', status: 'active', roles: ['org_admin'] },
  { user_id: 4, email: 'bob@acme.test', status: 'active', roles: ['org_member'] },
]

describe('TeamMemberSelector', () => {
  it('renders one checkbox per org member, checked to reflect current team membership', () => {
    render(
      <TeamMemberSelector members={members} selectedUserIds={[3]} onChange={vi.fn()} />
    )
    expect(screen.getByRole('checkbox', { name: 'alice@acme.test' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'bob@acme.test' })).not.toBeChecked()
  })

  it('calls onChange with the full new member list when a box is checked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn().mockResolvedValue(undefined)
    render(
      <TeamMemberSelector members={members} selectedUserIds={[3]} onChange={onChange} />
    )
    await user.click(screen.getByRole('checkbox', { name: 'bob@acme.test' }))
    expect(onChange).toHaveBeenCalledWith([3, 4])
  })

  it('calls onChange with the member removed when a box is unchecked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn().mockResolvedValue(undefined)
    render(
      <TeamMemberSelector members={members} selectedUserIds={[3, 4]} onChange={onChange} />
    )
    await user.click(screen.getByRole('checkbox', { name: 'alice@acme.test' }))
    expect(onChange).toHaveBeenCalledWith([4])
  })

  it('shows an inline alert and leaves the checkbox usable again when the call fails', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn().mockRejectedValue(new Error('/orgs/1/teams/1/members 403'))
    render(
      <TeamMemberSelector members={members} selectedUserIds={[3]} onChange={onChange} />
    )
    const checkbox = screen.getByRole('checkbox', { name: 'bob@acme.test' })
    await user.click(checkbox)

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
    await waitFor(() => expect(checkbox).not.toBeDisabled())
  })

  it('disables only the toggled checkbox while its change is in flight', async () => {
    const user = userEvent.setup()
    let resolveChange: () => void = () => {}
    const onChange = vi.fn(() => new Promise<void>(resolve => { resolveChange = resolve }))
    render(
      <TeamMemberSelector members={members} selectedUserIds={[3]} onChange={onChange} />
    )
    const bobCheckbox = screen.getByRole('checkbox', { name: 'bob@acme.test' })
    const aliceCheckbox = screen.getByRole('checkbox', { name: 'alice@acme.test' })
    await user.click(bobCheckbox)

    expect(bobCheckbox).toBeDisabled()
    expect(aliceCheckbox).not.toBeDisabled()
    resolveChange()
    await waitFor(() => expect(bobCheckbox).not.toBeDisabled())
  })

  it('shows a message instead of checkboxes when there are no organization members', () => {
    render(<TeamMemberSelector members={[]} selectedUserIds={[]} onChange={vi.fn()} />)
    expect(screen.getByText('No organization members to add.')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
