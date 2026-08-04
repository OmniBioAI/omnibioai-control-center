import type { ReactNode } from 'react'
import Card from '../ui/Card'
import type { IconComponent } from '../ui/icon-type'

interface Props {
  label: string
  icon?: IconComponent
  iconColor?: string
  /** True when the card's content is realistic preview data, not a live
   * API result -- renders the same "Preview data" tag StatCard already
   * established in Phase 2, so nothing here can be mistaken for a
   * working integration. */
  placeholder?: boolean
  children: ReactNode
}

/** PR10 (Live Platform Dashboard): the shared chrome -- label row with an
 * optional icon, an optional "Preview data" tag, a body slot -- every
 * other dashboard widget (MetricCard, HealthCard, TrendCard, AlertCard,
 * StatusCard) is built on top of, so the five of them can't drift into
 * five slightly-different card shells. Every future dashboard module
 * plugs into one of those five, not into this file directly. */
export default function DashboardCard({ label, icon: Icon, iconColor, placeholder, children }: Props) {
  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{
          fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--muted)',
        }}>
          {label}
        </span>
        {Icon && <Icon size={16} color={iconColor ?? 'var(--accent)'} />}
      </div>
      {children}
      {placeholder && (
        <span style={{
          alignSelf: 'flex-start', fontSize: 10, fontWeight: 600,
          color: 'var(--muted)', background: 'var(--bg3)',
          borderRadius: 99, padding: '2px 8px',
        }}>
          Preview data
        </span>
      )}
    </Card>
  )
}
