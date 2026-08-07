import { useCallback, useEffect, useState } from 'react'
import {
  authMethodLabel, fetchPlatformUsers,
  type PlatformUserListResponse, type UserSortField, type SortOrder,
} from '../users'
import { fetchPlatformOrgs, type PlatformOrgSummary } from '../organizations'
import { fetchPlatformRoles, type RoleSummary } from '../roles'
import StatusBadge from '../components/StatusBadge'
import { LoadingState, ErrorState, EmptyState, Pagination } from '../components/ui'
import { formatDateTime } from '../format'

/* ── Shared visual language (matches OrganizationsPage.tsx/DockerPage.tsx) ── */
const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center',
  justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
}
const th: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, color: 'var(--muted)',
  textTransform: 'uppercase', letterSpacing: '0.07em',
  padding: '9px 14px', borderBottom: '1px solid var(--border)',
  textAlign: 'left', background: 'rgba(255,255,255,0.03)', whiteSpace: 'nowrap',
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
  field: UserSortField
  label: string
  sortBy: UserSortField
  sortOrder: SortOrder
  onSort: (field: UserSortField) => void
}) {
  const active = sortBy === field
  return (
    <th style={thSortable} onClick={() => onSort(field)} role="columnheader" aria-sort={active ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}>
      {label} {active ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
    </th>
  )
}

const PAGE_SIZE = 20
const ALL_STATUSES = ['active', 'suspended']

interface Props {
  onSelect: (userId: number) => void
}

// Platform-admin only -- there is no org-admin variant of this page.
// Org-admins already have their own org's member list via the existing
// GET /orgs/{org_id}/members (Phase 1), unrelated to this new, platform-
// wide, cross-tenant directory.
export default function UsersPage({ onSelect }: Props) {
  const [data, setData] = useState<PlatformUserListResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<UserSortField>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  // PR11.1: filter toolbar state. Each is `''` when "All" is selected --
  // fetchPlatformUsers only sets the corresponding query param when
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

  const load = useCallback(() => {
    setLoading(true)
    fetchPlatformUsers({
      page, pageSize: PAGE_SIZE, search, sortBy, sortOrder,
      organizationId: orgFilter ? Number(orgFilter) : undefined,
      status: statusFilter || undefined,
      role: roleFilter || undefined,
    })
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [page, search, sortBy, sortOrder, orgFilter, statusFilter, roleFilter])

  useEffect(() => { load() }, [load])

  const handleSort = (field: UserSortField) => {
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

  const hasActiveFilters = !!(search || orgFilter || statusFilter || roleFilter)

  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Users</h2>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Every user in the system. This view is only reachable with platform-admin permissions,
        enforced by the backend on every request.
      </p>

      <form
        onSubmit={submitSearch}
        style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}
      >
        <input
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Search by email…"
          aria-label="Search users"
          style={{
            flex: 1, minWidth: 200, maxWidth: 420, fontSize: 13, padding: '8px 12px',
            borderRadius: 8, border: '1px solid var(--border)',
            background: 'var(--surface)', color: 'var(--text)',
          }}
        />
        <button type="submit" style={{
          fontSize: 13, fontWeight: 600, padding: '8px 16px', borderRadius: 8,
          border: 'none', background: 'var(--accent)', color: '#000', cursor: 'pointer',
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
        <div style={card}>
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
