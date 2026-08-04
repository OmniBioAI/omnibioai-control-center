import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { Users } from 'lucide-react'
import HealthCard from './HealthCard'
import AlertCard from './AlertCard'
import TrendCard from './TrendCard'

describe('HealthCard', () => {
  it.each([
    ['UP', 'Healthy'],
    ['WARN', 'Degraded'],
    ['DOWN', 'Down'],
  ] as const)('renders %s as "%s"', (status, label) => {
    render(<HealthCard label="Health" status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('renders "Unknown" (not a fabricated status) when status is null', () => {
    render(<HealthCard label="Health" status={null} />)
    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })
})

describe('AlertCard', () => {
  it('shows the count when active alerts exist', () => {
    render(<AlertCard label="Alerts" count={3} />)
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.queryByText('All clear')).not.toBeInTheDocument()
  })

  it('shows "All clear" for a real, distinct zero -- not the same as unknown', () => {
    render(<AlertCard label="Alerts" count={0} />)
    expect(screen.getByText('0')).toBeInTheDocument()
    expect(screen.getByText('All clear')).toBeInTheDocument()
  })

  it('renders "--" (not 0, not "All clear") when count is null', () => {
    render(<AlertCard label="Alerts" count={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(screen.queryByText('All clear')).not.toBeInTheDocument()
  })
})

describe('TrendCard', () => {
  it('renders the value alone when no trend is supplied', () => {
    render(<TrendCard label="Users" value={246} icon={Users} />)
    expect(screen.getByText('246')).toBeInTheDocument()
  })

  it('renders the trend label when supplied', () => {
    render(<TrendCard label="Users" value={246} trend={{ direction: 'up', label: '+12 this week' }} />)
    expect(screen.getByText('+12 this week')).toBeInTheDocument()
  })

  it('treats "up" as good by default (e.g. Users growing)', () => {
    render(<TrendCard label="Users" value={246} trend={{ direction: 'up', label: '+12' }} />)
    const trendText = screen.getByText('+12')
    expect(trendText).toHaveStyle({ color: 'var(--green)' })
  })

  it('treats "up" as bad when goodDirection is down (e.g. Failed Jobs rising)', () => {
    render(<TrendCard label="Failed Jobs" value={5} trend={{ direction: 'up', label: '+2', goodDirection: 'down' }} />)
    const trendText = screen.getByText('+2')
    expect(trendText).toHaveStyle({ color: 'var(--red)' })
  })
})
