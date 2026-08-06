import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import PermissionSelector from './PermissionSelector'
import type { PermissionDescriptor } from '../../serviceAccounts'

const perm = (name: string, description = ''): PermissionDescriptor => ({
  name, resource: name.split('.')[0], action: name.split('.')[1] ?? 'manage',
  scope: 'both', category: 'workflow', description, legacy: false, deprecated: false, deprecated_reason: null,
})

const allPermissions: PermissionDescriptor[] = [
  perm('dataset.read', 'Read datasets'),
  perm('workflow.execute', 'Execute workflows'),
]

describe('PermissionSelector', () => {
  it('renders one checkbox per permission, checked to reflect the current selection', () => {
    render(
      <PermissionSelector allPermissions={allPermissions} selectedPermissionNames={['dataset.read']} onChange={vi.fn()} />
    )
    expect(screen.getByRole('checkbox', { name: /dataset\.read/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /workflow\.execute/ })).not.toBeChecked()
  })

  it('shows each permission\'s description when present', () => {
    render(
      <PermissionSelector allPermissions={allPermissions} selectedPermissionNames={[]} onChange={vi.fn()} />
    )
    expect(screen.getByText('Read datasets')).toBeInTheDocument()
  })

  it('calls onChange with the permission added when an unchecked box is checked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <PermissionSelector allPermissions={allPermissions} selectedPermissionNames={['dataset.read']} onChange={onChange} />
    )
    await user.click(screen.getByRole('checkbox', { name: /workflow\.execute/ }))
    expect(onChange).toHaveBeenCalledWith(['dataset.read', 'workflow.execute'])
  })

  it('calls onChange with the permission removed when a checked box is unchecked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <PermissionSelector allPermissions={allPermissions} selectedPermissionNames={['dataset.read', 'workflow.execute']} onChange={onChange} />
    )
    await user.click(screen.getByRole('checkbox', { name: /dataset\.read/ }))
    expect(onChange).toHaveBeenCalledWith(['workflow.execute'])
  })

  it('disables every checkbox when the disabled prop is set, without calling onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <PermissionSelector allPermissions={allPermissions} selectedPermissionNames={[]} onChange={onChange} disabled />
    )
    const checkbox = screen.getByRole('checkbox', { name: /dataset\.read/ })
    expect(checkbox).toBeDisabled()
    await user.click(checkbox).catch(() => {})
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows a fallback message when there are no permissions to offer', () => {
    render(
      <PermissionSelector allPermissions={[]} selectedPermissionNames={[]} onChange={vi.fn()} />
    )
    expect(screen.getByText('No permissions available to grant.')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
