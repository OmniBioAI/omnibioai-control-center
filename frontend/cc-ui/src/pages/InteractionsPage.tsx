import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchInteractions, maskSensitiveFields,
  type Interaction, type InteractionListResponse,
} from '../interactions'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../organizations'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button, DataTable, Pagination } from '../components/ui'
import { formatDate } from '../format'

// PR-B5-B (Control Center Interaction Admin View). Mirrors
// AuditLogsPage.tsx's architecture exactly -- both read a paginated,
// filtered, platform-admin-only (manage_all_orgs) ledger with a
// free-form JSON metadata field, unlike SessionsPage.tsx's self-service,
// unpaginated, filter-less shape (a small, inherently bounded dataset
// Interactions has no equivalent of). See this PR's own report for why
// Audit Logs, not Sessions, is the governing precedent here.
//
// Interaction.status/service/interaction_type have no fixed, backend-
// enforced vocabulary (unlike AuditEvent.event_type, which has a
// maintained KNOWN_EVENT_TYPES list) -- confirmed by reading
// app/db/models.py::Interaction directly, plain unconstrained string
// columns. Free-text filters for all three, not dropdowns: a hardcoded
// vocabulary here (e.g. RAG's current "success"/"error"/"timeout")
// would silently go stale the moment a second producer with different
// values exists, and there is no source of truth to build a dropdown
// from the way KNOWN_EVENT_TYPES / fetchPlatformOrgs provide one for
// event_type / organization_id respectively.

const PAGE_SIZE = 20

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }

