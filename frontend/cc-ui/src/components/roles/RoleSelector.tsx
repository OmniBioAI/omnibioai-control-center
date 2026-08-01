import { useState } from 'react'
import type { RoleSummary } from '../../roles'
import RoleBadge from './RoleBadge'

// Phase 3 PR3B. The interactive "add role / remove role" editor, shared by
// UserDetailPage's Global Roles section and OrganizationDetailPage's
// Members & Roles section -- one checkbox per role in the catalog, checked
// state reflecting whether the target already holds it. Checking a box
// calls onAssign; unchecking calls onRemove. This component makes no
// authorization decision of its own: it is rendered by its callers only
// when they judge the viewer plausibly authorized (platform admin /
// org_admin), and the backend independently re-checks and rejects
// (403/400) regardless of what this component tried to call -- see this
// PR's implementation report, "Frontend hiding is NOT authorization."
interface Props {
  allRoles: RoleSummary[]
  assignedRoleNames: string[]
  onAssign: (roleName: string) => Promise<void>
  onRemove: (roleName: string, roleId: number) => Promise<void>
  disabled?: boolean
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: '8px 12px', borderRadius: 8, background: 'var(--red-bg)',
        border: '1px solid var(--red)', color: 'var(--red)', fontSize: 12, marginBottom: 8,
      }}
    >
      {msg}
    </div>
  )
}

export default function RoleSelector({ allRoles, assignedRoleNames, onAssign, onRemove, disabled }: Props) {
  const [busyRole, setBusyRole] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const toggle = async (role: RoleSummary, checked: boolean) => {
    setBusyRole(role.name)
    setErr(null)
    try {
      if (checked) {
        await onAssign(role.name)
      } else {
        await onRemove(role.name, role.id)
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyRole(null)
    }
  }

  return (
    <div>
      {err && <ErrBox msg={err} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {allRoles.map(role => {
          const checked = assignedRoleNames.includes(role.name)
          const busy = busyRole === role.name
          return (
            <label
              key={role.id}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                color: 'var(--text2)', cursor: disabled || busy ? 'default' : 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled || busy}
                onChange={e => toggle(role, e.target.checked)}
              />
              <RoleBadge name={role.name} />
              {role.description && (
                <span style={{ fontSize: 11, color: 'var(--muted)' }}>{role.description}</span>
              )}
              {busy && <span style={{ fontSize: 10, color: 'var(--muted)' }}>Applying…</span>}
            </label>
          )
        })}
      </div>
    </div>
  )
}
