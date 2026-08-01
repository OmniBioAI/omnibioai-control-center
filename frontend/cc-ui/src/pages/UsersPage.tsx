import { useCallback, useEffect, useState } from 'react'
import { fetchPlatformUsers, type PlatformUserListResponse, type UserSortField, type SortOrder } from '../users'
import StatusBadge from '../components/StatusBadge'

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

function Loading({ msg }: { msg: string }) {
  return <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>{msg}</div>
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div role="alert" style={{
      padding: '10px 14px', marginBottom: 14, borderRadius: 8,
      background: 'var(--red-bg)', border: '1px solid var(--red-border, var(--red))',
      color: 'var(--red)', fontSize: 12,
    }}>
      {msg}
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

  const load = useCallback(() => {
    setLoading(true)
    fetchPlatformUsers({ page, pageSize: PAGE_SIZE, search, sortBy, sortOrder })
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [page, search, sortBy, sortOrder])

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

  return (
    <div>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>Users</h2>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 20 }}>
        Every user in the system. This view is only reachable with platform-admin permissions,
        enforced by the backend on every request.
      </p>

      <form onSubmit={submitSearch} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Search by email…"
          aria-label="Search users"
          style={{
            flex: 1, maxWidth: 420, fontSize: 13, padding: '8px 12px',
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
      </form>

      {err && <ErrBox msg={err} />}

      {loading ? <Loading msg="Loading users…" /> : (
        <div style={card}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>All Users</span>
            {data && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{data.total} total</span>}
          </div>
          {!data?.items.length ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
              {search ? `No users match "${search}"` : 'No users exist yet.'}
            </div>
          ) : (
            <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <SortHeader field="email" label="Email" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <SortHeader field="status" label="Status" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <th style={th}>Global Roles</th>
                  <th style={th}>Organizations</th>
                  <SortHeader field="created_at" label="Created" sortBy={sortBy} sortOrder={sortOrder} onSort={handleSort} />
                  <th style={th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(u => (
                  <tr key={u.id} style={{ cursor: 'pointer' }} onClick={() => onSelect(u.id)} data-testid={`user-row-${u.id}`}>
                    <td style={{ ...td, color: 'var(--text)', fontWeight: 600 }}>{u.email}</td>
                    <td style={td}><StatusBadge status={u.status} /></td>
                    <td style={td}>{u.global_roles.length ? u.global_roles.join(', ') : '—'}</td>
                    <td style={td}>{u.org_count}</td>
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
