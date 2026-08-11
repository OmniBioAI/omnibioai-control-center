import { useEffect, useState } from 'react'
import {
  fetchTeamMembers, inviteTeamMember, updateTeamMemberRole, removeTeamMember, leaveTeam,
  TEAM_ROLES, type TeamMember,
} from '../../teams'
import type { OrgMember } from '../../organizations'
import { getSessionUser } from '../../auth'
import { classifyAuthError } from '../../format'

// Team Management v0.8.0 Step 5. Replaces TeamMemberSelector.tsx (the old
// full-replace checkbox picker) -- there is no longer a single "the
// membership list" to toggle; this fetches and owns a team's own roster
// (role/invited_by/joined_at per member, from GET .../members, Steps 1-3)
// and drives it with the per-member endpoints Step 4 authorized: invite,
// role change, remove, and self-service leave. Every mutation here re-
// fetches this panel's own roster afterward, and also calls
// onRosterChanged so the parent TeamRow/TeamsCard can refresh its own
// listTeams()-derived member count -- the same "refresh after mutate"
// convention TeamsCard's create/delete already use.
//
// `orgMembers` is the org's member roster (OrgMember[], email-bearing),
// passed down for two things: resolving a roster row's user_id to an
// email (same client-side resolution the old model used), and building
// the invite candidate list (the backend requires an invitee already be
// an org member -- team_service.invite_to_team -- so offering only
// eligible org members avoids ever hitting that 400 in normal use). Null
// when the org roster itself couldn't be loaded (no manage_org) --
// degrades to raw user ids and a free-text email invite field, same
// "frontend hiding is not authorization, backend decides" posture
// TeamRow's own delete button already documents.
interface Props {
  orgId: number
  teamId: number
  orgMembers: OrgMember[] | null
  onRosterChanged: () => void
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
const selectStyle: React.CSSProperties = {
  fontSize: 11, padding: '4px 6px', borderRadius: 6,
  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
}

function formatJoined(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

function RemoveMemberAction({ label, onConfirm }: { label: string; onConfirm: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleConfirm = async () => {
    setBusy(true)
    setErr(null)
    try {
      await onConfirm()
      // On success this row disappears (roster refetch), so there is no
      // "reset confirming" step to do -- the component unmounts.
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <span>
      {!confirming ? (
        <button onClick={() => setConfirming(true)} aria-label={`Remove ${label}`} style={destructiveButton}>Remove</button>
      ) : (
        <span style={{ display: 'inline-flex', gap: 6 }}>
          <button onClick={handleConfirm} disabled={busy} aria-label={`Confirm remove ${label}`} style={destructiveButton}>
            {busy ? 'Removing…' : 'Confirm'}
          </button>
          <button onClick={() => { setConfirming(false); setErr(null) }} disabled={busy} style={secondaryButton}>
            Cancel
          </button>
        </span>
      )}
      {err && <ErrBox msg={err} />}
    </span>
  )
}

function MemberRow({
  member, label, canLeave, onRoleChange, onRemove, onLeave,
}: {
  member: TeamMember
  label: string
  canLeave: boolean
  onRoleChange: (role: string) => Promise<void>
  onRemove: () => Promise<void>
  onLeave: () => Promise<void>
}) {
  const [roleBusy, setRoleBusy] = useState(false)
  const [roleErr, setRoleErr] = useState<string | null>(null)
  const [confirmingLeave, setConfirmingLeave] = useState(false)
  const [leaveBusy, setLeaveBusy] = useState(false)
  const [leaveErr, setLeaveErr] = useState<string | null>(null)

  const handleRoleChange = async (role: string) => {
    setRoleBusy(true)
    setRoleErr(null)
    try {
      await onRoleChange(role)
    } catch (e) {
      setRoleErr(e instanceof Error ? e.message : String(e))
    } finally {
      setRoleBusy(false)
    }
  }

  const handleLeave = async () => {
    setLeaveBusy(true)
    setLeaveErr(null)
    try {
      await onLeave()
    } catch (e) {
      setLeaveErr(e instanceof Error ? e.message : String(e))
      setLeaveBusy(false)
    }
  }

  return (
    <div style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12, color: 'var(--text2)' }}>
          {label}
          <span style={{ color: 'var(--muted)', marginLeft: 8 }}>Joined {formatJoined(member.joined_at)}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <select
            aria-label={`Role for ${label}`}
            value={member.role}
            disabled={roleBusy}
            onChange={e => handleRoleChange(e.target.value)}
            style={selectStyle}
          >
            {TEAM_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
          {canLeave ? (
            !confirmingLeave ? (
              <button onClick={() => setConfirmingLeave(true)} style={secondaryButton}>Leave</button>
            ) : (
              <span style={{ display: 'inline-flex', gap: 6 }}>
                <button onClick={handleLeave} disabled={leaveBusy} style={destructiveButton}>
                  {leaveBusy ? 'Leaving…' : 'Confirm leave'}
                </button>
                <button onClick={() => { setConfirmingLeave(false); setLeaveErr(null) }} disabled={leaveBusy} style={secondaryButton}>
                  Cancel
                </button>
              </span>
            )
          ) : (
            <RemoveMemberAction label={label} onConfirm={onRemove} />
          )}
        </div>
      </div>
      {roleErr && <ErrBox msg={roleErr} />}
      {leaveErr && <ErrBox msg={leaveErr} />}
    </div>
  )
}

export default function TeamMembersPanel({ orgId, teamId, orgMembers, onRosterChanged }: Props) {
  const [members, setMembers] = useState<TeamMember[] | null>(null)
  // Distinguishes "no longer reachable" (404 -- team deleted since the
  // list was loaded, or any other case that must not be explained
  // further) from an ordinary transient error, so this panel never
  // renders "you don't have access to this team" for a resource whose
  // very existence-to-this-caller is exactly what a 404 here is
  // deliberately not confirming -- same anti-enumeration posture PR #41
  // (require_team_manage_permission) enforces server-side.
  const [gone, setGone] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<string>('member')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [inviteErr, setInviteErr] = useState<string | null>(null)
  const [inviteOk, setInviteOk] = useState(false)

  const currentUserId = (() => {
    const raw = getSessionUser()?.userId
    const n = raw != null ? Number(raw) : NaN
    return Number.isFinite(n) ? n : null
  })()

  const load = () => {
    setMembers(null)
    setGone(false)
    setErr(null)
    fetchTeamMembers(orgId, teamId)
      .then(setMembers)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (classifyAuthError(message) === 'not-found') setGone(true)
        else setErr(message)
      })
  }

  useEffect(load, [orgId, teamId])

  const emailFor = (userId: number) => orgMembers?.find(m => m.user_id === userId)?.email ?? `User #${userId}`

  const afterMutate = () => {
    load()
    onRosterChanged()
  }

  const eligibleInvitees = orgMembers?.filter(m => !members?.some(tm => tm.user_id === m.user_id)) ?? null

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    const email = inviteEmail.trim()
    if (!email) return
    setInviteBusy(true)
    setInviteErr(null)
    setInviteOk(false)
    try {
      await inviteTeamMember(orgId, teamId, { email, role: inviteRole })
      setInviteEmail('')
      setInviteOk(true)
      afterMutate()
    } catch (e) {
      setInviteErr(e instanceof Error ? e.message : String(e))
    } finally {
      setInviteBusy(false)
    }
  }

