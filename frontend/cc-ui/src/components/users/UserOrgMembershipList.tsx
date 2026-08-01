import type { OrgMembershipSummary } from '../../users'

// The "org membership display" this PR exists to provide -- one row per
// organization the user belongs to, reused only on UserDetailPage today
// but kept as its own component (not inlined) since a future Users-
// adjacent page is likely to want the same view.
interface Props {
  memberships: OrgMembershipSummary[]
}

const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid var(--border)',
  textAlign: 'left', background: 'rgba(255,255,255,0.03)', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  fontSize: 12, color: 'var(--text2)',
  padding: '10px 14px', borderBottom: '1px solid var(--border)',
  verticalAlign: 'middle',
}

export default function UserOrgMembershipList({ memberships }: Props) {
  if (!memberships.length) {
    return (
      <div style={{ fontSize: 12, color: 'var(--muted)' }}>
        Not a member of any organization.
      </div>
    )
  }

  return (
    <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={th}>Organization</th>
          <th style={th}>Slug</th>
          <th style={th}>Role(s)</th>
          <th style={th}>Status</th>
          <th style={th}>Joined</th>
        </tr>
      </thead>
      <tbody>
        {memberships.map(m => (
          <tr key={m.organization_id}>
            <td style={{ ...td, color: 'var(--text)', fontWeight: 600 }}>{m.organization_name}</td>
            <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11 }}>{m.organization_slug}</td>
            <td style={td}>{m.roles.length ? m.roles.join(', ') : '—'}</td>
            <td style={td}>{m.status}</td>
            <td style={td}>{m.joined_at ? new Date(m.joined_at).toLocaleDateString() : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
