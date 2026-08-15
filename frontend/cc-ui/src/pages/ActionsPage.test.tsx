import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ActionsPage from './ActionsPage'

vi.mock('../api', () => ({
  fetchReportStatus: vi.fn(),
  triggerGenerate: vi.fn(),
  fetchCoverageStatus: vi.fn(),
  triggerCoverageGenerate: vi.fn(),
}))

describe('ActionsPage', () => {
  beforeEach(async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportStatus).mockReset().mockResolvedValue({ status: 'idle' } as any)
    vi.mocked(api.fetchCoverageStatus).mockReset().mockResolvedValue({ status: 'idle' } as any)
    vi.mocked(api.triggerGenerate).mockReset().mockResolvedValue(undefined)
    vi.mocked(api.triggerCoverageGenerate).mockReset().mockResolvedValue(undefined)
  })

  it('renders Regenerate Report and Refresh Coverage buttons -- no login form', async () => {
    render(<ActionsPage />)
    await waitFor(() => expect(screen.getByText('↻ Regenerate Report')).toBeInTheDocument())
    expect(screen.getByText('↻ Refresh Coverage')).toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/sign in/i)).not.toBeInTheDocument()
  })

  it('calls triggerGenerate (POST /report/generate) when Regenerate Report is clicked', async () => {
    const api = await import('../api')
    render(<ActionsPage />)
    await waitFor(() => expect(screen.getByText('↻ Regenerate Report')).toBeInTheDocument())
    fireEvent.click(screen.getByText('↻ Regenerate Report'))
    await waitFor(() => expect(api.triggerGenerate).toHaveBeenCalled())
  })

  it('calls triggerCoverageGenerate (POST /coverage/generate) when Refresh Coverage is clicked', async () => {
    const api = await import('../api')
    render(<ActionsPage />)
    await waitFor(() => expect(screen.getByText('↻ Refresh Coverage')).toBeInTheDocument())
    fireEvent.click(screen.getByText('↻ Refresh Coverage'))
    await waitFor(() => expect(api.triggerCoverageGenerate).toHaveBeenCalled())
  })

  it('polls report status until done', async () => {
    const api = await import('../api')
    vi.mocked(api.fetchReportStatus)
      .mockResolvedValueOnce({ status: 'idle' } as any)
      .mockResolvedValueOnce({ status: 'done', message: '' } as any)
    render(<ActionsPage />)
    fireEvent.click(await screen.findByText('↻ Regenerate Report'))
    await waitFor(() => expect(screen.getByText(/Done -- report regenerated/)).toBeInTheDocument())
  })
})
