import { useEffect, useState } from 'react'
import {
  fetchMyOrgs, fetchPlatformOrgs,
  type MyOrg, type PlatformOrgSummary,
} from '../../organizations'
import { hasPlatformAdminAccess } from '../../auth'
import { PageContainer, SectionHeader, ActionToolbar, LoadingState, ErrorState, EmptyState } from '../../components/ui'
import TeamsCard from '../../components/teams/TeamsCard'

/**
 * PR11.2: standalone enterprise Teams page -- promotes team management out
 * of OrganizationDetailPage into its own nav destination (navigation.ts's
 * 'teams' entry, previously Coming Soon). Reuses TeamsCard exactly as-is
 * (create/view/edit-members/delete, all backed by omnibioai-auth's
 * existing /orgs/{org_id}/teams* endpoints via routes_team_proxy.py,
 * unchanged by this PR) -- this page only adds the organization picker
 * that OrganizationDetailPage didn't need (it already had orgId from the
 * URL). No new API calls, no new authorization logic: GET /platform/orgs
 * or GET /orgs (the same dual view OrganizationsPage.tsx already uses)
 * decides which organizations populate the selector, and TeamsCard's own
 * listTeams call is what actually determines whether the viewer can see
 * that org's teams at all -- a non-member who somehow selects an org they
 * don't belong to just gets TeamsCard's existing "hide silently on 403"
 * behavior, not a new error path invented here.
 */
interface OrgOption { id: number; name: string }

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}

interface Props {
  /** Pre-selects an organization -- set when arriving via "View all
   * teams" from OrganizationDetailPage. Falls back to the first option
   * once the organization list loads if this id isn't among them (or is
   * omitted, the normal nav-click entry point). */
  initialOrgId?: number | null
}

export default function TeamsPage({ initialOrgId }: Props) {
  // Evaluated once per mount, same convention as OrganizationsPage.tsx --
  // reads the live cached session claims, not re-derived permission logic.
  const [isPlatformAdmin] = useState(() => hasPlatformAdminAccess())
  const [orgs, setOrgs] = useState<OrgOption[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(initialOrgId ?? null)

  useEffect(() => {
    setOrgs(null)
    setErr(null)
    const load = isPlatformAdmin
      ? fetchPlatformOrgs({ pageSize: 100 }).then((r): OrgOption[] => r.items.map((o: PlatformOrgSummary) => ({ id: o.id, name: o.name })))
      : fetchMyOrgs().then((list): OrgOption[] => list.map((o: MyOrg) => ({ id: o.id, name: o.name })))
    load
      .then(list => {
        setOrgs(list)
        setSelectedOrgId(cur => (cur != null && list.some(o => o.id === cur) ? cur : (list[0]?.id ?? null)))
      })
      .catch(e => setErr(String(e)))
  }, [isPlatformAdmin])

  return (
    <PageContainer>
      <SectionHeader
        title="Teams"
        description="Team membership across every organization you can see. Creating, renaming, and deleting teams -- and adding or removing members -- is enforced entirely by omnibioai-auth; this page only calls its existing endpoints."
        actions={orgs && orgs.length > 0 ? (
          <ActionToolbar>
            <label htmlFor="teams-org-select" style={{ fontSize: 12, color: 'var(--muted)' }}>Organization</label>
            <select
              id="teams-org-select"
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

      {err && <ErrorState message={err} />}
      {!err && orgs == null && <LoadingState label="Loading organizations…" />}
      {!err && orgs && orgs.length === 0 && (
        <EmptyState title={isPlatformAdmin ? 'No organizations exist yet.' : "You don't belong to any organization yet."} />
      )}
      {!err && orgs && orgs.length > 0 && selectedOrgId != null && (
        <TeamsCard orgId={selectedOrgId} />
      )}
    </PageContainer>
  )
}
