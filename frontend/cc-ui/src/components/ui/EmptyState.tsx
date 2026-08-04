import type { ReactNode } from 'react'
import type { IconComponent } from './icon-type'

interface Props {
  icon?: IconComponent
  title: string
  description?: string
  action?: ReactNode
}

/** Admin Console Phase 2 design system: the generic "nothing here"
 * state -- used directly for empty lists, and as the base ComingSoon
 * builds on for unimplemented modules. */
export default function EmptyState({ icon: Icon, title, description, action }: Props) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center',
      gap: 8, padding: '48px 24px', color: 'var(--muted)',
    }}>
      {Icon && <Icon size={32} color="var(--muted)" />}
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text2)', marginTop: 4 }}>{title}</div>
      {description && <div style={{ fontSize: 12, maxWidth: 380 }}>{description}</div>}
      {action && <div style={{ marginTop: 8 }}>{action}</div>}
    </div>
  )
}
