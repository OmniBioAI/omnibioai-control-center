import { useCallback, useEffect, useState } from 'react'
import {
  authMethodLabel, fetchManagedUsers, managedUsersCsv,
  type ManagedUserListResponse, type ManagedUser, type ManagedUserSort, type SortOrder,
} from '../users'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../organizations'
import { fetchPlatformRoles, type RoleSummary } from '../roles'
import StatusBadge from '../components/StatusBadge'
import { LoadingState, ErrorState, EmptyState, Pagination } from '../components/ui'
import { formatDateTime } from '../format'
import { fetchTenantSummary, type TenantQuery, type TenantSummary } from '../tenants'
import { TenantSummaryCards, Filter, PlanCell, Usage, date, validUntil } from './tenants/TenantManagementPage'

/* ── Shared visual language (matches OrganizationsPage.tsx/DockerPage.tsx) ── */
const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid var(--border)',
  background: 'color-mix(in srgb, var(--color-text) 3%, transparent)', display: 'flex', alignItems: 'center',
  justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
}
const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid var(--border)',
  textAlign: 'left', background: 'color-mix(in srgb, var(--color-text) 3%, transparent)', whiteSpace: 'nowrap',
}
const thSortable: React.CSSProperties = { ...th, cursor: 'pointer', userSelect: 'none' }
const td: React.CSSProperties = {
  fontSize: 12, color: 'var(--text2)', padding: '10px 14px',
  borderBottom: '1px solid var(--border)', verticalAlign: 'middle',
}
const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '7px 10px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)',
}

function SortHeader({
  field, label, sortBy, sortOrder, onSort,
}: {
  field: ManagedUserSort
  label: string
  sortBy: ManagedUserSort
  sortOrder: SortOrder
  onSort: (field: ManagedUserSort) => void
}) {
  const active = sortBy === field
  return (
    <th style={thSortable} role="columnheader" aria-sort={active ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => onSort(field)}>{label} {active ? (sortOrder === 'asc' ? '▲' : '▼') : ''}</button>
    </th>
  )
}

const PAGE_SIZE = 50
const ALL_STATUSES = ['active', 'suspended']

interface Props {
  onSelect: (userId: number) => void
}

