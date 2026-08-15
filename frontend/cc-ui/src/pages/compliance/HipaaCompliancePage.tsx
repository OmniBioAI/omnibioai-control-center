import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchHipaaComplianceSummary, fetchHipaaComplianceChanges,
  CONTROL_CATEGORY_LABELS, STATUS_LABELS, COMPLIANCE_STATUSES, CONTROL_CATEGORIES,
  type HipaaComplianceSummary, type HipaaComplianceChange, type HipaaComplianceChangeListResponse,
  type ComplianceStatus, type ComplianceControlCategory,
} from '../../hipaaCompliance'
import {
  Card, SectionHeader, StatCard, LoadingState, ErrorState, EmptyState,
  SessionExpiredState, DataTable, Pagination, Button, ActionToolbar,
} from '../../components/ui'
import { formatDate, formatDateOnly, classifyAuthError } from '../../format'

const PAGE_SIZE = 20

type Tab = 'overview' | 'history' | 'controls'

function StatusBadge({ status }: { status: ComplianceStatus }) {
  const colorVar = {
    planned: 'var(--muted)', in_progress: 'var(--blue)', verified: 'var(--green)',
    released: 'var(--green)', exception: 'var(--red)',
  }[status]
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 99,
      color: colorVar, border: `1px solid ${colorVar}`, whiteSpace: 'nowrap',
    }}>
      {STATUS_LABELS[status]}
    </span>
  )
}

const OVERALL_STATUS_COPY: Record<HipaaComplianceSummary['overall_status'], { label: string; accent: 'default' | 'green' | 'amber' | 'red' }> = {
  no_data: { label: 'No data yet', accent: 'default' },
  on_track: { label: 'On track', accent: 'green' },
  in_progress: { label: 'In progress', accent: 'amber' },
  attention_needed: { label: 'Attention needed', accent: 'red' },
}

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }

export default function HipaaCompliancePage() {
  const [tab, setTab] = useState<Tab>('overview')

  return (
    <div>
      <SectionHeader
        title="HIPAA Compliance"
        description="Persistent history of HIPAA-related changes, releases, and their verification evidence."
      />
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, borderBottom: '1px solid var(--border)' }}>
        {(['overview', 'history', 'controls'] as const).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              fontSize: 13, fontWeight: 600, padding: '9px 14px', background: 'none', border: 'none',
              borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent',
              color: tab === t ? 'var(--text)' : 'var(--muted)', cursor: 'pointer',
            }}
          >
            {t === 'overview' ? 'Compliance Overview' : t === 'history' ? 'Change History' : 'Compliance Controls'}
          </button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'history' && <ChangeHistoryTab />}
      {tab === 'controls' && <ControlsTab />}
    </div>
  )
}

// ── Compliance Overview ──────────────────────────────────────────────────

function OverviewTab() {
  const [data, setData] = useState<HipaaComplianceSummary | null>(null)
  const [session, setSession] = useState(false)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    setSession(false)
    setDenied(false)
    fetchHipaaComplianceSummary()
      .then(setData)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setSession(true)
        else if (kind === 'denied') setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  if (loading) return <LoadingState label="Loading compliance overview…" />
  if (session) return <SessionExpiredState />
  if (denied) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Permission denied"
        description="You don't have manage_all_orgs, so the compliance overview can't be shown here. This is enforced by the backend, not this page."
      />
    )
  }
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!data) return null

  const overall = OVERALL_STATUS_COPY[data.overall_status]

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 24 }}>
        <StatCard label="Overall Status" value={overall.label} accent={overall.accent} />
        <StatCard label="Controls Tracked" value={data.total_controls_tracked} />
        <StatCard label="Verified" value={data.verified_count} accent="green" />
        <StatCard label="Pending" value={data.pending_count} accent="amber" />
        <StatCard label="Exceptions" value={data.exception_count} accent={data.exception_count > 0 ? 'red' : 'default'} />
      </div>

      <Card>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Latest Compliance Change
        </div>
        {data.latest_change_id ? (
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{data.latest_change_title}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              {data.latest_change_id} · {formatDateOnly(data.latest_change_date)}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>No compliance changes recorded yet.</div>
        )}
      </Card>
    </>
  )
}

// ── Compliance Controls ──────────────────────────────────────────────────

function ControlsTab() {
  const [data, setData] = useState<HipaaComplianceSummary | null>(null)
  const [session, setSession] = useState(false)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    setSession(false)
    setDenied(false)
    fetchHipaaComplianceSummary()
      .then(setData)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setSession(true)
        else if (kind === 'denied') setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  if (loading) return <LoadingState label="Loading compliance controls…" />
  if (session) return <SessionExpiredState />
  if (denied) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Permission denied"
        description="You don't have manage_all_orgs, so compliance controls can't be shown here. This is enforced by the backend, not this page."
      />
    )
  }
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!data) return null

  return (
    <DataTable
      rowKey={c => c.category}
      rows={data.controls}
      emptyLabel="No control categories tracked yet."
      columns={[
        { key: 'label', header: 'Control / Category', render: c => c.label },
        { key: 'total', header: 'Total', render: c => c.total },
        { key: 'verified', header: 'Verified', render: c => c.verified },
        { key: 'pending', header: 'Pending', render: c => c.pending },
        { key: 'exceptions', header: 'Exceptions', render: c => c.exceptions },
      ]}
    />
  )
}

// ── Change History ───────────────────────────────────────────────────────

