import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import WorkflowsPage from './WorkflowsPage'
import * as workflows from '../../workflows'
import type { WorkflowRow, CategoryStat, WorkflowRun } from '../../workflows'

vi.mock('../../workflows', async () => {
  const actual = await vi.importActual<typeof import('../../workflows')>('../../workflows')
  return { ...actual, fetchWorkflows: vi.fn(), fetchCategories: vi.fn(), fetchRuns: vi.fn() }
})

const starSalmon: WorkflowRow = {
  id: 1, category: 'rnaseq', engine: 'nextflow', name: 'star-salmon',
  display_name: 'STAR + Salmon RNA-seq', version: '1.0.0', entrypoint: 'main.nf',
  object_id: 'obj-1', enabled: true, created_at: '2026-07-01T00:00:00',
}

const categories: CategoryStat[] = [{ category: 'rnaseq', count: 3, enabled_count: 2 }]

// Deliberately spans two organizations -- GET /v1/runs has no
// org-scoping upstream, and this page must render exactly what's
// returned, not filter it.
const multiOrgRuns: WorkflowRun[] = [
  { run_id: 'r-1', workflow_id: 1, workflow_name: 'star-salmon', status: 'running', engine: 'nextflow', requested_by: 'u-1', organization_id: 3, started_at: '2026-08-05T10:00:00' },
  { run_id: 'r-2', workflow_id: 2, workflow_name: 'other-pipeline', status: 'success', engine: 'nextflow', requested_by: 'u-9', organization_id: 7, started_at: '2026-08-05T09:00:00' },
]

describe('WorkflowsPage', () => {
  beforeEach(() => {
    vi.mocked(workflows.fetchWorkflows).mockReset()
    vi.mocked(workflows.fetchCategories).mockReset().mockResolvedValue(categories)
    vi.mocked(workflows.fetchRuns).mockReset()
  })

  it('shows a loading state while workflows are in flight', async () => {
    vi.mocked(workflows.fetchWorkflows).mockReturnValue(new Promise(() => {}))
    render(<WorkflowsPage />)
    expect(await screen.findByText('Loading workflows…')).toBeInTheDocument()
  })

  it('shows the empty state when no workflows are registered yet', async () => {
    vi.mocked(workflows.fetchWorkflows).mockResolvedValue([])
    render(<WorkflowsPage />)
    expect(await screen.findByText('No workflows registered yet.')).toBeInTheDocument()
  })

  it('renders the Workflows tab with Name/Category/Engine/Version/Enabled columns', async () => {
    vi.mocked(workflows.fetchWorkflows).mockResolvedValue([starSalmon])
    render(<WorkflowsPage />)

    expect(await screen.findByRole('columnheader', { name: 'Name' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Category' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Engine' })).toBeInTheDocument()
    expect(screen.getByText('STAR + Salmon RNA-seq')).toBeInTheDocument()
    expect(screen.getByText('rnaseq')).toBeInTheDocument()
  })

  it('shows permission-denied when the backend 403s', async () => {
    vi.mocked(workflows.fetchWorkflows).mockRejectedValue(new Error('/workflow-bundles/workflows 403'))
    render(<WorkflowsPage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('No workflows registered yet.')).not.toBeInTheDocument()
  })

  it('shows a generic error with retry on other failures', async () => {
    vi.mocked(workflows.fetchWorkflows).mockRejectedValueOnce(new Error('/workflow-bundles/workflows 503'))
    vi.mocked(workflows.fetchWorkflows).mockResolvedValueOnce([starSalmon])
    const user = userEvent.setup()
    render(<WorkflowsPage />)

    expect(await screen.findByText('/workflow-bundles/workflows 503')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => expect(screen.getByText('STAR + Salmon RNA-seq')).toBeInTheDocument())
  })

  it('switches to the Categories tab and shows category stats', async () => {
    vi.mocked(workflows.fetchWorkflows).mockResolvedValue([])
    const user = userEvent.setup()
    render(<WorkflowsPage />)
    await screen.findByText('No workflows registered yet.')

    await user.click(screen.getByRole('button', { name: 'Categories' }))

    expect(await screen.findByText('rnaseq')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Total Workflows' })).toBeInTheDocument()
  })

  describe('Runs tab', () => {
    it('shows the upstream-limitation notice and renders runs from multiple organizations unfiltered', async () => {
      vi.mocked(workflows.fetchWorkflows).mockResolvedValue([])
      vi.mocked(workflows.fetchRuns).mockResolvedValue(multiOrgRuns)
      const user = userEvent.setup()
      render(<WorkflowsPage />)
      await screen.findByText('No workflows registered yet.')

      await user.click(screen.getByRole('button', { name: 'Runs' }))

      // The explicit upstream-limitation banner must be present.
      expect(await screen.findByText(/does not yet enforce organization-level filtering/)).toBeInTheDocument()
      expect(screen.getByText(/not an Admin Console bug/)).toBeInTheDocument()

      // Both organizations' runs render -- no client-side filtering.
      expect(screen.getByRole('cell', { name: 'Org #3' })).toBeInTheDocument()
      expect(screen.getByRole('cell', { name: 'Org #7' })).toBeInTheDocument()
      expect(screen.getByText('u-1')).toBeInTheDocument()
      expect(screen.getByText('u-9')).toBeInTheDocument()
    })

    it('shows the empty state (with the notice still present) when there are no runs', async () => {
      vi.mocked(workflows.fetchWorkflows).mockResolvedValue([])
      vi.mocked(workflows.fetchRuns).mockResolvedValue([])
      const user = userEvent.setup()
      render(<WorkflowsPage />)
      await screen.findByText('No workflows registered yet.')

      await user.click(screen.getByRole('button', { name: 'Runs' }))

      expect(await screen.findByText('No workflow runs recorded yet.')).toBeInTheDocument()
      expect(screen.getByText(/does not yet enforce organization-level filtering/)).toBeInTheDocument()
    })

    it('shows permission-denied (with the notice still present) when the backend 403s', async () => {
      vi.mocked(workflows.fetchWorkflows).mockResolvedValue([])
      vi.mocked(workflows.fetchRuns).mockRejectedValue(new Error('/workflow-bundles/runs 403'))
      const user = userEvent.setup()
      render(<WorkflowsPage />)
      await screen.findByText('No workflows registered yet.')

      await user.click(screen.getByRole('button', { name: 'Runs' }))

      expect(await screen.findByText('Permission denied')).toBeInTheDocument()
      expect(screen.getByText(/does not yet enforce organization-level filtering/)).toBeInTheDocument()
    })
  })
})
