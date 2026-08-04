import type { ReactNode } from 'react'

interface Props {
  title: string
  description?: string
  children: ReactNode
}

/** PR10 (Live Platform Dashboard): one section of the Overview page --
 * a small heading followed by a responsive card grid. Every dashboard
 * section (Identity, AI Platform, Knowledge Platform, Workflow Platform,
 * Infrastructure, Operations, Business) is one of these; a future module
 * adds a new section by rendering one more <DashboardGrid>, not by
 * inventing its own layout. */
export default function DashboardGrid({ title, description, children }: Props) {
  return (
    <section style={{ marginBottom: 28 }}>
      <div style={{ marginBottom: 12 }}>
        <h2 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.01em' }}>
          {title}
        </h2>
        {description && (
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>{description}</p>
        )}
      </div>
      <div
        className="shell-stat-grid"
        style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}
      >
        {children}
      </div>
    </section>
  )
}
