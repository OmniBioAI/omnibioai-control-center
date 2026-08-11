import { useEffect, useState } from 'react'
import { createTeam, deleteTeam, listTeams, type Team } from '../../teams'
import { fetchOrgMembers, type OrgMember } from '../../organizations'
import TeamRow from './TeamRow'

// Phase 3 PR3C, updated Team Management v0.8.0 Step 5 (description field
// on the create form; member editing moved into TeamRow/TeamMembersPanel,
// see those files). Rendered by OrganizationDetailPage.tsx in both the
// platform-admin and org-admin views, near MembersRolesCard -- same
// placement convention, same independent-fetch/graceful-degradation
// shape, but a different authorization boundary underneath: GET
// /orgs/{org_id}/teams only requires bare org membership (any member can
// view teams, per omnibioai-auth's existing get_org_membership_or_
// platform_admin dependency -- unmodified by this change), unlike GET
// /orgs/{org_id}/members which requires manage_org. That's why this card
// hides entirely only if the *teams* fetch itself fails (a true non-
// member, or an org that doesn't exist) -- a plain member who can list
// teams but can't load the org member roster (no manage_org) still sees
// their teams, just with "User #id" instead of an email inside
// TeamMembersPanel, and a free-text invite field instead of a picker.
// Every mutating control (create/delete/rename/manage members) is
// rendered unconditionally regardless of the viewer's guessed role -- the
// backend is what actually decides whether an attempt succeeds; a 403
// surfaces inline, the same "frontend hiding is not authorization"
// posture PR3B already established.
interface Props {
  orgId: number
}

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '18px 20px', boxShadow: 'var(--shadow-card)',
  marginTop: 16,
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12,
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: '8px 12px', borderRadius: 8, background: 'var(--red-bg)',
        border: '1px solid var(--red)', color: 'var(--red)', fontSize: 12, marginBottom: 12,
      }}
    >
      {msg}
    </div>
  )
}

export default function TeamsCard({ orgId }: Props) {
  const [teams, setTeams] = useState<Team[] | null>(null)
  const [members, setMembers] = useState<OrgMember[] | null>(null)
  const [hidden, setHidden] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [creating, setCreating] = useState(false)

  const loadTeams = () => {
    listTeams(orgId).then(setTeams).catch(() => setHidden(true))
  }

  useEffect(() => {
    setHidden(false)
    setTeams(null)
    setMembers(null)
    loadTeams()
    fetchOrgMembers(orgId).then(setMembers).catch(() => setMembers(null))
  }, [orgId])

  if (hidden) return null

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    setErr(null)
    try {
      await createTeam(orgId, { name, description: newDescription.trim() || undefined })
      setNewName('')
      setNewDescription('')
      loadTeams()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div style={card}>
      <div style={label}>Teams</div>
      {err && <ErrBox msg={err} />}

      <form onSubmit={handleCreate} style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <input
          value={newName}
          onChange={e => setNewName(e.target.value)}
          placeholder="New team name"
          aria-label="New team name"
          style={{
            flex: 1, minWidth: 140, fontSize: 12, padding: '7px 10px', borderRadius: 6,
            border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
          }}
        />
        <input
          value={newDescription}
          onChange={e => setNewDescription(e.target.value)}
          placeholder="Description (optional)"
          aria-label="New team description"
          style={{
            flex: 1, minWidth: 160, fontSize: 12, padding: '7px 10px', borderRadius: 6,
            border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
          }}
        />
        <button
          type="submit"
          disabled={creating || !newName.trim()}
          style={{
            fontSize: 12, fontWeight: 700, padding: '7px 14px', borderRadius: 8, border: 'none',
            background: 'var(--accent)', color: '#000',
            cursor: creating || !newName.trim() ? 'not-allowed' : 'pointer',
            opacity: creating || !newName.trim() ? 0.6 : 1,
          }}
        >
          {creating ? 'Creating…' : 'Create Team'}
        </button>
      </form>

      {!teams ? (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Loading teams…</div>
      ) : teams.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>No teams yet.</div>
      ) : (
        <div>
          {teams.map(t => (
            <TeamRow
              key={t.id}
              orgId={orgId}
              team={t}
              orgMembers={members}
              onChanged={loadTeams}
              onDelete={async () => {
                await deleteTeam(orgId, t.id)
                loadTeams()
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
