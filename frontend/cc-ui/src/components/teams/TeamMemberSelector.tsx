import { useState } from 'react'
import type { OrgMember } from '../../organizations'

// Phase 3 PR3C. Same interaction shape as components/roles/RoleSelector.tsx
// (checkbox-per-item, immediate apply, per-item busy/error state) but for
// team membership instead of role assignment -- there is no per-item
// add/remove endpoint for teams (only PUT .../teams/{id}/members,
// full-replace), so each toggle here computes the new full member list and
// calls onChange with it, rather than an onAssign/onRemove pair. No
// permission dimension exists for team membership at all (Team carries no
// roles/permissions -- see this PR's implementation report's security
// review), so unlike RoleSelector there is nothing to self-escalate.
interface Props {
  members: OrgMember[]
  selectedUserIds: number[]
  onChange: (userIds: number[]) => Promise<void>
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

export default function TeamMemberSelector({ members, selectedUserIds, onChange, disabled }: Props) {
  const [busyUserId, setBusyUserId] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const toggle = async (userId: number, checked: boolean) => {
    setBusyUserId(userId)
    setErr(null)
    const next = checked
      ? [...selectedUserIds, userId]
      : selectedUserIds.filter(id => id !== userId)
    try {
      await onChange(next)
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyUserId(null)
    }
  }

  if (!members.length) {
    return <div style={{ fontSize: 12, color: 'var(--muted)' }}>No organization members to add.</div>
  }

  return (
    <div>
      {err && <ErrBox msg={err} />}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {members.map(m => {
          const checked = selectedUserIds.includes(m.user_id)
          const busy = busyUserId === m.user_id
          return (
            <label
              key={m.user_id}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                color: 'var(--text2)', cursor: disabled || busy ? 'default' : 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={disabled || busy}
                onChange={e => toggle(m.user_id, e.target.checked)}
              />
              <span>{m.email}</span>
              {busy && <span style={{ fontSize: 10, color: 'var(--muted)' }}>Applying…</span>}
            </label>
          )
        })}
      </div>
    </div>
  )
}