// Platform-admin only -- there is no org-admin variant of this page.
// Org-admins already have their own org's member list via the existing
// GET /orgs/{org_id}/members (Phase 1), unrelated to this new, platform-
// wide, cross-tenant directory.
export default function UsersPage({ onSelect }: Props) {
  const [data, setData] = useState<ManagedUserListResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [tenantFilters, setTenantFilters] = useState<TenantQuery>({})
  const [summary, setSummary] = useState<TenantSummary | null>(null)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [reload, setReload] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<ManagedUserSort>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  // PR11.1: filter toolbar state. Each is `''` when "All" is selected --
  // fetchManagedUsers only sets the corresponding query param when
  // truthy, so this stays backward compatible with the unfiltered call.
  const [orgFilter, setOrgFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [orgOptions, setOrgOptions] = useState<PlatformOrgSummary[] | null>(null)
  const [roleOptions, setRoleOptions] = useState<RoleSummary[] | null>(null)

  useEffect(() => {
    // Best-effort: if either catalog fails to load, its filter dropdown
    // just doesn't render (see below) -- the page itself still works.
    fetchPlatformOrgs({ pageSize: 100 }).then(r => setOrgOptions(r.items)).catch(() => setOrgOptions(null))
    fetchPlatformRoles().then(setRoleOptions).catch(() => setRoleOptions(null))
  }, [])

  const query = { page, pageSize: PAGE_SIZE, search, sortBy, sortOrder,
    organizationId: orgFilter ? Number(orgFilter) : undefined,
    status: statusFilter || undefined, role: roleFilter || undefined, tenant: tenantFilters }
  const load = useCallback(() => setReload(value => value + 1), [])
  useEffect(() => {
    let cancelled = false
    fetchTenantSummary().then(value => { if (!cancelled) { setSummary(value); setSummaryError(null) } })
      .catch(error => { if (!cancelled) setSummaryError(String(error)) })
    return () => { cancelled = true }
  }, [reload])
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let retries = 0
    const request = async () => {
      setLoading(true)
      try {
        const result = await fetchManagedUsers(query)
        if (!cancelled) { setData(result); setErr(null); setLoading(false) }
      } catch (error) {
        if (cancelled) return
        if ((error as { status?: number }).status === 503 && retries++ < 30) {
          timer = setTimeout(request, 2000)
        } else { setErr(String(error)); setLoading(false) }
      }
    }
    void request()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [page, search, sortBy, sortOrder, orgFilter, statusFilter, roleFilter, tenantFilters, reload])

  const updateTenantFilter = (key: keyof TenantQuery, value: string) => {
    setTenantFilters(previous => ({ ...previous, [key]: value }))
    setPage(1)
  }
  const exportCsv = async () => {
    setExporting(true)
    try {
      const rows: ManagedUser[] = []
      for (let page = 1; ; page++) {
        const batch = await fetchManagedUsers({ ...query, page, pageSize: 200 })
        rows.push(...batch.items)
        if (!batch.items.length || page >= batch.total_pages) break
      }
      const url = URL.createObjectURL(new Blob([managedUsersCsv(rows)], { type: 'text/csv;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url; link.download = 'users.csv'; link.click()
      URL.revokeObjectURL(url)
    } catch (error) { setErr(`Export failed: ${String(error)}`) }
    finally { setExporting(false) }
  }

  const handleSort = (field: ManagedUserSort) => {
    if (field === sortBy) {
      setSortOrder(o => (o === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(field)
      setSortOrder('asc')
    }
    setPage(1)
  }

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setPage(1)
    setSearch(searchInput.trim())
  }

  const hasActiveFilters = !!(search || orgFilter || statusFilter || roleFilter || Object.values(tenantFilters).some(Boolean))

  return (
    <div>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Users</h1>
      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 20 }}>
        Every user in the system. This view is only reachable with platform-admin permissions,
        enforced by the backend on every request.
      </p>

      {summary && <TenantSummaryCards summary={summary} />}
      {summaryError && <div role="alert">Summary unavailable. <button onClick={load}>Retry summary</button></div>}
      <button disabled={exporting || loading} onClick={() => void exportCsv()}>{exporting ? 'Exporting…' : 'Export current filter'}</button>
      <div className="tenant-filter-card">
        <Filter label="Plan" value={tenantFilters.plan ?? ''} options={['free', 'plus', 'pro']} onChange={v => updateTenantFilter('plan', v)} />
        <Filter label="Plan source" value={tenantFilters.plan_source ?? ''} options={['stripe', 'promo', 'free']} labels={{ stripe: 'Paid', promo: 'Promo', free: 'Free' }} onChange={v => updateTenantFilter('plan_source', v)} />
        <Filter label="Membership" value={tenantFilters.status ?? ''} options={['active', 'trialing', 'past_due', 'canceled', 'none']} onChange={v => updateTenantFilter('status', v)} />
        <Filter label="Validity" value={tenantFilters.validity ?? ''} options={['expiring_7d', 'expiring_30d', 'expired']} onChange={v => updateTenantFilter('validity', v)} />
        <Filter label="Storage" value={tenantFilters.storage_status ?? ''} options={['ok', 'near', 'over_allocation']} onChange={v => updateTenantFilter('storage_status', v)} />
      </div>
      <form
        onSubmit={submitSearch}
        style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}
      >
        <input
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Search username, email, or ID…"
          aria-label="Search users"
          style={{
            flex: 1, minWidth: 200, maxWidth: 420, fontSize: 13, padding: '8px 12px',
            borderRadius: 8, border: '1px solid var(--border)',
            background: 'var(--surface)', color: 'var(--text)',
          }}
        />
        <button type="submit" style={{
          fontSize: 13, fontWeight: 600, padding: '8px 16px', borderRadius: 8,
          border: 'none', background: 'var(--accent)', color: 'var(--color-on-accent)', cursor: 'pointer',
        }}>
          Search
        </button>

        {orgOptions && (
          <select
            aria-label="Filter by organization"
            value={orgFilter}
            onChange={e => { setOrgFilter(e.target.value); setPage(1) }}
            style={selectStyle}
          >
            <option value="">All organizations</option>
            {orgOptions.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        )}

        <select
          aria-label="Filter by status"
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
          style={selectStyle}
        >
          <option value="">All statuses</option>
          {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        {roleOptions && (
          <select
            aria-label="Filter by role"
            value={roleFilter}
            onChange={e => { setRoleFilter(e.target.value); setPage(1) }}
            style={selectStyle}
          >
            <option value="">All roles</option>
            {roleOptions.map(r => <option key={r.id} value={r.name}>{r.name}</option>)}
          </select>
        )}
      </form>

      {err && <div role="alert" style={{ marginBottom: 14 }}><ErrorState message={err} onRetry={load} /></div>}

      {loading ? <LoadingState label="Loading users…" /> : (
        <div style={{ ...card, overflowX: 'auto' }}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>All Users</span>
            {data && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{data.total} total</span>}
          </div>
          {!data?.items.length ? (
            <EmptyState
              title={hasActiveFilters ? 'No users match these filters' : 'No users exist yet.'}
              description={hasActiveFilters ? 'Try clearing the search or filters above.' : undefined}
            />
          ) : (
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <SortHeader field="email" label="Email" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <SortHeader field="status" label="Status" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <th style={th}>Global Roles</th>
                  <th style={th}>Organizations</th>
                  <th style={th}>Last Login</th>
                  <th style={th}>Auth Method</th>
                  <SortHeader field="created_at" label="Created" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <SortHeader field="effective_plan_id" label="Plan" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <SortHeader field="pct" label="Used / Allocated" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <SortHeader field="valid_until" label="Valid until" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <th style={th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(u => (
                  <tr
                    key={u.id}
                    style={{ cursor: 'pointer' }}
                    onClick={() => onSelect(u.id)}
                    // PR E2: additive keyboard-accessibility fix -- this
                    // row was mouse-only before (no role, no tabIndex, no
                    // key handler), same gap OrganizationTable.tsx's
                    // equivalent row still has. onClick above is
                    // unchanged; this only adds an equivalent path.
                    role="button"
                    tabIndex={0}
                    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(u.id) } }}
                    aria-label={`View user ${u.email}`}
                    data-testid={`user-row-${u.id}`}
                  >
                    <td style={{ ...td, color: 'var(--text)', fontWeight: 600 }}>{u.email}</td>
                    <td style={td}><StatusBadge status={u.status} /></td>
                    <td style={td}>{u.global_roles.length ? u.global_roles.join(', ') : '—'}</td>
                    <td style={td}>{u.org_count}</td>
                    <td style={td}>{formatDateTime(u.last_login_at)}</td>
                    <td style={td}>{authMethodLabel(u.authentication_method)}</td>
                    <td style={td}>{u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}</td>
                    <td style={td}>{u.effective_plan_id ? <PlanCell row={u} /> : '—'}</td>
                    <td style={td}>{u.allocated_bytes != null ? <Usage row={u} /> : '—'}</td>
                    <td style={td}>{u.effective_plan_id ? date(validUntil(u)) : '—'}</td>
                    <td style={td}>
                      <button
                        onClick={e => { e.stopPropagation(); onSelect(u.id) }}
                        style={{
                          fontSize: 11, fontWeight: 600, padding: '4px 10px', borderRadius: 6,
                          border: '1px solid var(--border)', background: 'transparent',
                          color: 'var(--text2)', cursor: 'pointer',
                        }}
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {data && <Pagination page={data.page} totalPages={data.total_pages} onPage={setPage} />}
    </div>
  )
}
