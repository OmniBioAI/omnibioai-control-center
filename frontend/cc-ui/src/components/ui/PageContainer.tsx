import type { ReactNode } from 'react'

/**
 * Admin Console Phase 2 design system: the max-width/centering/padding
 * wrapper every page's content sits in. Extracted from what AdminApp.tsx
 * already inlined once (`maxWidth: 1280, margin: '0 auto', padding: '24px
 * 28px 48px'`) -- new pages (Overview, ComingSoon destinations) use this;
 * existing pages are untouched and keep their own markup exactly as
 * before, since AppShell still wraps the same content area they already
 * rendered into.
 */
export default function PageContainer({ children }: { children: ReactNode }) {
  return (
    <div className="shell-content" style={{ maxWidth: 1280, margin: '0 auto', padding: '24px 28px 48px' }}>
      {children}
    </div>
  )
}
