import { AlertTriangle } from 'lucide-react'
import DashboardCard from './DashboardCard'

interface Props {
  label: string
  /** Count of open/acknowledged alerts. `null` = no source (see
   * routes_dashboard.py); `0` is a real, distinct "all clear" value. */
  count: number | null
  placeholder?: boolean
}

/** PR10 (Live Platform Dashboard): the Operations > Alerts card --
 * visually flags itself (amber icon/value) whenever count > 0, stays
 * neutral at 0 or unknown, so an admin scanning the dashboard doesn't
 * have to read the number to notice something needs attention. Backed
 * today by control-center's existing Known Issues list (open +
 * acknowledged) -- the closest existing thing to "alerts" in this
 * codebase; a future dedicated alerting module plugs into this same
 * card by supplying a different `count`. */
export default function AlertCard({ label, count, placeholder }: Props) {
  const active = typeof count === 'number' && count > 0
  const color = active ? 'var(--amber)' : count === 0 ? 'var(--green)' : 'var(--muted)'
  return (
    <DashboardCard label={label} icon={AlertTriangle} iconColor={color} placeholder={placeholder}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color, lineHeight: 1 }}>
          {count ?? '—'}
        </span>
      </div>
      {count === 0 && (
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>All clear</span>
      )}
    </DashboardCard>
  )
}