function EvidenceList({ change }: { change: HipaaComplianceChange }) {
  if (change.evidence.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--muted)' }}>No evidence recorded.</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {change.evidence.map((ev, i) => (
        <div key={i} style={{ fontSize: 12, color: 'var(--text2)' }}>
          <span style={{ fontWeight: 600, color: 'var(--text)' }}>[{ev.type}]</span>{' '}
          {ev.url ? (
            <a href={ev.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>{ev.label}</a>
          ) : (
            <span>{ev.label}</span>
          )}
        </div>
      ))}
    </div>
  )
}

function Field({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 13, color: 'var(--text)' }}>{children}</div>
    </div>
  )
}

function ChangeDetailModal({ change, onClose }: { change: HipaaComplianceChange; onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-label="HIPAA compliance change detail"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 560, maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{change.title}</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, marginBottom: 16 }}>
          <Field title="Change ID">{change.change_id}</Field>
          <Field title="Status"><StatusBadge status={change.status} /></Field>
          <Field title="Date">{formatDateOnly(change.change_date)}</Field>
          <Field title="Control / Category">{CONTROL_CATEGORY_LABELS[change.control_category]}</Field>
          <Field title="Repository">{change.repository}</Field>
          <Field title="Branch">{change.branch ?? '—'}</Field>
          <Field title="Commit">{change.commit_sha ? <code style={{ fontSize: 11 }}>{change.commit_sha}</code> : '—'}</Field>
          <Field title="PR">{change.pr_number != null ? `#${change.pr_number}` : '—'}</Field>
          <Field title="Affected Component">{change.affected_component ?? '—'}</Field>
          <Field title="Reviewer">{change.reviewer ?? 'Not recorded'}</Field>
        </div>

        {change.description && (
          <div style={{ marginBottom: 14 }}>
            <Field title="Description">{change.description}</Field>
          </div>
        )}
        {change.verification_result && (
          <div style={{ marginBottom: 14 }}>
            <Field title="Verification / Test Result">{change.verification_result}</Field>
          </div>
        )}

        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Evidence</div>
          <EvidenceList change={change} />
        </div>

        {change.notes && (
          <div style={{ marginBottom: 4 }}>
            <Field title="Notes">{change.notes}</Field>
          </div>
        )}

        <div style={{ marginTop: 12, fontSize: 11, color: 'var(--muted)' }}>
          Last updated {formatDate(change.updated_at)}
        </div>
      </div>
    </div>
  )
}

function ChangeHistoryTab() {
  const [data, setData] = useState<HipaaComplianceChangeListResponse | null>(null)
  const [session, setSession] = useState(false)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<ComplianceStatus | ''>('')
  const [categoryFilter, setCategoryFilter] = useState<ComplianceControlCategory | ''>('')
  const [selected, setSelected] = useState<HipaaComplianceChange | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    setSession(false)
    setDenied(false)
    fetchHipaaComplianceChanges({
      page, pageSize: PAGE_SIZE,
      status: statusFilter || undefined,
      controlCategory: categoryFilter || undefined,
    })
      .then(setData)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        const kind = classifyAuthError(message)
        if (kind === 'session') setSession(true)
        else if (kind === 'denied') setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [page, statusFilter, categoryFilter])

  const hasActiveFilters = !!(statusFilter || categoryFilter)
  const clearFilters = () => { setStatusFilter(''); setCategoryFilter(''); setPage(1) }

  if (session) return <SessionExpiredState />
  if (denied) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Permission denied"
        description="You don't have manage_all_orgs, so the change history can't be shown here. This is enforced by the backend, not this page."
      />
    )
  }

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <label style={fieldLabel} htmlFor="hipaa-status-filter">Status</label>
            <select
              id="hipaa-status-filter" aria-label="Filter by status" style={selectStyle}
              value={statusFilter} onChange={e => { setStatusFilter(e.target.value as ComplianceStatus | ''); setPage(1) }}
            >
              <option value="">All statuses</option>
              {COMPLIANCE_STATUSES.map(s => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </div>
          <div>
            <label style={fieldLabel} htmlFor="hipaa-category-filter">Control / Category</label>
            <select
              id="hipaa-category-filter" aria-label="Filter by control category" style={selectStyle}
              value={categoryFilter} onChange={e => { setCategoryFilter(e.target.value as ComplianceControlCategory | ''); setPage(1) }}
            >
              <option value="">All categories</option>
              {CONTROL_CATEGORIES.map(c => <option key={c} value={c}>{CONTROL_CATEGORY_LABELS[c]}</option>)}
            </select>
          </div>
          {hasActiveFilters && <Button variant="ghost" onClick={clearFilters}>Clear filters</Button>}
          <ActionToolbar>
            <Button variant="secondary" onClick={load} disabled={loading}>Refresh</Button>
          </ActionToolbar>
        </div>
      </Card>

      {loading && <LoadingState label="Loading change history…" />}
      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          <DataTable
            rowKey={c => c.change_id}
            emptyLabel={hasActiveFilters ? 'No changes match these filters.' : 'No HIPAA compliance changes recorded yet.'}
            rows={data.items}
            columns={[
              { key: 'date', header: 'Date', render: c => formatDateOnly(c.change_date) },
              { key: 'title', header: 'Title', render: c => c.title },
              { key: 'category', header: 'Control / Category', render: c => CONTROL_CATEGORY_LABELS[c.control_category] },
              { key: 'repository', header: 'Repository', render: c => c.repository },
              { key: 'status', header: 'Status', render: c => <StatusBadge status={c.status} /> },
              {
                key: 'details', header: 'Details', render: c => (
                  <button
                    onClick={() => setSelected(c)}
                    style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                  >
                    View →
                  </button>
                ),
              },
            ]}
          />
          <Pagination page={data.page} totalPages={data.total_pages} onPage={setPage} />
        </>
      )}

      {selected && <ChangeDetailModal change={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
