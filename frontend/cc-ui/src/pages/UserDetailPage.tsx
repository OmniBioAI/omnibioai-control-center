import { useEffect, useState } from 'react'
import { fetchPlatformUserDetail, type PlatformUserDetail } from '../users'
import { assignUserRole, fetchPlatformRoles, removeUserRole, type RoleSummary } from '../roles'
import StatusBadge from '../components/StatusBadge'
import UserOrgMembershipList from '../components/users/UserOrgMembershipList'
import UserStatusAction from '../components/users/UserStatusAction'
import RoleAssignmentList from '../components/roles/RoleAssignmentList'
import RoleSelector from '../components/roles/RoleSelector'

const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '18px 20px', boxShadow: 'var(--shadow-card)',
}
const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4,
}
const value: React.CSSProperties = { fontSize: 13, color: 'var(--text)' }
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16,
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={value}>{children}</div>
    </div>
  )
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div role="alert" style={{
      padding: '12px 16px', borderRadius: 8, background: 'var(--red-bg)',
      border: '1px solid var(--red)', color: 'var(--red)', fontSize: 13,
    }}>
      {msg}
    </div>
  )
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button
      onClick={onBack}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 16,
        fontSize: 12, fontWeight: 600, color: 'var(--muted)', background: 'none', border: 'none', cursor: 'pointer',
      }}
    >
      ← Back to Users
    </button>
  )
}

interface Props {
  userId: number
  onBack: () => void
}

// Platform-admin only, mirroring GET /platform/users/{id}'s own gate --
// there is no org-admin variant of this page (see UsersPage.tsx).
export default function UserDetailPage({ userId, onBack }: Props) {
  const [user, setUser] = useState<PlatformUserDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // Phase 3 PR3B: the role catalog is fetched independently of the user
  // detail load above -- a failure here degrades the Global Roles section
  // to a read-only RoleAssignmentList (no role IDs available to remove
  // by) rather than failing the whole page, since every other field on
  // this page is unaffected by whether /platform/roles happens to be
  // reachable.
  const [roleCatalog, setRoleCatalog] = useState<RoleSummary[] | null>(null)

  const load = () => {
    setLoading(true)
    fetchPlatformUserDetail(userId)
      .then(d => { setUser(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [userId])
  useEffect(() => {
    fetchPlatformRoles().then(setRoleCatalog).catch(() => setRoleCatalog(null))
  }, [])

  const handleAssignGlobalRole = async (roleName: string) => {
    await assignUserRole(userId, roleName)
    load()
  }
  const handleRemoveGlobalRole = async (_roleName: string, roleId: number) => {
    await removeUserRole(userId, roleId)
    load()
  }

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>Loading user…</div>
  if (err || !user) {
    // Covers "doesn't exist" (404) and, defensively, any authorization
    // rejection the backend might return -- this page never assumes
    // access just because the URL contains a user_id.
    return (
      <div>
        <BackLink onBack={onBack} />
        <ErrBox msg={err ?? 'User not found'} />
      </div>
    )
  }

  return (
    <div>
      <BackLink onBack={onBack} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>{user.email}</h2>
        <StatusBadge status={user.status} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>User #{user.id}</div>

      <div style={card}>
        <div style={{ ...label, marginBottom: 12 }}>General Information</div>
        <div style={grid}>
          <Field title="User ID">{user.id}</Field>
          <Field title="Email">{user.email}</Field>
          <Field title="Created">{user.created_at ? new Date(user.created_at).toLocaleString() : '—'}</Field>
        </div>
        {user.status_changed_at && (
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--muted)' }}>
            Status last changed {new Date(user.status_changed_at).toLocaleString()}
            {user.status_changed_by_email && ` by ${user.status_changed_by_email}`}
            {user.status_changed_reason && ` — "${user.status_changed_reason}"`}
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <UserStatusAction user={user} onChanged={load} />
        </div>
      </div>

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ ...label, marginBottom: 12 }}>Global Roles</div>
        {roleCatalog ? (
          <RoleSelector
            allRoles={roleCatalog}
            assignedRoleNames={user.global_roles}
            onAssign={handleAssignGlobalRole}
            onRemove={handleRemoveGlobalRole}
          />
        ) : (
          <RoleAssignmentList roles={user.global_roles} />
        )}
      </div>

      <div style={{ ...card, marginTop: 16 }}>
        <div style={{ ...label, marginBottom: 12 }}>Organization Memberships</div>
        <UserOrgMembershipList memberships={user.memberships} />
      </div>
    </div>
  )
}
