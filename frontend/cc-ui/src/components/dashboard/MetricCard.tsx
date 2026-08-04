import DashboardCard from './DashboardCard'
import type { IconComponent } from '../ui/icon-type'

interface Props {
  label: string
  /** `null` renders as "--" (no live source yet), never a fabricated 0. */
  value: number | string | null
  icon?: IconComponent
  iconColor?: string
  placeholder?: boolean
  /** Optional small secondary line under the number, e.g. "of 18 total". */
  sublabel?: string
}

/** PR10 (Live Platform Dashboard): the plain number metric card --
 * Organizations: 18, Users: 246, Registered Models: 118, etc. Direct
 * successor to Phase 2's ui/StatCard for dashboard use specifically;
 * ui/StatCard itself is untouched and still available for non-dashboard
 * pages. */
export default function MetricCard({ label, value, icon, iconColor, placeholder, sublabel }: Props) {
  return (
    <DashboardCard label={label} icon={icon} iconColor={iconColor} placeholder={placeholder}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>
          {value ?? '—'}
        </span>
      </div>
      {sublabel && (
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{sublabel}</span>
      )}
    </DashboardCard>
  )
}
