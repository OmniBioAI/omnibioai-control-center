import RoleBadge from './RoleBadge'

// Phase 3 PR3B. Read-only display of a set of role names -- used wherever
// an editor (RoleSelector) either isn't authorized to render or hasn't
// loaded yet, and as the plain "currently has" summary next to the
// interactive editor. Deliberately takes plain strings, not RoleSummary
// objects, since every caller already has the assigned names on hand
// (PlatformUserDetail.global_roles, OrgMember.roles) without needing the
// full role catalog just to display them.
interface Props {
  roles: string[]
}

export default function RoleAssignmentList({ roles }: Props) {
  if (!roles.length) {
    return <div style={{ fontSize: 12, color: 'var(--muted)' }}>No roles assigned.</div>
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {roles.map(r => (
        <RoleBadge key={r} name={r} />
      ))}
    </div>
  )
}
