import Card from './Card'
import type { IconComponent } from './icon-type'

type Accent = 'default' | 'green' | 'amber' | 'red' | 'blue' | 'purple'

const ACCENT_COLOR: Record<Accent, string> = {
  default: 'var(--accent)',
  green: 'var(--green)',
  amber: 'var(--amber)',
  red: 'var(--red)',
  blue: 'var(--blue)',
  purple: 'var(--purple)',
}

interface Props {
  label: string
  value: string | number
  icon?: IconComponent
  accent?: Accent
  /** True when `value` is realistic placeholder data, not a live API
   * result -- per this PR's explicit instruction, placeholder numbers
   * must be clearly labeled, never presented as if they were real so
   * nothing here could be mistaken for a working integration. Renders a
   * small "Preview data" tag; omit once a real API backs this card. */
  placeholder?: boolean
}

/** Admin Console Phase 2 design system: the dashboard's stat tile --
 * label, big number, optional icon, optional "Preview data" tag for
 * modules with no live API yet. */
export default function StatCard({ label, value, icon: Icon, accent = 'default', placeholder }: Props) {
  const color = ACCENT_COLOR[accent]
  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{
          fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--muted)',
        }}>
          {label}
        </span>
        {Icon && <Icon size={16} color={color} />}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>{value}</span>
      </div>
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