// ── Detail modal -- same page-local Modal shape AuditLogsPage.tsx's
// EventDetailModal / SessionsPage.tsx's SessionDetailModal already
// established; an Interaction isn't a manageable resource with its own
// page (a record to inspect, not edit), so a full navigation is the
// wrong shape here, same reasoning EventDetailModal's own comment
// gives. ──────────────────────────────────────────────────────────────
function InteractionDetailModal({ interaction, onClose }: { interaction: Interaction; onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-label="Interaction detail"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 520, maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{interaction.interaction_type}</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, marginBottom: 16 }}>
          <Field title="Timestamp">{formatDate(interaction.created_at)}</Field>
          <Field title="Interaction ID"><code style={{ fontSize: 11 }}>{interaction.interaction_id}</code></Field>
          <Field title="Service">{interaction.service}</Field>
          <Field title="Action">{interaction.action}</Field>
          <Field title="Status">{interaction.status ?? '—'}</Field>
          <Field title="Decision">{interaction.decision ?? '—'}</Field>
          <Field title="Organization">{`Org #${interaction.organization_id}`}</Field>
          <Field title="User">{interaction.user_id != null ? `User #${interaction.user_id}` : '—'}</Field>
          <Field title="Resource">{interaction.resource_type ? `${interaction.resource_type}${interaction.resource_id ? ` #${interaction.resource_id}` : ''}` : '—'}</Field>
          <Field title="Session ID">{interaction.session_id ?? '—'}</Field>
          <Field title="Trace ID">{interaction.trace_id ?? '—'}</Field>
        </div>

        {interaction.metadata && (
          <MetadataBlock title="Metadata" value={maskSensitiveFields(interaction.metadata)} />
        )}

        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>
          Sensitive-looking fields (secrets, tokens, hashes) are masked here as a defense-in-depth
          measure -- the backend never writes one into an interaction's metadata in the first place.
        </div>
      </div>
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

function MetadataBlock({ title, value }: { title: string; value: Record<string, unknown> | null }) {
  if (!value || Object.keys(value).length === 0) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{title}</div>
      <pre style={{
        fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8,
        padding: '8px 10px', overflowX: 'auto', color: 'var(--text2)', margin: 0,
      }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

export default function InteractionsPage() {
  const [data, setData] = useState<InteractionListResponse | null>(null)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [orgOptions, setOrgOptions] = useState<PlatformOrgSummary[] | null>(null)
  const [orgFilter, setOrgFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [serviceFilter, setServiceFilter] = useState('')
  const [interactionTypeFilter, setInteractionTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selected, setSelected] = useState<Interaction | null>(null)

  useEffect(() => {
    fetchPlatformOrgs({ pageSize: 100 }).then(r => setOrgOptions(r.items)).catch(() => setOrgOptions(null))
  }, [])

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    fetchInteractions({
      page, pageSize: PAGE_SIZE,
      organizationId: orgFilter ? Number(orgFilter) : undefined,
      userId: userFilter ? Number(userFilter) : undefined,
      service: serviceFilter || undefined,
      interactionType: interactionTypeFilter || undefined,
      status: statusFilter || undefined,
      startDate: startDate || undefined,
      endDate: endDate || undefined,
    })
      .then(setData)
      .catch((e: unknown) => {
        const message = e instanceof Error ? e.message : String(e)
        if (message.endsWith(' 403')) setDenied(true)
        else setError(message)
      })
      .finally(() => setLoading(false))
  }

  useEffect(load, [page, orgFilter, userFilter, serviceFilter, interactionTypeFilter, statusFilter, startDate, endDate])

  const hasActiveFilters = !!(orgFilter || userFilter || serviceFilter || interactionTypeFilter || statusFilter || startDate || endDate)
  const clearFilters = () => {
    setOrgFilter(''); setUserFilter(''); setServiceFilter(''); setInteractionTypeFilter('')
    setStatusFilter(''); setStartDate(''); setEndDate(''); setPage(1)
  }

  return (
    <div>
      <SectionHeader
        title="Interactions"
        description="Platform activity across services -- RAG queries and other recorded interactions, across every organization."
        actions={
          <ActionToolbar>
            <Button variant="secondary" onClick={load} disabled={loading}>Refresh</Button>
          </ActionToolbar>
        }
      />

      {denied ? (
        <EmptyState
          icon={ShieldAlert}
          title="Permission denied"
          description="You don't have manage_all_orgs, so interaction history can't be shown here. This is enforced by the backend, not this page."
        />
      ) : (
        <>
          <Card style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div>
                <label style={fieldLabel} htmlFor="interactions-org-filter">Organization</label>
                <select
                  id="interactions-org-filter" aria-label="Filter by organization" style={selectStyle}
                  value={orgFilter} onChange={e => { setOrgFilter(e.target.value); setPage(1) }}
                >
                  <option value="">All organizations</option>
                  {orgOptions?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-user-filter">User ID</label>
                <input
                  id="interactions-user-filter" aria-label="Filter by user ID" style={{ ...selectStyle, width: 100 }}
                  value={userFilter} onChange={e => { setUserFilter(e.target.value); setPage(1) }}
                  placeholder="e.g. 42" inputMode="numeric"
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-service-filter">Service</label>
                <input
                  id="interactions-service-filter" aria-label="Filter by service" style={{ ...selectStyle, width: 120 }}
                  value={serviceFilter} onChange={e => { setServiceFilter(e.target.value); setPage(1) }}
                  placeholder="e.g. rag"
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-type-filter">Interaction type</label>
                <input
                  id="interactions-type-filter" aria-label="Filter by interaction type" style={{ ...selectStyle, width: 140 }}
                  value={interactionTypeFilter} onChange={e => { setInteractionTypeFilter(e.target.value); setPage(1) }}
                  placeholder="e.g. query"
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-status-filter">Status</label>
                <input
                  id="interactions-status-filter" aria-label="Filter by status" style={{ ...selectStyle, width: 120 }}
                  value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
                  placeholder="e.g. success"
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-start-date">From</label>
                <input
                  id="interactions-start-date" aria-label="Filter from date" type="date" style={selectStyle}
                  value={startDate} onChange={e => { setStartDate(e.target.value); setPage(1) }}
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="interactions-end-date">To</label>
                <input
                  id="interactions-end-date" aria-label="Filter to date" type="date" style={selectStyle}
                  value={endDate} onChange={e => { setEndDate(e.target.value); setPage(1) }}
                />
              </div>
              {hasActiveFilters && (
                <Button variant="ghost" onClick={clearFilters}>Clear filters</Button>
              )}
            </div>
          </Card>

          {loading && <LoadingState label="Loading interactions…" />}
          {!loading && error && <ErrorState message={error} onRetry={load} />}

          {!loading && !error && data && (
            <>
              <DataTable
                rowKey={i => i.id}
                emptyLabel={hasActiveFilters ? 'No interactions match these filters.' : 'No interactions recorded yet.'}
                rows={data.items}
                columns={[
                  { key: 'interaction_type', header: 'Interaction Type', render: i => i.interaction_type },
                  { key: 'action', header: 'Action', render: i => i.action },
                  { key: 'status', header: 'Status', render: i => i.status ?? '—' },
                  { key: 'organization', header: 'Organization', render: i => `Org #${i.organization_id}` },
                  { key: 'user', header: 'User', render: i => i.user_id != null ? `User #${i.user_id}` : '—' },
                  {
                    key: 'details', header: 'Details', render: i => (
                      <button
                        onClick={() => setSelected(i)}
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
        </>
      )}

      {selected && <InteractionDetailModal interaction={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
