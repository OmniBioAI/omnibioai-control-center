import type { OrgSortField, SortOrder } from '../../organizations'
import OrganizationStatusBadge from './OrganizationStatusBadge'

// Shared by both audiences (OrganizationsPage decides which data source
// feeds it): a platform admin's row comes from GET /platform/orgs
// (PlatformOrgSummary -- owner/counts/sso included), an org admin's row
// comes from GET /orgs (MyOrg -- id/slug/name/plan/status only, per
// OrganizationOut's existing, unchanged response shape). Optional fields
// below are simply omitted from the org-admin's own row objects rather
// than faked -- `richColumns=false` then hides those columns entirely
// instead of rendering a column full of placeholder dashes.
export interface OrganizationTableRow {
  id: number
  name: string
  slug?: string
  plan?: string
  status: string
  ownerEmail?: string | null
  memberCount?: number
  teamCount?: number
  apiKeyCount?: number
  oauthClientCount?: number
  licenseCount?: number
  ssoEnabled?: boolean
  createdAt?: string | null
}

interface Props {
  rows: OrganizationTableRow[]
  onSelect: (id: number) => void
  richColumns: boolean
  sortBy?: OrgSortField
  sortOrder?: SortOrder
  onSort?: (field: OrgSortField) => void
}

const th: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: 'var(--muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.07em',
  padding: '9px 14px',
  borderBottom: '1px solid var(--border)',
  textAlign: 'left',
  background: 'rgba(255,255,255,0.03)',
  whiteSpace: 'nowrap',
}
const thSortable: React.CSSProperties = { ...th, cursor: 'pointer', userSelect: 'none' }
const td: React.CSSProperties = {
  fontSize: 12,
  color: 'var(--text2)',
  padding: '10px 14px',
  borderBottom: '1px solid var(--border)',
  verticalAlign: 'middle',
}
const rowStyle: React.CSSProperties = { cursor: 'pointer' }

function SortHeader({
  field,
  label,
  sortBy,
  sortOrder,
  onSort,
}: {
  field: OrgSortField
  label: string
  sortBy?: OrgSortField
  sortOrder?: SortOrder
  onSort?: (field: OrgSortField) => void
}) {
  if (!onSort) return <th style={th}>{label}</th>
  const active = sortBy === field
  return (
    <th style={thSortable} onClick={() => onSort(field)} role="columnheader" aria-sort={active ? (sortOrder === 'asc' ? 'ascending' : 'descending') : 'none'}>
      {label} {active ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
    </th>
  )
}

export default function OrganizationTable({ rows, onSelect, richColumns, sortBy, sortOrder, onSort }: Props) {
  return (
    <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <SortHeader field="name" label="Name" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          <th style={th}>Slug</th>
          <th style={th}>Plan</th>
          <SortHeader field="status" label="Status" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          {richColumns && (
            <SortHeader field="owner_email" label="Owner" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          )}
          {richColumns && <th style={th}>Members</th>}
          {richColumns && <th style={th}>Teams</th>}
          {richColumns && <th style={th}>API Keys</th>}
          {richColumns && <th style={th}>OAuth Clients</th>}
          {richColumns && <th style={th}>SSO</th>}
          {richColumns && (
            <SortHeader field="created_at" label="Created" sortBy={sortBy} sortOrder={sortOrder} onSort={onSort} />
          )}
          <th style={th}>Actions</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(row => (
          <tr
            key={row.id}
            style={rowStyle}
            onClick={() => onSelect(row.id)}
            // PR E2: additive keyboard-accessibility fix, same as
            // UsersPage.tsx's equivalent row -- a keyboard path already
            // existed via the Actions column's real <button> below, but
            // making the row itself focusable/actionable doesn't rely on
            // a caller discovering that button first. onClick above is
            // unchanged; this only adds an equivalent path.
            role="button"
            tabIndex={0}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(row.id) } }}
            aria-label={`View organization ${row.name}`}
            data-testid={`org-row-${row.id}`}
          >
            <td style={{ ...td, color: 'var(--text)', fontWeight: 600 }}>{row.name}</td>
            <td style={{ ...td, fontFamily: 'var(--mono)', fontSize: 11 }}>{row.slug ?? '—'}</td>
            <td style={td}>{row.plan ?? '—'}</td>
            <td style={td}>
              <OrganizationStatusBadge status={row.status} />
            </td>
            {richColumns && <td style={td}>{row.ownerEmail ?? '—'}</td>}
            {richColumns && <td style={td}>{row.memberCount ?? '—'}</td>}
            {richColumns && <td style={td}>{row.teamCount ?? '—'}</td>}
            {richColumns && <td style={td}>{row.apiKeyCount ?? '—'}</td>}
            {richColumns && <td style={td}>{row.oauthClientCount ?? '—'}</td>}
            {richColumns && (
              <td style={td}>
                {row.ssoEnabled ? (
                  <span style={{ color: 'var(--color-success)', fontWeight: 700 }}>Enabled</span>
                ) : (
                  <span style={{ color: 'var(--muted)' }}>Disabled</span>
                )}
              </td>
            )}
            {richColumns && (
              <td style={td}>{row.createdAt ? new Date(row.createdAt).toLocaleDateString() : '—'}</td>
            )}
            <td style={td}>
              <button
                onClick={e => {
                  e.stopPropagation()
                  onSelect(row.id)
                }}
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '4px 10px',
                  borderRadius: 6,
                  border: '1px solid var(--border)',
                  background: 'transparent',
                  color: 'var(--text2)',
                  cursor: 'pointer',
                }}
              >
                View
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
