import { useState } from 'react'
import type { Team } from '../../teams'
import type { OrgMember } from '../../organizations'
import TeamMemberSelector from './TeamMemberSelector'

// Phase 3 PR3C. One team's name, resolved member emails, and manage
// controls -- "Edit Members" toggles an inline TeamMemberSelector, "Delete"
// follows the same confirm/cancel two-step every other destructive action
// in this app uses (StatusAction, UserStatusAction). No confirmation
// reason field here, unlike those -- team deletion has no status-tracking
// columns to record one against (Team has none, and this PR does not add
// any -- see the implementation report).
interface Props {
  team: Team
  // null when the org's member roster couldn't be loaded (e.g. the
  // caller lacks manage_org, so GET /orgs/{org_id}/members 403'd) --
  // degrades to showing raw user ids instead of emails, and disables the
  // member editor entirely (there is no roster to choose from), while
  // still allowing delete to be attempted (the backend is what actually
  // decides whether that succeeds).
  members: OrgMember[] | null
  onUpdateMembers: (userIds: number[]) => Promise<void>
  onDelete: () => Promise<void>
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: '8px 12px', borderRadius: 8, background: 'var(--red-bg)',
        border: '1px solid var(--red)', color: 'var(--red)', fontSize: 12, marginTop: 8,
      }}
    >
      {msg}
    </div>
  )
}

const secondaryButton: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '5px 10px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
}
const destructiveButton: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, padding: '5px 10px', borderRadius: 6,
  border: '1px solid var(--red)', background: 'transparent', color: 'var(--red)', cursor: 'pointer',
}

export default function TeamRow({ team, members, onUpdateMembers, onDelete }: Props) {
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const memberLabel = (userId: number) => members?.find(m => m.user_id === userId)?.email ?? `User #${userId}`

  const handleDelete = async () => {
    setBusy(true)
    setErr(null)
    try {
      await onDelete()
    } catch (e) {
      setErr(String(e))
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '12px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{team.name}</div>
        <div style={{ display: 'flex', gap: 8 }}>
          {members && (
            <button onClick={() => setEditing(e => !e)} style={secondaryButton}>
              {editing ? 'Done' : 'Edit Members'}
            </button>
          )}
          {!confirmingDelete ? (
            <button onClick={() => setConfirmingDelete(true)} style={destructiveButton}>
              Delete
            </button>
          ) : (
            <>
              <button onClick={handleDelete} disabled={busy} style={destructiveButton}>
                {busy ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button onClick={() => { setConfirmingDelete(false); setErr(null) }} disabled={busy} style={secondaryButton}>
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      {err && <ErrBox msg={err} />}

      <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 4 }}>
        {team.member_user_ids.length
          ? [...team.member_user_ids].map(memberLabel).sort().join(', ')
          : 'No members'}
      </div>

      {editing && members && (
        <div style={{ marginTop: 10 }}>
          <TeamMemberSelector members={members} selectedUserIds={team.member_user_ids} onChange={onUpdateMembers} />
        </div>
      )}
    </div>
  )
}
