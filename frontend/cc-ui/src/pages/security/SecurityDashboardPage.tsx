import { useEffect, useState } from 'react'
import { ShieldAlert, ShieldCheck } from 'lucide-react'
import { fetchPlatformUsers, type PlatformUserSummary } from '../../users'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../../organizations'
import { fetchAuditEvents, formatEventType, MFA_EVENT_TYPES, type AuditEvent } from '../../audit'
import { Card, SectionHeader, StatCard, LoadingState, ErrorState, EmptyState } from '../../components/ui'
import { formatDate } from '../../format'

// PR11.5.6 (Admin Console Security UI). Enterprise security overview --
// MFA adoption, organization MFA policy counts, recent MFA/audit events.
// Sourced entirely from the existing Users/Organizations/Audit APIs, no
// new backend aggregation endpoint -- see
// docs/pr11-5-6-security-ui-discovery.md SS7 for the full reasoning and
// the known scaling caveat this page's own paging-walk accepts (flagged
// there, not solved here).
const PAGE_WALK_SIZE = 100
// Bounds the paging walk below -- a real safety backstop, not a
// realistic ceiling: at PAGE_WALK_SIZE=100/page this covers 100,000
// rows before giving up, an order of magnitude past where §7's own
// scaling caveat already says a real aggregation endpoint would be the
// correct fix instead.
const MAX_PAGES = 1000

async function fetchAllUsers(): Promise<PlatformUserSummary[]> {
  const all: PlatformUserSummary[] = []
  let page = 1
  let totalPages = 1
  while (page <= totalPages && page <= MAX_PAGES) {
    const resp = await fetchPlatformUsers({ page, pageSize: PAGE_WALK_SIZE })
    all.push(...resp.items)
    totalPages = resp.total_pages
    page += 1
  }
  return all
}

async function fetchAllOrgs(): Promise<PlatformOrgSummary[]> {
  const all: PlatformOrgSummary[] = []
  let page = 1
  let totalPages = 1
  while (page <= totalPages && page <= MAX_PAGES) {
    const resp = await fetchPlatformOrgs({ page, pageSize: PAGE_WALK_SIZE })
    all.push(...resp.items)
    totalPages = resp.total_pages
    page += 1
  }
  return all
}

interface DashboardData {
  totalUsers: number
  mfaEnabledUsers: number
  mfaDisabledUsers: number
  totalOrgs: number
  orgsRequiringMfa: number
  orgsWithoutPolicy: number
  recentEvents: AuditEvent[]
}

async function loadDashboardData(): Promise<DashboardData> {
  const [users, orgs, auditPage] = await Promise.all([
    fetchAllUsers(),
    fetchAllOrgs(),
    // A modestly larger page than the 10 the tile actually shows --
    // simpler than issuing one request per MFA event type (the backend
    // only accepts a single event_type value per request), and cheap at
    // this size. See SS7.
    fetchAuditEvents({ pageSize: 50 }),
  ])

  const mfaEnabledUsers = users.filter(u => u.mfa_enabled).length
  const recentEvents = auditPage.items
    .filter(e => (MFA_EVENT_TYPES as readonly string[]).includes(e.event_type))
    .slice(0, 10)

  return {
    totalUsers: users.length,
    mfaEnabledUsers,
    mfaDisabledUsers: users.length - mfaEnabledUsers,
    totalOrgs: orgs.length,
    orgsRequiringMfa: orgs.filter(o => o.mfa_policy_required).length,
    orgsWithoutPolicy: orgs.filter(o => !o.mfa_policy_configured).length,
    recentEvents,
  }
}

function enrollmentPct(data: DashboardData): string {
  if (data.totalUsers === 0) return '—'
  return `${Math.round((data.mfaEnabledUsers / data.totalUsers) * 100)}%`
}

export default function SecurityDashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    loadDashboardData()
      .then(setData)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 403')) setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  return (
    <div>
      <SectionHeader
        title="Security Overview"
        description="Enterprise-wide MFA adoption, organization policy coverage, and recent security events."
      />

      {loading && <LoadingState label="Loading security overview…" />}

      {!loading && denied && (
        <EmptyState
          icon={ShieldAlert}
          title="Permission denied"
          description="You don't have manage_all_orgs, so the security overview can't be shown here. This is enforced by the backend, not this page."
        />
      )}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !denied && !error && data && (
        data.totalUsers === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="No users yet"
            description="Once users exist on this platform, MFA adoption and policy coverage will appear here."
          />
        ) : (
          <>
            <div style={{ ...label, marginBottom: 12 }}>MFA Adoption</div>
            <div style={grid}>
              <StatCard label="Total Users" value={data.totalUsers} />
              <StatCard label="MFA Enabled" value={data.mfaEnabledUsers} accent="green" />
              <StatCard label="MFA Disabled" value={data.mfaDisabledUsers} accent="amber" />
              <StatCard label="Enrollment" value={enrollmentPct(data)} />
            </div>

            <div style={{ ...label, marginTop: 24, marginBottom: 12 }}>Organization Policies</div>
            <div style={grid}>
              <StatCard label="Organizations Requiring MFA" value={data.orgsRequiringMfa} accent="green" />
              <StatCard label="Organizations Without a Policy" value={data.orgsWithoutPolicy} accent="amber" />
            </div>

            <div style={{ ...label, marginTop: 24, marginBottom: 12 }}>Recent Security Events</div>
            <Card>
              {data.recentEvents.length === 0 ? (
                <EmptyState icon={ShieldCheck} title="No recent MFA events" description="MFA enrollment, policy, and override events will appear here as they happen." />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {data.recentEvents.map(event => (
                    <div
                      key={event.id}
                      style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '8px 0', borderBottom: '1px solid var(--border)', fontSize: 13,
                      }}
                    >
                      <div>
                        <span style={{ fontWeight: 600, color: 'var(--text)' }}>{formatEventType(event.event_type)}</span>
                        <span style={{ color: 'var(--muted)', marginLeft: 8 }}>
                          {event.actor_email ?? (event.actor_user_id != null ? `User #${event.actor_user_id}` : '—')}
                          {event.organization_name && ` · ${event.organization_name}`}
                        </span>
                      </div>
                      <span style={{ color: 'var(--muted)', fontSize: 12 }}>{formatDate(event.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )
      )}
    </div>
  )
}

const label: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.06em',
}
const grid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16,
}
