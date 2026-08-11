import { useState } from 'react'
import { updateTeam, type Team } from '../../teams'
import type { OrgMember } from '../../organizations'
import TeamMembersPanel from './TeamMembersPanel'

// Team Management v0.8.0 Step 5. One team's name, description, member
// count, and manage controls. "Manage Members" toggles an inline
// TeamMembersPanel (roster + invite/role-change/remove/leave, Step 4's
// per-member endpoints) -- replaces the old "Edit Members" full-replace
// checkbox picker (TeamMemberSelector, removed this change). "Edit"
// toggles an inline rename/description form (PATCH .../teams/{id}, Step
// 1's description column, never exposed in this app until now). "Delete"
// is unchanged from before this change: the same confirm/cancel two-step
// every other destructive action in this app uses (StatusAction,
// UserStatusAction, RevokeAction) -- still no confirmation-reason field,
// team deletion has no status-tracking column to record one against.
//
// Rendered unconditionally regardless of the viewer's guessed
// permission -- omnibioai-auth (require_org_permission_or_platform_admin
// (manage_teams) for rename/delete, app.rbac.require_team_manage_
// permission for the per-member actions inside TeamMembersPanel) is what
// actually decides whether an attempt succeeds; a 403 surfaces inline,
// the same "frontend hiding is not authorization" posture this app
// already established (PR3B/PR3C).
interface Props {
  orgId: number
  team: Team
  // null when the org's member roster couldn't be loaded (e.g. the
  // caller lacks manage_org, so GET /orgs/{org_id}/members 403'd) --
  // TeamMembersPanel degrades to raw user ids and a free-text invite
  // field in that case; every control still renders, the backend is
  // what actually decides whether an attempt succeeds.
  orgMembers: OrgMember[] | null
  onChanged: () => void
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
const fieldStyle: React.CSSProperties = {
  fontSize: 12, padding: '6px 8px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', width: '100%', boxSizing: 'border-box',
}

function EditTeamForm({ team, onSaved, onCancel }: { team: Team; onSaved: (t: Team) => void; onCancel: () => void }) {
  const [name, setName] = useState(team.name)
  const [description, setDescription] = useState(team.description ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    setErr(null)
    try {
      const updated = await updateTeam(team.organization_id, team.id, { name: trimmed, description })
      onSaved(updated)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8, maxWidth: 420 }}>
      <input
        value={name}
        onChange={e => setName(e.target.value)}
        aria-label="Team name"
        style={fieldStyle}
      />
      <textarea
        value={description}
        onChange={e => setDescription(e.target.value)}
        placeholder="Description (optional)"
        aria-label="Team description"
        rows={2}
        style={fieldStyle}
      />
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="submit" disabled={busy || !name.trim()} style={{ ...secondaryButton, opacity: busy || !name.trim() ? 0.6 : 1 }}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel} disabled={busy} style={secondaryButton}>Cancel</button>
      </div>
      {err && <ErrBox msg={err} />}
    </form>
  )
}

export default function TeamRow({ orgId, team, orgMembers, onChanged, onDelete }: Props) {
  const [managingMembers, setManagingMembers] = useState(false)
  const [editing, setEditing] = useState(false)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleDelete = async () => {
    setBusy(true)
    setErr(null)
    try {
      await onDelete()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '12px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{team.name}</div>
          {team.description && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{team.description}</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setEditing(e => !e)} style={secondaryButton}>
            {editing ? 'Done' : 'Edit'}
          </button>
          <button onClick={() => setManagingMembers(m => !m)} style={secondaryButton}>
            {managingMembers ? 'Done' : 'Manage Members'}
          </button>
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
        {team.member_user_ids.length} member{team.member_user_ids.length === 1 ? '' : 's'}
      </div>

      {editing && (
        <EditTeamForm
          team={team}
          onSaved={() => { setEditing(false); onChanged() }}
          onCancel={() => setEditing(false)}
        />
      )}

      {managingMembers && (
        <TeamMembersPanel orgId={orgId} teamId={team.id} orgMembers={orgMembers} onRosterChanged={onChanged} />
      )}
    </div>
  )
}
