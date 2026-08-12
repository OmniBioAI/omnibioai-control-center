import { useEffect, useState } from 'react'
import { AlertTriangle, Download, FileText } from 'lucide-react'
import {
  downloadHipaaReportCsv, downloadHipaaReportPdf, fetchHipaaReport,
  type HipaaReport, type HipaaReportFilters,
} from '../compliance'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../organizations'
import {
  ActionToolbar, Button, Card, DataTable, EmptyState, ErrorState, LoadingState, SectionHeader, StatCard,
} from '../components/ui'
import { formatDate } from '../format'

// HIPAA Basic Compliance Report v0.8.0. platform_admin-only (see
// auth.ts::canSeeComplianceReport's own comment for why org_admin isn't
// offered yet) -- AdminApp.tsx gates the nav entry/route on that, this
// page also renders the same EmptyState AnalyticsDashboard.tsx uses on a
// 403, as defense in depth if reached some other way.
//
// Deliberately NOT auto-loaded on mount like AnalyticsDashboard.tsx --
// generating this report is a real, potentially-expensive fan-out across
// two other services (see compliance/service.py), so it only runs on an
// explicit "Generate Report" click, matching the task brief's own button
// list. Download buttons stay disabled until a report has actually been
// generated for the currently-selected org/range, so a download can
// never target a combination this page hasn't already confirmed is
// valid (org exists, from_date <= to_date -- both re-validated by the
// backend regardless).

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }

function isoDateDaysAgo(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() - (days - 1))
  return d.toISOString().slice(0, 10)
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function ComplianceReport() {
  const [fromDate, setFromDate] = useState(isoDateDaysAgo(30))
  const [toDate, setToDate] = useState(todayIso())
  const [orgOptions, setOrgOptions] = useState<PlatformOrgSummary[] | null>(null)
  const [orgId, setOrgId] = useState<number | undefined>(undefined)

  const [report, setReport] = useState<HipaaReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [denied, setDenied] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<'pdf' | 'csv' | null>(null)

  useEffect(() => {
    fetchPlatformOrgs({ pageSize: 100 }).then(r => setOrgOptions(r.items)).catch(() => setOrgOptions(null))
  }, [])

  const currentFilters = (): HipaaReportFilters | null => {
    if (orgId == null) return null
    return { fromDate, toDate, orgId }
  }

  const handleGenerate = () => {
    const filters = currentFilters()
    if (!filters) return
    setLoading(true)
    setError(null)
    setDenied(false)
    setReport(null)
    fetchHipaaReport(filters)
      .then(setReport)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 403')) setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  const handleDownload = async (kind: 'pdf' | 'csv') => {
    const filters = currentFilters()
    if (!filters) return
    setDownloadError(null)
    setDownloading(kind)
    try {
      await (kind === 'pdf' ? downloadHipaaReportPdf(filters) : downloadHipaaReportCsv(filters))
    } catch (e: unknown) {
      setDownloadError(e instanceof Error ? e.message : String(e))
    } finally {
      setDownloading(null)
    }
  }

  const canGenerate = orgId != null && fromDate <= toDate && !loading

  return (
    <div>
      <SectionHeader
        title="HIPAA Compliance Report"
        description="Basic compliance report: user access, RAG query log, and security events for an organization's date range. Full HIPAA certification is planned for v0.9.0."
      />

      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <label style={fieldLabel} htmlFor="compliance-from-date">From</label>
            <input
              id="compliance-from-date" aria-label="Report start date" type="date" style={selectStyle}
              value={fromDate} onChange={e => setFromDate(e.target.value)}
            />
          </div>
          <div>
            <label style={fieldLabel} htmlFor="compliance-to-date">To</label>
            <input
              id="compliance-to-date" aria-label="Report end date" type="date" style={selectStyle}
              value={toDate} onChange={e => setToDate(e.target.value)}
            />
          </div>
          <div>
            <label style={fieldLabel} htmlFor="compliance-org">Organization</label>
            <select
              id="compliance-org" aria-label="Organization" style={{ ...selectStyle, minWidth: 200 }}
              value={orgId ?? ''} onChange={e => setOrgId(e.target.value ? Number(e.target.value) : undefined)}
            >
              <option value="">Select an organization…</option>
              {orgOptions?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
          <ActionToolbar>
            <Button variant="primary" onClick={handleGenerate} disabled={!canGenerate}>
              {loading ? 'Generating…' : 'Generate Report'}
            </Button>
            <Button variant="secondary" onClick={() => handleDownload('pdf')} disabled={!report || downloading !== null}>
              <FileText size={13} /> {downloading === 'pdf' ? 'Downloading…' : 'Download PDF'}
            </Button>
            <Button variant="secondary" onClick={() => handleDownload('csv')} disabled={!report || downloading !== null}>
              <Download size={13} /> {downloading === 'csv' ? 'Downloading…' : 'Download CSV'}
            </Button>
          </ActionToolbar>
        </div>
        {fromDate > toDate && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--red)' }}>From date must be on or before to date.</div>
        )}
      </Card>

      {downloadError && (
        <div style={{ marginBottom: 16 }}>
          <ErrorState message={`Download failed: ${downloadError}`} onRetry={() => setDownloadError(null)} />
        </div>
      )}

      {denied && (
        <EmptyState
          icon={AlertTriangle}
          title="Permission denied"
          description="The HIPAA compliance report requires a platform admin role. This is enforced by the backend, not this page."
        />
      )}

      {loading && <LoadingState label="Generating compliance report…" />}
      {!loading && error && <ErrorState message={error} onRetry={handleGenerate} />}

      {!loading && !error && !denied && report && <ReportPreview report={report} />}
    </div>
  )
}

