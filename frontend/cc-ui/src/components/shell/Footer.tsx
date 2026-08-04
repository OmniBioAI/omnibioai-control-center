/** Admin Console Phase 2: minimal status/version footer. */
export default function Footer() {
  return (
    <footer
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 24px', borderTop: '1px solid var(--border)',
        fontSize: 11, color: 'var(--muted)', flexShrink: 0,
      }}
    >
      <span>OmniBioAI Admin Console</span>
      <span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)' }} />
          Connected
        </span>
      </span>
    </footer>
  )
}
