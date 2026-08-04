/** Admin Console Phase 2 design system: generic in-page loading
 * indicator -- new pages should use this instead of a bespoke "Loading…"
 * string, for visual consistency. */
export default function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
      padding: '48px 24px', color: 'var(--muted)', fontSize: 13,
    }}>
      <span style={{
        width: 14, height: 14, borderRadius: '50%',
        border: '2px solid var(--border)', borderTopColor: 'var(--accent)',
        animation: 'spin 0.8s linear infinite', flexShrink: 0,
      }} />
      {label}
    </div>
  )
}
