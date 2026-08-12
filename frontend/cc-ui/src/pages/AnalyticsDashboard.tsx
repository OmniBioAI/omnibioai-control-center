import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, Download, Gauge, PlayCircle, Search, Users } from 'lucide-react'
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  exportAnalyticsCsv, fetchAnalyticsOverview, fetchAnalyticsPerformance,
  fetchAnalyticsServices, fetchAnalyticsUsers,
  type AnalyticsOverview, type AnalyticsPerformance, type AnalyticsServices, type AnalyticsUsers,
} from '../analytics'
import { hasPlatformAdminAccess } from '../auth'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../organizations'
import { DashboardGrid, MetricCard } from '../components/dashboard'
import { ActionToolbar, Button, Card, DataTable, EmptyState, ErrorState, LoadingState, SectionHeader } from '../components/ui'

// Usage Analytics v1 (PR-D). Reuses the exact dashboard widget family
// PR10 established (DashboardGrid/MetricCard) rather than a new visual
// system, per this feature's own task brief (Section 10). No chart
// library beyond recharts (already a dependency, already used by
// BillingPage.tsx/EcosystemPage.tsx) -- colors/margins below match those
// two pages' own CHART_BAR_COLOR/CHART_MUTED/CHART_BORDER constants
// exactly, not a new palette.
//
// Org/team filters (Section 10: "For users authorized to access
// multiple organizations") only render for a platform_admin -- an
// org_admin/team_admin's scope is already fixed server-side to their
// own org/team (require_analytics_scope resolves it from their token
// regardless of any filter this page could offer), so a picker for
// them would only ever have one real choice.

const CHART_LINE_COLOR = '#0094ff'
const CHART_MUTED = '#6b7280'
const CHART_BORDER = '#2a2d3e'

type RangePreset = '7d' | '30d' | '90d'
const RANGE_DAYS: Record<RangePreset, number> = { '7d': 7, '30d': 30, '90d': 90 }

function isoDateDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - (days - 1))
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

interface LoadState {
  overview: AnalyticsOverview
  users: AnalyticsUsers
  services: AnalyticsServices
  performance: AnalyticsPerformance
}

