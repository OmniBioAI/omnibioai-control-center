import { Search } from 'lucide-react'

/**
 * Admin Console Phase 2: global search placeholder, per this phase's
 * explicit scope -- a real visual presence in the shell, deliberately
 * non-functional (disabled input, no search implementation) rather than
 * a fake box that silently does nothing when a user types into it.
 */
export default function GlobalSearch() {
  return (
    <div
      className="shell-topbar-search"
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
        padding: '6px 10px', background: 'var(--bg2)', color: 'var(--muted)',
        width: 220,
      }}
    >
      <Search size={14} />
      <input
        disabled
        placeholder="Search (coming soon)"
        title="Global search is not implemented yet"
        style={{
          border: 'none', background: 'transparent', color: 'var(--muted)',
          fontSize: 12, width: '100%', cursor: 'not-allowed',
        }}
      />
    </div>
  )
}
