import type { PermissionDescriptor } from '../../serviceAccounts'

// PR13. Sibling to RoleSelector.tsx, same "makes no authorization decision
// of its own" contract -- it's rendered by its callers only when they
// judge the viewer plausibly authorized, and the backend independently
// re-checks and rejects (400/403) regardless of what this component
// offers. Deliberately a different shape than RoleSelector though: a
// role's permission set is edited as one batch on save (one PUT), not
// per-checkbox like role *assignment* is (which has real per-item
// POST/DELETE endpoints) -- so this has a single onChange over the whole
// selected set, not per-item onAssign/onRemove callbacks.
interface Props {
  allPermissions: PermissionDescriptor[]
  selectedPermissionNames: string[]
  onChange: (names: string[]) => void
  disabled?: boolean
}

const permissionPill: React.CSSProperties = {
  fontSize: 11, fontFamily: 'monospace', color: 'var(--text2)',
}

export default function PermissionSelector({ allPermissions, selectedPermissionNames, onChange, disabled }: Props) {
  const toggle = (name: string, checked: boolean) => {
    onChange(
      checked
        ? [...selectedPermissionNames, name]
        : selectedPermissionNames.filter(n => n !== name),
    )
  }

  if (allPermissions.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--muted)' }}>No permissions available to grant.</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
      {allPermissions.map(perm => {
        const checked = selectedPermissionNames.includes(perm.name)
        return (
          <label
            key={perm.name}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12,
              color: 'var(--text2)', cursor: disabled ? 'default' : 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={disabled}
              onChange={e => toggle(perm.name, e.target.checked)}
              style={{ marginTop: 2 }}
            />
            <span>
              <span style={permissionPill}>{perm.name}</span>
              {perm.description && (
                <span style={{ display: 'block', fontSize: 11, color: 'var(--muted)' }}>{perm.description}</span>
              )}
            </span>
          </label>
        )
      })}
    </div>
  )
}
