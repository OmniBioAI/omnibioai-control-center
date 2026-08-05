import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  fetchAuditEvents, formatEventType, maskSensitiveFields, KNOWN_EVENT_TYPES,
  type AuditEvent, type AuditEventListResponse,
} from '../../audit'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../../organizations'
import { Card, SectionHeader, LoadingState, ErrorState, EmptyState, ActionToolbar, Button, DataTable } from '../../components/ui'

const PAGE_SIZE = 20

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}
const fieldLabel: React.CSSProperties = { fontSize: 12, fontWeight: 600, color: 'var(--text2)', marginBottom: 4, display: 'block' }

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : '—'
}

// ── Detail modal -- same page-local Modal shape ServiceAccountsPage.tsx
// (PR11.4) and ConfigPage.tsx's AddServiceModal already established;
// audit log entries aren't a manageable resource with their own page,
// so a full navigation (like OrganizationDetailPage/UserDetailPage) is
// the wrong shape here -- this is a record to inspect, not edit. ──────
function EventDetailModal({ event, onClose }: { event: AuditEvent; onClose: () => void }) {
  return (
    <div
      role="dialog"
      aria-label="Audit event detail"
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '20px 22px', width: 520, maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>{formatEventType(event.event_type)}</span>
          <button onClick={onClose} aria-label="Close" style={{ fontSize: 18, color: 'var(--muted)', lineHeight: 1, cursor: 'pointer', background: 'none', border: 'none' }}>×</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14, marginBottom: 16 }}>
          <Field title="Timestamp">{formatDate(event.created_at)}</Field>
          <Field title="Event type"><code style={{ fontSize: 11 }}>{event.event_type}</code></Field>
          <Field title="Actor">{event.actor_email ?? (event.actor_user_id != null ? `User #${event.actor_user_id}` : '—')}</Field>
          <Field title="Target">{event.target_email ?? (event.target_user_id != null ? `User #${event.target_user_id}` : '—')}</Field>
          <Field title="Organization">{event.organization_name ?? (event.organization_id != null ? `Org #${event.organization_id}` : '—')}</Field>
          <Field title="Resource">{event.resource_type ? `${event.resource_type}${event.resource_id ? ` #${event.resource_id}` : ''}` : '—'}</Field>
        </div>

        {event.before_state && (
          <MetadataBlock title="Before" value={maskSensitiveFields(event.before_state)} />
        )}
        {event.after_state && (
          <MetadataBlock title="After" value={maskSensitiveFields(event.after_state)} />
        )}
        {event.metadata && (
          <MetadataBlock title="Metadata" value={maskSensitiveFields(event.metadata)} />
        )}

        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--muted)' }}>
          Sensitive-looking fields (secrets, tokens, hashes) are masked here as a defense-in-depth
          measure -- the backend never writes one into an audit event's metadata in the first place.
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

