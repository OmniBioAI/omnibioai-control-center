import { Minus, TrendingDown, TrendingUp } from 'lucide-react'
import DashboardCard from './DashboardCard'
import type { IconComponent } from '../ui/icon-type'

export interface Trend {
  direction: 'up' | 'down' | 'flat'
  /** Pre-formatted delta string, e.g. "+12%" or "-3 since yesterday" --
   * this component doesn't compute deltas, it only renders one the
   * caller already has. */
  label: string
  /** Whether "up" is the good direction for this particular metric
   * (e.g. Users trending up is good; Failed Jobs trending up is not) --
   * controls the arrow's color, not its direction. */
  goodDirection?: 'up' | 'down'
}

interface Props {
  label: string
  value: number | string | null
  icon?: IconComponent
  trend?: Trend
  placeholder?: boolean
}

const ARROW = { up: TrendingUp, down: TrendingDown, flat: Minus }

/** PR10 (Live Platform Dashboard): a metric with a trend indicator --
 * built for any future module that has a time-series to compare against
 * (e.g. "Users" week-over-week once usage snapshots exist). No data
 * source in this PR currently has historical/point-in-time snapshots to
 * diff (confirmed by reading every service this dashboard aggregates --
 * none stores one), so `trend` is optional and this card renders
 * identically to MetricCard when omitted; wiring a real trend in is a
 * future module's job once a snapshot table exists somewhere, not
 * something to fabricate here. */
export default function TrendCard({ label, value, icon, trend, placeholder }: Props) {
  const Arrow = trend ? ARROW[trend.direction] : null
  const isGood = trend && trend.direction !== 'flat' && trend.direction === (trend.goodDirection ?? 'up')
  const trendColor = !trend || trend.direction === 'flat' ? 'var(--muted)' : isGood ? 'var(--green)' : 'var(--red)'

  return (
    <DashboardCard label={label} icon={icon} placeholder={placeholder}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>
          {value ?? '—'}
        </span>
      </div>
      {trend && Arrow && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: trendColor }}>
          <Arrow size={12} />
          {trend.label}
        </span>
      )}
    </DashboardCard>
  )
}
