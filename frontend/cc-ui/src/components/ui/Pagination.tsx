// PR E2 (Admin Console Enterprise UX Hardening): extracted from what
// was previously four independent, byte-for-byte identical copies
// (OrganizationsPage.tsx, UsersPage.tsx, AuditLogsPage.tsx,
// BillingPage.tsx) -- confirmed identical by direct comparison before
// extraction, not assumed. Same markup, same styles, same behavior;
// this file changes where it lives, not what it renders.
interface Props {
  page: number
  totalPages: number
  onPage: (p: number) => void
}

export default function Pagination({ page, totalPages, onPage }: Props) {
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