export default function AuditLogsPage() {
  const [data, setData] = useState<AuditEventListResponse | null>(null)
  const [denied, setDenied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [orgOptions, setOrgOptions] = useState<PlatformOrgSummary[] | null>(null)
  const [orgFilter, setOrgFilter] = useState('')
  const [actorFilter, setActorFilter] = useState('')
  const [eventTypeFilter, setEventTypeFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [selected, setSelected] = useState<AuditEvent | null>(null)

  useEffect(() => {
    fetchPlatformOrgs({ pageSize: 100 }).then(r => setOrgOptions(r.items)).catch(() => setOrgOptions(null))
  }, [])

  const load = () => {
    setLoading(true)
    setError(null)
    setDenied(false)
    fetchAuditEvents({
      page, pageSize: PAGE_SIZE,
      organizationId: orgFilter ? Number(orgFilter) : undefined,
      actorUserId: actorFilter ? Number(actorFilter) : undefined,
      eventType: eventTypeFilter || undefined,
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

  useEffect(load, [page, orgFilter, actorFilter, eventTypeFilter, startDate, endDate])

  const hasActiveFilters = !!(orgFilter || actorFilter || eventTypeFilter || startDate || endDate)
  const clearFilters = () => {
    setOrgFilter(''); setActorFilter(''); setEventTypeFilter(''); setStartDate(''); setEndDate(''); setPage(1)
  }

  return (
    <div>
      <SectionHeader
        title="Audit Logs"
        description="Who changed what, when, and where -- across users, API keys, service accounts, and SSO configuration."
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
          description="You don't have manage_all_orgs, so the audit trail can't be shown here. This is enforced by the backend, not this page."
        />
      ) : (
        <>
          <Card style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <div>
                <label style={fieldLabel} htmlFor="audit-org-filter">Organization</label>
                <select
                  id="audit-org-filter" aria-label="Filter by organization" style={selectStyle}
                  value={orgFilter} onChange={e => { setOrgFilter(e.target.value); setPage(1) }}
                >
                  <option value="">All organizations</option>
                  {orgOptions?.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              </div>
              <div>
                <label style={fieldLabel} htmlFor="audit-event-filter">Event</label>
                <select
                  id="audit-event-filter" aria-label="Filter by event type" style={selectStyle}
                  value={eventTypeFilter} onChange={e => { setEventTypeFilter(e.target.value); setPage(1) }}
                >
                  <option value="">All events</option>
                  {KNOWN_EVENT_TYPES.map(t => <option key={t} value={t}>{formatEventType(t)}</option>)}
                </select>
              </div>
              <div>
                <label style={fieldLabel} htmlFor="audit-actor-filter">Actor user ID</label>
                <input
                  id="audit-actor-filter" aria-label="Filter by actor user ID" style={{ ...selectStyle, width: 120 }}
                  value={actorFilter} onChange={e => { setActorFilter(e.target.value); setPage(1) }}
                  placeholder="e.g. 42" inputMode="numeric"
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="audit-start-date">From</label>
                <input
                  id="audit-start-date" aria-label="Filter from date" type="date" style={selectStyle}
                  value={startDate} onChange={e => { setStartDate(e.target.value); setPage(1) }}
                />
              </div>
              <div>
                <label style={fieldLabel} htmlFor="audit-end-date">To</label>
                <input
                  id="audit-end-date" aria-label="Filter to date" type="date" style={selectStyle}
                  value={endDate} onChange={e => { setEndDate(e.target.value); setPage(1) }}
                />
              </div>
              {hasActiveFilters && (
                <Button variant="ghost" onClick={clearFilters}>Clear filters</Button>
              )}
            </div>
          </Card>

          {loading && <LoadingState label="Loading audit events…" />}
          {!loading && error && <ErrorState message={error} onRetry={load} />}

          {!loading && !error && data && (
            <>
              <DataTable
                rowKey={e => e.id}
                emptyLabel={hasActiveFilters ? 'No audit events match these filters.' : 'No audit events recorded yet.'}
                rows={data.items}
                columns={[
                  { key: 'timestamp', header: 'Timestamp', render: e => formatDate(e.created_at) },
                  { key: 'event', header: 'Event', render: e => formatEventType(e.event_type) },
                  { key: 'actor', header: 'Actor', render: e => e.actor_email ?? (e.actor_user_id != null ? `User #${e.actor_user_id}` : '—') },
                  { key: 'organization', header: 'Organization', render: e => e.organization_name ?? (e.organization_id != null ? `Org #${e.organization_id}` : '—') },
                  { key: 'target', header: 'Target', render: e => e.target_email ?? (e.target_user_id != null ? `User #${e.target_user_id}` : '—') },
                  {
                    key: 'details', header: 'Details', render: e => (
                      <button
                        onClick={() => setSelected(e)}
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

      {selected && <EventDetailModal event={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function Pagination({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  if (totalPages <= 1) return null
  const btnBase: React.CSSProperties = {
    fontSize: 12, fontWeight: 600, padding: '5px 12px', borderRadius: 6,
    border: '1px solid var(--border)', background: 'var(--surface)', cursor: 'pointer',
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, padding: '12px 0' }}>
      <button onClick={() => onPage(page - 1)} disabled={page === 1}
        style={{ ...btnBase, color: page === 1 ? 'var(--muted)' : 'var(--text2)', opacity: page === 1 ? 0.4 : 1 }}>
        ← Prev
      </button>
      <span style={{ fontSize: 12, color: 'var(--muted)', minWidth: 90, textAlign: 'center' }}>
        Page <span style={{ color: 'var(--text)', fontWeight: 700 }}>{page}</span> of {totalPages}
      </span>
      <button onClick={() => onPage(page + 1)} disabled={page === totalPages}
        style={{ ...btnBase, color: page === totalPages ? 'var(--muted)' : 'var(--text2)', opacity: page === totalPages ? 0.4 : 1 }}>
        Next →
      </button>
    </div>
  )
}
