import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import RoleSelector from './RoleSelector'
import type { RoleSummary } from '../../roles'

const allRoles: RoleSummary[] = [
  { id: 1, name: 'org_admin', description: 'Full control of the organization', permissions: ['manage_org'] },
  { id: 2, name: 'org_member', description: null, permissions: [] },
]

describe('RoleSelector', () => {
  it('renders one checkbox per role, checked to reflect current assignment', () => {
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={['org_admin']} onAssign={vi.fn()} onRemove={vi.fn()} />
    )
    expect(screen.getByRole('checkbox', { name: /^org_admin\b/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /^org_member\b/ })).not.toBeChecked()
  })

  it('shows a role description next to its name when present', () => {
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={[]} onAssign={vi.fn()} onRemove={vi.fn()} />
    )
    expect(screen.getByText('Full control of the organization')).toBeInTheDocument()
  })

  it('calls onAssign with the role name when an unchecked box is checked', async () => {
    const user = userEvent.setup()
    const onAssign = vi.fn().mockResolvedValue(undefined)
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={[]} onAssign={onAssign} onRemove={vi.fn()} />
    )
    await user.click(screen.getByRole('checkbox', { name: /^org_member\b/ }))
    expect(onAssign).toHaveBeenCalledWith('org_member')
  })

  it('calls onRemove with the role name and id when a checked box is unchecked', async () => {
    const user = userEvent.setup()
    const onRemove = vi.fn().mockResolvedValue(undefined)
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={['org_admin']} onAssign={vi.fn()} onRemove={onRemove} />
    )
    await user.click(screen.getByRole('checkbox', { name: /^org_admin\b/ }))
    expect(onRemove).toHaveBeenCalledWith('org_admin', 1)
  })

  it('shows an inline alert and leaves the checkbox usable again when the call fails', async () => {
    const user = userEvent.setup()
    const onAssign = vi.fn().mockRejectedValue(new Error('/orgs/1/members/2/roles 403'))
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={[]} onAssign={onAssign} onRemove={vi.fn()} />
    )
    const checkbox = screen.getByRole('checkbox', { name: /^org_member\b/ })
    await user.click(checkbox)

    expect(await screen.findByRole('alert')).toHaveTextContent('403')
    await waitFor(() => expect(checkbox).not.toBeDisabled())
  })

  it('disables every checkbox while a change is in flight, and re-enables after', async () => {
    const user = userEvent.setup()
    let resolveAssign: () => void = () => {}
    const onAssign = vi.fn(() => new Promise<void>(resolve => { resolveAssign = resolve }))
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={[]} onAssign={onAssign} onRemove={vi.fn()} />
    )
    const memberCheckbox = screen.getByRole('checkbox', { name: /^org_member\b/ })
    await user.click(memberCheckbox)

    expect(memberCheckbox).toBeDisabled()
    resolveAssign()
    await waitFor(() => expect(memberCheckbox).not.toBeDisabled())
  })

  it('disables every checkbox when the disabled prop is set, without calling onAssign/onRemove', async () => {
    const user = userEvent.setup()
    const onAssign = vi.fn()
    render(
      <RoleSelector allRoles={allRoles} assignedRoleNames={[]} onAssign={onAssign} onRemove={vi.fn()} disabled />
    )
    const checkbox = screen.getByRole('checkbox', { name: /^org_member\b/ })
    expect(checkbox).toBeDisabled()
    await user.click(checkbox).catch(() => {})
    expect(onAssign).not.toHaveBeenCalled()
  })
})
