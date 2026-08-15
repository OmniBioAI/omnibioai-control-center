import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ScheduledJobsPage from './ScheduledJobsPage'

vi.mock('../api', () => ({
  fetchCronJobs: vi.fn(),
  fetchCronJobLog: vi.fn(),
  pauseCronJob: vi.fn(),
  resumeCronJob: vi.fn(),
  updateCronSchedule: vi.fn(),
}))
vi.mock('../auth', () => ({ hasAdminAccess: vi.fn() }))

const JOB = { id: 'coverage-nightly', name: 'Coverage Collection', schedule: '0 2 * * *', paused: false, last_status: 'ok', last_run_at: '2026-08-14T02:00:00Z' }

describe('ScheduledJobsPage', () => {
  beforeEach(async () => {
    const api = await import('../api')
    const auth = await import('../auth')
    vi.mocked(api.fetchCronJobs).mockReset().mockResolvedValue({ jobs: [JOB] } as any)
    vi.mocked(api.fetchCronJobLog).mockReset()
    vi.mocked(api.pauseCronJob).mockReset()
    vi.mocked(api.resumeCronJob).mockReset()
    vi.mocked(api.updateCronSchedule).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset().mockReturnValue(true)
  })

  it('lists jobs from GET /cron/jobs', async () => {
    render(<ScheduledJobsPage />)
    await waitFor(() => expect(screen.getByText('Coverage Collection')).toBeInTheDocument())
    expect(screen.getByText('0 2 * * *')).toBeInTheDocument()
  })

  it('shows Pause/Resume/Save controls for an admin', async () => {
    render(<ScheduledJobsPage />)
    await waitFor(() => expect(screen.getByText('Coverage Collection')).toBeInTheDocument())
    expect(screen.getByText('Pause')).toBeInTheDocument()
    expect(screen.getByText('Save')).toBeInTheDocument()
  })

  it('hides mutation controls for a non-admin -- read-only view stays', async () => {
    const auth = await import('../auth')
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    render(<ScheduledJobsPage />)
    await waitFor(() => expect(screen.getByText('Coverage Collection')).toBeInTheDocument())
    expect(screen.queryByText('Pause')).not.toBeInTheDocument()
    expect(screen.queryByText('Save')).not.toBeInTheDocument()
  })

  it('calls pauseCronJob when Pause is clicked', async () => {
    const api = await import('../api')
    vi.mocked(api.pauseCronJob).mockResolvedValue(undefined)
    render(<ScheduledJobsPage />)
    fireEvent.click(await screen.findByText('Pause'))
    await waitFor(() => expect(api.pauseCronJob).toHaveBeenCalledWith('coverage-nightly'))
  })

  it('loads and displays the job log on View', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchCronJobLog).mockResolvedValue({ lines: ['line one', 'line two'] })
    render(<ScheduledJobsPage />)
    fireEvent.click(await screen.findByText('View'))
    await waitFor(() => expect(screen.getByText(/line one/)).toBeInTheDocument())
  })
})
