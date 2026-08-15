import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import KnownIssuesPage from './KnownIssuesPage'

vi.mock('../api', () => ({
  fetchKnownIssues: vi.fn(),
  createKnownIssue: vi.fn(),
  updateKnownIssueStatus: vi.fn(),
  deleteKnownIssue: vi.fn(),
}))
vi.mock('../auth', () => ({ hasAdminAccess: vi.fn() }))

const ISSUE = { id: 'i1', title: 'GPU throttling', description: 'DGX runs hot', severity: 'high', status: 'open', area: 'GPU / Infra', opened_at: '2026-08-01' }

describe('KnownIssuesPage', () => {
  beforeEach(async () => {
    const api = await import('../api')
    const auth = await import('../auth')
    vi.mocked(api.fetchKnownIssues).mockReset().mockResolvedValue({ issues: [ISSUE] } as any)
    vi.mocked(api.createKnownIssue).mockReset()
    vi.mocked(api.updateKnownIssueStatus).mockReset()
    vi.mocked(api.deleteKnownIssue).mockReset()
    vi.mocked(auth.hasAdminAccess).mockReset().mockReturnValue(true)
  })

  it('lists issues from GET /known-issues', async () => {
    render(<KnownIssuesPage />)
    await waitFor(() => expect(screen.getByText('GPU throttling')).toBeInTheDocument())
    expect(screen.getByText('DGX runs hot')).toBeInTheDocument()
  })

  it('shows the new-issue form and status/delete controls for an admin', async () => {
    render(<KnownIssuesPage />)
    await waitFor(() => expect(screen.getByText('GPU throttling')).toBeInTheDocument())
    expect(screen.getByText('New issue')).toBeInTheDocument()
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('hides the new-issue form and status/delete controls for a non-admin -- read-only view stays', async () => {
    const auth = await import('../auth')
    vi.mocked(auth.hasAdminAccess).mockReturnValue(false)
    render(<KnownIssuesPage />)
    await waitFor(() => expect(screen.getByText('GPU throttling')).toBeInTheDocument())
    expect(screen.queryByText('New issue')).not.toBeInTheDocument()
    expect(screen.queryByText('Delete')).not.toBeInTheDocument()
  })

  it('calls createKnownIssue when Add issue is submitted', async () => {
    const api = await import('../api')
    vi.mocked(api.createKnownIssue).mockResolvedValue(ISSUE as any)
    render(<KnownIssuesPage />)
    await waitFor(() => expect(screen.getByText('New issue')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText('title'), { target: { value: 'New thing broke' } })
    fireEvent.click(screen.getByText('Add issue'))
    await waitFor(() => expect(api.createKnownIssue).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'New thing broke' })
    ))
  })

  it('calls deleteKnownIssue when Delete is confirmed', async () => {
    const api = await import('../api')
    vi.mocked(api.deleteKnownIssue).mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(<KnownIssuesPage />)
    fireEvent.click(await screen.findByText('Delete'))
    await waitFor(() => expect(api.deleteKnownIssue).toHaveBeenCalledWith('i1'))
    vi.unstubAllGlobals()
  })
})
