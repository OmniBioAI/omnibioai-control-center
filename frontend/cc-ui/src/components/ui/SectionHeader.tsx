import type { ReactNode } from 'react'

interface Props {
  title: string
  description?: string
  actions?: ReactNode
}

/** Admin Console Phase 2 design system: title + optional description on
 * the left, optional action buttons on the right -- the header every
 * page section in an enterprise console (Azure/AWS/GCP-style) starts
 * with. */
export default function SectionHeader({ title, description, actions }: Props) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      gap: 16, marginBottom: 20,
    }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.01em' }}>
          {title}
        </h1>
        {description && (
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 4 }}>{description}</p>
        )}
      </div>
      {actions && <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>{actions}</div>}
    </div>
  )
}
