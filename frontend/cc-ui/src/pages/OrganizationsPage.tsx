import { useCallback, useEffect, useState } from 'react'
import {
  createOrganization,
  fetchMyOrgs,
  fetchPlatformOrgs,
  type MyOrg,
  type OrgSortField,
  type PlatformOrgListResponse,
  type SortOrder,
} from '../organizations'
import { hasPlatformAdminAccess } from '../auth'
import OrganizationTable, { type OrganizationTableRow } from '../components/organizations/OrganizationTable'

/* ── Shared visual language (matches DockerPage.tsx/ConfigPage.tsx) ──── */
const card: React.CSSProperties = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
}
const cardHead: React.CSSProperties = {
  padding: '11px 18px', borderBottom: '1px solid var(--border)',
  background: 'rgba(255,255,255,0.03)', display: 'flex', alignItems: 'center',
  justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
}

function Loading({ msg }: { msg: string }) {
  return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>{msg}</div>
  )
}

function ErrBox({ msg }: { msg: string }) {
  return (
    <div
      role="alert"
      style={{
        padding: '10px 14px', marginBottom: 14, borderRadius: 8,
        background: 'var(--red-bg)', border: '1px solid var(--red-border, var(--red))',
        color: 'var(--red)', fontSize: 12,
      }}
    >
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

interface Props {
  onSelect: (orgId: number) => void
}

interface ViewProps extends Props {
  refreshSignal: number
}

const PAGE_SIZE = 20

/* ── Create Organization: POST /orgs already exists and requires no
   permission beyond being an authenticated user (any caller becomes the
   new org's org_admin) -- reused as-is, no duplicate endpoint. Shown to
   both audiences for the same reason the backend imposes no extra
   restriction here. ───────────────────────────────────────────────── */
function CreateOrgForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await createOrganization(name.trim(), slug.trim())
      setOpen(false)
      setName('')
      setSlug('')
      onCreated()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          fontSize: 13, fontWeight: 600, padding: '8px 16px', borderRadius: 8,
          border: 'none', background: 'var(--accent)', color: '#000', cursor: 'pointer',
        }}
      >
        + New Organization
      </button>
    )
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      {err && <div style={{ width: '100%' }}><ErrBox msg={err} /></div>}
      <input
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder="Organization name"
        aria-label="Organization name"
        required
        style={{ fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)' }}
      />
      <input
        value={slug}
        onChange={e => setSlug(e.target.value)}
        placeholder="slug"
        aria-label="Organization slug"
        required
        style={{ fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)' }}
      />
      <button type="submit" disabled={busy} style={{
        fontSize: 13, fontWeight: 600, padding: '8px 16px', borderRadius: 8,
        border: 'none', background: 'var(--accent)', color: '#000', cursor: busy ? 'not-allowed' : 'pointer',
      }}>
        {busy ? 'Creating…' : 'Create'}
      </button>
      <button type="button" onClick={() => setOpen(false)} disabled={busy} style={{
        fontSize: 13, fontWeight: 600, padding: '8px 16px', borderRadius: 8,
        border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer',
      }}>
        Cancel
      </button>
    </form>
  )
}

/* ── Platform-admin view: GET /platform/orgs -- paginated, searchable,
   sortable, cross-tenant. ──────────────────────────────────────────── */
function PlatformOrgsView({ onSelect, refreshSignal }: ViewProps) {
  const [data, setData] = useState<PlatformOrgListResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<OrgSortField>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  const load = useCallback(() => {
    setLoading(true)
    fetchPlatformOrgs({ page, pageSize: PAGE_SIZE, search, sortBy, sortOrder })
      .then(d => { setData(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [page, search, sortBy, sortOrder, refreshSignal])

  useEffect(() => { load() }, [load])

  const handleSort = (field: OrgSortField) => {
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

  const rows: OrganizationTableRow[] = (data?.items ?? []).map(o => ({
    id: o.id,
    name: o.name,
    status: o.status,
    ownerEmail: o.owner_email,
    memberCount: o.member_count,
    teamCount: o.team_count,
    apiKeyCount: o.api_key_count,
    oauthClientCount: o.oauth_client_count,
    licenseCount: o.license_count,
    ssoEnabled: o.sso_enabled,
    createdAt: o.created_at,
  }))

  return (
    <div>
      <form onSubmit={submitSearch} style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          placeholder="Search by organization name or owner email…"
          aria-label="Search organizations"
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

      {loading ? <Loading msg="Loading organizations…" /> : (
        <div style={card}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>All Organizations</span>
            {data && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{data.total} total</span>}
          </div>
          {!rows.length ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
              {search ? `No organizations match "${search}"` : 'No organizations exist yet.'}
            </div>
          ) : (
            <OrganizationTable
              rows={rows}
              onSelect={onSelect}
              richColumns
              sortBy={sortBy}
              sortOrder={sortOrder}
              onSort={handleSort}
            />
          )}
        </div>
      )}
      {data && <Pagination page={data.page} totalPages={data.total_pages} onPage={setPage} />}
    </div>
  )
}

/* ── Org-admin view: GET /orgs -- only orgs the caller actually belongs
   to. No search/sort/pagination controls: this list is never large
   (a handful of memberships at most), and per PR2's security review, a
   client-side search box here must never be mistaken for the tenant-
   isolation boundary -- the boundary is that /orgs itself never returns
   another org in the first place. No org switcher exists separately from
   this table: if a caller belongs to more than one org, they're all just
   rows here. ──────────────────────────────────────────────────────────── */
function MyOrgsView({ onSelect, refreshSignal }: ViewProps) {
  const [orgs, setOrgs] = useState<MyOrg[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchMyOrgs()
      .then(d => { setOrgs(d); setErr(null) })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [refreshSignal])

  const rows: OrganizationTableRow[] = (orgs ?? []).map(o => ({
    id: o.id, name: o.name, slug: o.slug, plan: o.plan, status: o.status,
  }))

  return (
    <div>
      {err && <ErrBox msg={err} />}
      {loading ? <Loading msg="Loading your organizations…" /> : (
        <div style={card}>
          <div style={cardHead}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Your Organizations</span>
          </div>
          {!rows.length ? (
            <div style={{ padding: 24, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
              You don't belong to any organization yet.
            </div>
          ) : (
            <OrganizationTable rows={rows} onSelect={onSelect} richColumns={false} />
          )}
        </div>
      )}
    </div>
  )
}

export default function OrganizationsPage({ onSelect }: Props) {
  // Evaluated once per mount, not memoized across the whole session --
  // hasPlatformAdminAccess() reads the live cached session claims, so a
  // token refresh that changes manage_all_orgs (PR0.2 x PR0.4) is
  // reflected on next visit to this page, not stuck at login-time state.
  const [isPlatformAdmin] = useState(() => hasPlatformAdminAccess())
  const [refreshSignal, setRefreshSignal] = useState(0)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, marginBottom: 4 }}>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>Organizations</h2>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
            {isPlatformAdmin
              ? 'Every organization in the system. This view is only reachable with platform-admin permissions, enforced by the backend on every request.'
              : 'Organizations you belong to.'}
          </p>
        </div>
        <CreateOrgForm onCreated={() => setRefreshSignal(s => s + 1)} />
      </div>
      <div style={{ marginTop: 20 }}>
        {isPlatformAdmin
          ? <PlatformOrgsView onSelect={onSelect} refreshSignal={refreshSignal} />
          : <MyOrgsView onSelect={onSelect} refreshSignal={refreshSignal} />}
      </div>
    </div>
  )
}