export default function AnalyticsDashboard() {
  const [range, setRange] = useState<RangePreset>('30d')
  const [orgOptions, setOrgOptions] = useState<PlatformOrgSummary[] | null>(null)
  const [orgFilter, setOrgFilter] = useState<number | undefined>(undefined)
  const [data, setData] = useState<LoadState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [denied, setDenied] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const showOrgFilter = hasPlatformAdminAccess()

  useEffect(() => {
    if (!showOrgFilter) return
    fetchPlatformOrgs({ pageSize: 100 }).then(r => setOrgOptions(r.items)).catch(() => setOrgOptions(null))
  }, [showOrgFilter])

  const filters = useMemo(
    () => ({ fromDate: isoDateDaysAgo(RANGE_DAYS[range]), toDate: todayIso(), orgId: orgFilter }),
    [range, orgFilter],
  )

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    Promise.all([
      fetchAnalyticsOverview(filters),
      fetchAnalyticsUsers(filters),
      fetchAnalyticsServices(filters),
      fetchAnalyticsPerformance(filters),
    ])
      .then(([overview, users, services, performance]) => setData({ overview, users, services, performance }))
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 403')) setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [filters.fromDate, filters.toDate, filters.orgId])

  const handleExport = async (type: Parameters<typeof exportAnalyticsCsv>[0]) => {
    setExportError(null)
    try {
      await exportAnalyticsCsv(type, filters)
    } catch (e: unknown) {
      setExportError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div>
      <SectionHeader
        title="Usage Analytics"
        description="Queries, active users, workflow executions, service usage, and error rates across the platform."
        actions={
          <ActionToolbar>
            <Button variant="secondary" onClick={load} disabled={loading}>Refresh</Button>
            <Button variant="secondary" onClick={() => handleExport('overview')} disabled={loading || denied}>
              <Download size={13} /> Export CSV
            </Button>
          </ActionToolbar>
        }
      />

      {denied ? (
        <EmptyState
          icon={AlertTriangle}
          title="Permission denied"
          description="Usage analytics requires a platform admin, organization admin, or team admin role. This is enforced by the backend, not this page."
        />
      ) : (
        <>
          <Card style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Date range</div>
                <ActionToolbar>
                  {(['7d', '30d', '90d'] as RangePreset[]).map(preset => (
                    <Button
                      key={preset}
                      variant={range === preset ? 'primary' : 'secondary'}
                      onClick={() => setRange(preset)}
                      aria-pressed={range === preset}
                    >
                      {preset}
                    </Button>
                  ))}
                </ActionToolbar>
              </div>
              {showOrgFilter && (
                <div>
                  <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }} htmlFor="analytics-org-filter">
                    Organization
                  </label>
                  <select
                    id="analytics-org-filter"
                    aria-label="Filter by organization"
                    style={{ fontSize: 12, padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)' }}
                    value={orgFilter ?? ''}
                    onChange={e => setOrgFilter(e.target.value ? Number(e.target.value) : undefined)}
                  >
                    <option value="">All organizations (platform-wide)</option>
                    {orgOptions?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </div>
              )}
            </div>
          </Card>

          {exportError && (
            <div style={{ marginBottom: 16 }}>
              <ErrorState message={`Export failed: ${exportError}`} onRetry={() => setExportError(null)} />
            </div>
          )}

          {loading && <LoadingState label="Loading usage analytics…" />}
          {!loading && error && <ErrorState message={error} onRetry={load} />}

          {!loading && !error && data && (
            <>
              <OverviewSection overview={data.overview} />
              <UsersSection users={data.users} />
              <ServicesSection services={data.services} onExport={() => handleExport('services')} />
              <PerformanceSection performance={data.performance} />
            </>
          )}
        </>
      )}
    </div>
  )
}

function OverviewSection({ overview }: { overview: AnalyticsOverview }) {
  return (
    <DashboardGrid title="Overview" description={`${overview.from_date} – ${overview.to_date}`}>
      <MetricCard label="Total Queries" value={overview.total_queries} icon={Search} />
      <MetricCard label="Active Users" value={overview.active_users} icon={Users} />
      <MetricCard label="Workflows Run" value={overview.workflows_run} icon={PlayCircle} />
      <MetricCard label="Error Rate" value={formatPct(overview.error_rate)} icon={AlertTriangle} />
    </DashboardGrid>
  )
}

function TrendChart({ data: chartData }: { data: { date: string; count: number | null }[] }) {
  if (chartData.every(d => d.count == null)) {
    return <EmptyState title="No data for this range" description="Team-scoped data may be unavailable -- see the note above." />
  }
  return (
    <div style={{ height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_BORDER} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: CHART_MUTED, fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: CHART_MUTED, fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip contentStyle={{ background: '#1a1d2e', border: `1px solid ${CHART_BORDER}`, borderRadius: 8, fontSize: 12 }} />
          <Line type="monotone" dataKey="count" stroke={CHART_LINE_COLOR} strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function UsersSection({ users }: { users: AnalyticsUsers }) {
  return (
    <DashboardGrid title="Active Users" description="Queries over time and daily/weekly/monthly active users.">
      <MetricCard label="DAU" value={users.dau} icon={Users} />
      <MetricCard label="WAU" value={users.wau} icon={Users} />
      <MetricCard label="MAU" value={users.mau} icon={Users} />
      <div style={{ gridColumn: '1 / -1' }}>
        <Card>
          {users.team_scope_available === false && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
              Team-scoped data is temporarily unavailable (the team roster couldn't be resolved) -- showing no data rather than an incorrect number.
            </div>
          )}
          <TrendChart data={users.daily} />
        </Card>
      </div>
    </DashboardGrid>
  )
}

function ServicesSection({ services, onExport }: { services: AnalyticsServices; onExport: () => void }) {
  return (
    <DashboardGrid title="Service Usage" description={services.note}>
      {services.services.length === 0 ? (
        <div style={{ gridColumn: '1 / -1' }}>
          <EmptyState title="No service activity" description={services.note ?? 'No recorded service traffic for this range.'} />
        </div>
      ) : (
        <div style={{ gridColumn: '1 / -1' }}>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
            <Button variant="ghost" onClick={onExport}><Download size={13} /> Export services CSV</Button>
          </div>
          <DataTable
            rowKey={r => r.service}
            rows={services.services}
            emptyLabel="No service activity"
            columns={[
              { key: 'service', header: 'Service', render: r => r.service },
              { key: 'total_calls', header: 'Calls', render: r => r.total_calls },
              { key: 'errors', header: 'Errors', render: r => r.errors },
              { key: 'error_rate', header: 'Error Rate', render: r => formatPct(r.error_rate) },
              { key: 'avg_latency_ms', header: 'Avg Latency', render: r => r.avg_latency_ms != null ? `${r.avg_latency_ms.toFixed(0)} ms` : '—' },
            ]}
          />
        </div>
      )}
    </DashboardGrid>
  )
}

function PerformanceSection({ performance }: { performance: AnalyticsPerformance }) {
  return (
    <DashboardGrid
      title="Performance"
      description={`Platform-wide (not organization-scoped) -- source: ${performance.latency_source === 'prometheus' ? 'Prometheus' : 'recent event data'}.`}
    >
      <MetricCard label="P50 Latency" value={performance.p50_latency_ms != null ? `${performance.p50_latency_ms.toFixed(0)} ms` : null} icon={Gauge} />
      <MetricCard label="P95 Latency" value={performance.p95_latency_ms != null ? `${performance.p95_latency_ms.toFixed(0)} ms` : null} icon={Gauge} />
      <MetricCard label="P99 Latency" value={performance.p99_latency_ms != null ? `${performance.p99_latency_ms.toFixed(0)} ms` : null} icon={Gauge} />
      <MetricCard label="Throughput" value={performance.throughput_per_day} icon={Activity} sublabel="requests / day" />
    </DashboardGrid>
  )
}