  if (gone) {
    return <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>This team is no longer available.</div>
  }
  if (err) {
    return <ErrBox msg={err} />
  }

  if (!members) {
    return <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}>Loading members…</div>
  }

  return (
    <div style={{ marginTop: 10 }}>
      {members.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>No members yet.</div>
      ) : (
        <div>
          {members.map(m => (
            <MemberRow
              key={m.user_id}
              member={m}
              label={emailFor(m.user_id)}
              canLeave={currentUserId != null && m.user_id === currentUserId}
              onRoleChange={async role => { await updateTeamMemberRole(orgId, teamId, m.user_id, role); afterMutate() }}
              onRemove={async () => { await removeTeamMember(orgId, teamId, m.user_id); afterMutate() }}
              onLeave={async () => { await leaveTeam(orgId, teamId); afterMutate() }}
            />
          ))}
        </div>
      )}

      <form onSubmit={handleInvite} style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
        {eligibleInvitees ? (
          <select
            aria-label="Member to invite"
            value={inviteEmail}
            onChange={e => setInviteEmail(e.target.value)}
            style={{ ...selectStyle, flex: 1, minWidth: 160 }}
          >
            <option value="">Select an organization member…</option>
            {eligibleInvitees.map(m => <option key={m.user_id} value={m.email}>{m.email}</option>)}
          </select>
        ) : (
          <input
            type="email"
            value={inviteEmail}
            onChange={e => setInviteEmail(e.target.value)}
            placeholder="Email address"
            aria-label="Email address"
            style={{
              flex: 1, minWidth: 160, fontSize: 12, padding: '6px 8px', borderRadius: 6,
              border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
            }}
          />
        )}
        <select
          aria-label="Role to invite as"
          value={inviteRole}
          onChange={e => setInviteRole(e.target.value)}
          style={selectStyle}
        >
          {TEAM_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <button
          type="submit"
          disabled={inviteBusy || !inviteEmail.trim()}
          style={{ ...secondaryButton, opacity: inviteBusy || !inviteEmail.trim() ? 0.6 : 1 }}
        >
          {inviteBusy ? 'Inviting…' : 'Invite'}
        </button>
      </form>
      {inviteErr && <ErrBox msg={inviteErr} />}
      {inviteOk && !inviteErr && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Invited.</div>
      )}
    </div>
  )
}
