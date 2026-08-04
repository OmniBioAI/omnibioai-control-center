import { useEffect, useState } from 'react'
import {
  fetchMyOrgs, fetchOrgMembers, fetchPlatformOrgs,
  type MyOrg, type OrgMember, type PlatformOrgSummary,
} from '../../organizations'
import { fetchOrgRoles, type RoleSummary } from '../../roles'
import { hasPlatformAdminAccess } from '../../auth'
import { PageContainer, SectionHeader, ActionToolbar, LoadingState, ErrorState, EmptyState, Card } from '../../components/ui'
import RoleBadge from '../../components/roles/RoleBadge'

/**
 * PR11.2: standalone, READ-ONLY enterprise Roles & Permissions page.
 * Promotes visibility of the existing role catalog (GET
 * /orgs/{org_id}/roles, unchanged since Phase 3 PR3B) out of
 * OrganizationDetailPage's Members & Roles editor into its own nav
 * destination. Deliberately does not let anyone create a role, edit a
 * role's permissions, or change who holds a role from here -- all of
 * that already exists (RoleSelector, on OrganizationDetailPage) and stays
 * exactly where it is; per this PR's own scope, permission mutation
 * requires a separate security review this PR is not that review.
 *
 * Member counts are computed client-side from GET /orgs/{org_id}/members
 * (the same OrgMember.roles string array MembersRolesCard/RoleSelector
 * already read) -- best-effort only: a viewer without manage_org can see
 * the role catalog (bare org membership is enough per
 * get_org_membership_or_platform_admin) but not the member roster, so the
 * count silently degrades to "--" rather than an error, the same "hide,
 * don't error" posture TeamsCard/MembersRolesCard already established for
 * exactly this situation.
 */
interface OrgOption { id: number; name: string }

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const permissionPill: React.CSSProperties = {
  fontSize: 11, fontFamily: 'monospace', padding: '3px 8px', borderRadius: 6,
  background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', color: 'var(--text2)',
}

interface Props {
  /** Pre-selects an organization -- set when arriving via "View roles &
   * permissions" from OrganizationDetailPage. */
  initialOrgId?: number | null
}

export default function RolesPage({ initialOrgId }: Props) {
  const [isPlatformAdmin] = useState(() => hasPlatformAdminAccess())
  const [orgs, setOrgs] = useState<OrgOption[] | null>(null)
  const [orgsErr, setOrgsErr] = useState<string | null>(null)
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(initialOrgId ?? null)

  const [roles, setRoles] = useState<RoleSummary[] | null>(null)
  const [rolesErr, setRolesErr] = useState<string | null>(null)
  const [members, setMembers] = useState<OrgMember[] | null>(null)

  useEffect(() => {
    setOrgs(null)
    setOrgsErr(null)
    const load = isPlatformAdmin
      ? fetchPlatformOrgs({ pageSize: 100 }).then((r): OrgOption[] => r.items.map((o: PlatformOrgSummary) => ({ id: o.id, name: o.name })))
      : fetchMyOrgs().then((list): OrgOption[] => list.map((o: MyOrg) => ({ id: o.id, name: o.name })))
    load
      .then(list => {
        setOrgs(list)
        setSelectedOrgId(cur => (cur != null && list.some(o => o.id === cur) ? cur : (list[0]?.id ?? null)))
      })
      .catch(e => setOrgsErr(String(e)))
  }, [isPlatformAdmin])

  useEffect(() => {
    if (selectedOrgId == null) return
    setRoles(null)
    setRolesErr(null)
    setMembers(null)
    fetchOrgRoles(selectedOrgId).then(setRoles).catch(e => setRolesErr(String(e)))
    // Best-effort only -- see module docstring. A 403 here just means the
    // member counts below show "--", not an error banner.
    fetchOrgMembers(selectedOrgId).then(setMembers).catch(() => setMembers(null))
  }, [selectedOrgId])

  const memberCountFor = (roleName: string): number | null =>
    members ? members.filter(m => m.roles.includes(roleName)).length : null

  return (
    <PageContainer>
      <SectionHeader
        title="Roles & Permissions"
        description="Read-only view of each organization's role catalog and what every role grants. Assigning or removing a member's role is done from that member's row on the organization's detail page -- this page does not mutate anything."
        actions={orgs && orgs.length > 0 ? (
          <ActionToolbar>
            <label htmlFor="roles-org-select" style={{ fontSize: 12, color: 'var(--muted)' }}>Organization</label>
            <select
              id="roles-org-select"
              aria-label="Select organization"
              value={selectedOrgId ?? ''}
              onChange={e => setSelectedOrgId(Number(e.target.value))}
              style={selectStyle}
            >
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </ActionToolbar>
        ) : undefined}
      />

      {orgsErr && <ErrorState message={orgsErr} />}
      {!orgsErr && orgs == null && <LoadingState label="Loading organizations…" />}
      {!orgsErr && orgs && orgs.length === 0 && (
        <EmptyState title={isPlatformAdmin ? 'No organizations exist yet.' : "You don't belong to any organization yet."} />
      )}

      {!orgsErr && orgs && orgs.length > 0 && selectedOrgId != null && (
        <>
          {rolesErr && <ErrorState message={rolesErr} />}
          {!rolesErr && roles == null && <LoadingState label="Loading roles…" />}
          {!rolesErr && roles && roles.length === 0 && (
            <EmptyState title="No roles defined for this organization." />
          )}
          {!rolesErr && roles && roles.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {roles.map(role => {
                const count = memberCountFor(role.name)
                return (
                  <Card key={role.id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                      <div>
                        <RoleBadge name={role.name} />
                        {role.description && (
                          <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>{role.description}</div>
                        )}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                        {count != null ? `${count} member${count === 1 ? '' : 's'}` : '—'}
                      </div>
                    </div>
                    <div style={{
                      marginTop: 12, fontSize: 10, fontWeight: 700, color: 'var(--muted)',
                      textTransform: 'uppercase', letterSpacing: '0.06em',
                    }}>
                      Permissions
                    </div>
                    <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {role.permissions.length
                        ? role.permissions.map(p => <span key={p} style={permissionPill}>{p}</span>)
                        : <span style={{ fontSize: 12, color: 'var(--muted)' }}>No permissions granted.</span>}
                    </div>
                  </Card>
                )
              })}
            </div>
          )}
        </>
      )}
    </PageContainer>
  )
}
