/**
 * Admin Console dual build architecture: main.tsx's safe-failure UI for
 * an unset/unrecognized VITE_APP_MODE. Deliberately a standalone,
 * presentational component (no env-var logic of its own) so it can be
 * unit tested directly -- see UnknownModeNotice.test.tsx -- without
 * touching main.tsx's own top-level `import.meta.env.VITE_APP_MODE`
 * comparison, which stays a direct literal comparison (not routed
 * through a function parameter) so Vite/Rollup can still statically
 * tree-shake the untaken AdminApp/ControlApp branch out of each build.
 */
export default function UnknownModeNotice({ mode }: { mode: string | undefined }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 8,
      background: '#0a0a0a', color: '#ef4444', fontFamily: 'monospace', fontSize: 13,
      textAlign: 'center', padding: 24,
    }}>
      <div style={{ fontWeight: 700, fontSize: 15 }}>Configuration error</div>
      <div>
        VITE_APP_MODE must be set to "admin" or "control" at build time
        (got: {mode === undefined ? 'undefined' : JSON.stringify(mode)}).
      </div>
    </div>
  )
}