function ReportPreview({ report }: { report: HipaaReport }) {
  return (
    <>
      {report.truncated && (
        <div style={{ marginBottom: 16 }}>
          <EmptyState
            icon={AlertTriangle}
            title="Report may be incomplete"
            description="One or more data sources had more events than this report could fetch for the selected range. Narrow the date range for a complete report."
          />
        </div>
      )}

      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 12 }}>
          {report.organization_name} (org #{report.organization_id}) &middot; {report.from_date} to {report.to_date}
          <br />
          Generated {formatDate(report.generated_at)} by {report.generated_by}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          <StatCard label="Total Users" value={report.summary.total_users} />
          <StatCard label="Active Users" value={report.summary.active_users} />
          <StatCard label="RAG Queries" value={report.summary.total_rag_queries} />
          <StatCard
            label="Security Incidents"
            value={report.summary.security_incidents}
            accent={report.summary.security_incidents > 0 ? 'red' : 'default'}
          />
        </div>
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>User Access Log</div>
        <DataTable
          columns={[
            { key: 'user', header: 'User', render: (r: typeof report.user_access[number]) => r.user_label },
            { key: 'logins', header: 'Login Count', render: (r: typeof report.user_access[number]) => r.login_count },
            { key: 'last', header: 'Last Login', render: (r: typeof report.user_access[number]) => r.last_login ? formatDate(r.last_login) : '—' },
            { key: 'failed', header: 'Failed Attempts', render: (r: typeof report.user_access[number]) => r.failed_attempts },
          ]}
          rows={report.user_access}
          rowKey={r => r.user_label}
          emptyLabel="No login activity recorded in this period."
        />
      </Card>

      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>RAG Query Log</div>
        <DataTable
          columns={[
            { key: 'ts', header: 'Timestamp', render: (r: typeof report.rag_queries[number]) => r.timestamp ? formatDate(r.timestamp) : '—' },
            { key: 'user', header: 'User', render: (r: typeof report.rag_queries[number]) => r.user_label },
            { key: 'trace', header: 'Trace ID', render: (r: typeof report.rag_queries[number]) => r.trace_id ?? '—' },
          ]}
          rows={report.rag_queries}
          rowKey={r => `${r.trace_id ?? 'no-trace'}-${r.timestamp ?? ''}-${r.user_label}`}
          emptyLabel="No RAG queries recorded in this period."
        />
      </Card>

      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>Security Events</div>
        <DataTable
          columns={[
            { key: 'ts', header: 'Timestamp', render: (r: typeof report.security_events[number]) => r.timestamp ? formatDate(r.timestamp) : '—' },
            { key: 'event', header: 'Event', render: (r: typeof report.security_events[number]) => r.label },
            { key: 'actor', header: 'Actor', render: (r: typeof report.security_events[number]) => r.actor_label },
            {
              key: 'outcome', header: 'Outcome',
              render: (r: typeof report.security_events[number]) => (
                <span style={{ color: r.outcome === 'deny' || r.outcome === 'failure' ? 'var(--red)' : 'var(--text2)' }}>{r.outcome}</span>
              ),
            },
          ]}
          rows={report.security_events}
          rowKey={r => `${r.event_type}-${r.timestamp ?? ''}-${r.actor_label}`}
          emptyLabel="No security events recorded in this period."
        />
      </Card>
    </>
  )
}
