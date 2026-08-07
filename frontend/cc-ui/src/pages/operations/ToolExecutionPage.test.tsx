import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ToolExecutionPage from './ToolExecutionPage'
import * as tes from '../../tes'
import type { RunRecord, ToolSummary, ToolCapability } from '../../tes'

vi.mock('../../tes', async () => {
  const actual = await vi.importActual<typeof import('../../tes')>('../../tes')
  return { ...actual, fetchRuns: vi.fn(), fetchTools: vi.fn(), fetchToolCapabilities: vi.fn() }
})

const runningRun: RunRecord = {
  run_id: 'r-1', tool_id: 'fastqc', server_id: 'slurm-1', state: 'RUNNING',
  organization_id: 3, created_at: '2026-08-05T10:00:00',
}

const tools: ToolSummary[] = [{ tool_id: 'fastqc', name: 'FastQC' }]
const capabilities: ToolCapability[] = [{ tool_id: 'fastqc', backends: ['http', 'slurm'] }]

describe('ToolExecutionPage', () => {
  beforeEach(() => {
    vi.mocked(tes.fetchRuns).mockReset()
    vi.mocked(tes.fetchTools).mockReset().mockResolvedValue(tools)
    vi.mocked(tes.fetchToolCapabilities).mockReset().mockResolvedValue(capabilities)
  })

  it('shows a loading state while runs are in flight', async () => {
    vi.mocked(tes.fetchRuns).mockReturnValue(new Promise(() => {}))
    render(<ToolExecutionPage />)
    expect(await screen.findByText('Loading runs…')).toBeInTheDocument()
  })

  it('shows the empty state when the org has no runs yet', async () => {
    vi.mocked(tes.fetchRuns).mockResolvedValue([])
    render(<ToolExecutionPage />)
    expect(await screen.findByText('No runs for your organization yet.')).toBeInTheDocument()
  })

  it('renders the runs table with Run ID/Tool/State/Server/Created columns', async () => {
    vi.mocked(tes.fetchRuns).mockResolvedValue([runningRun])
    render(<ToolExecutionPage />)

    expect(await screen.findByRole('columnheader', { name: 'Run ID' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Tool' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'State' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Server' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Created' })).toBeInTheDocument()

    expect(screen.getByText('r-1')).toBeInTheDocument()
    expect(screen.getByText('RUNNING')).toBeInTheDocument()
  })

  it('shows permission-denied when the backend 403s', async () => {
    vi.mocked(tes.fetchRuns).mockRejectedValue(new Error('/tes/runs 403'))
    render(<ToolExecutionPage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('No runs for your organization yet.')).not.toBeInTheDocument()
  })

  // PR E2: a 401 must render as a distinct session-issue state, not the
  // same "Permission denied" copy a 403 gets.
  it('shows a session-expired state when the backend 401s, not Permission denied', async () => {
    vi.mocked(tes.fetchRuns).mockRejectedValue(new Error('/tes/runs 401'))
    render(<ToolExecutionPage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
    expect(screen.queryByText('Permission denied')).not.toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(tes.fetchRuns).mockRejectedValueOnce(new Error('/tes/runs 503'))
    vi.mocked(tes.fetchRuns).mockResolvedValueOnce([runningRun])
    const user = userEvent.setup()
    render(<ToolExecutionPage />)

    expect(await screen.findByText('/tes/runs 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByText('r-1')).toBeInTheDocument())
  })

  it('switches to the Tools tab and shows registered tools with their backends', async () => {
    vi.mocked(tes.fetchRuns).mockResolvedValue([])
    const user = userEvent.setup()
    render(<ToolExecutionPage />)
    await screen.findByText('No runs for your organization yet.')

    await user.click(screen.getByRole('button', { name: 'Tools' }))

    expect(await screen.findByText('fastqc')).toBeInTheDocument()
    expect(screen.getByText('FastQC')).toBeInTheDocument()
    expect(screen.getByText('http, slurm')).toBeInTheDocument()
  })
})
