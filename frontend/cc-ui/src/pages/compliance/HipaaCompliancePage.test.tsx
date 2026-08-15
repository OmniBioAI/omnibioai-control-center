import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import HipaaCompliancePage from './HipaaCompliancePage'
import * as hipaaCompliance from '../../hipaaCompliance'
import type {
  HipaaComplianceSummary, HipaaComplianceChange, HipaaComplianceChangeListResponse,
} from '../../hipaaCompliance'

vi.mock('../../hipaaCompliance', async () => {
  const actual = await vi.importActual<typeof import('../../hipaaCompliance')>('../../hipaaCompliance')
  return {
    ...actual,
    fetchHipaaComplianceSummary: vi.fn(),
    fetchHipaaComplianceChanges: vi.fn(),
  }
})

const SUMMARY: HipaaComplianceSummary = {
  overall_status: 'attention_needed',
  total_controls_tracked: 3,
  verified_count: 3,
  pending_count: 0,
  exception_count: 1,
  latest_change_id: 'CC-PR46',
  latest_change_title: 'HIPAA PR3d',
  latest_change_date: '2026-08-15',
  controls: [
    { category: 'audit_event_signing', label: 'Audit Event Signing', total: 1, verified: 1, pending: 0, exceptions: 0 },
    { category: 'audit_event_verification', label: 'Audit Event Verification', total: 3, verified: 2, pending: 0, exceptions: 1 },
    { category: 'access_control', label: 'Access Control', total: 0, verified: 0, pending: 0, exceptions: 0 },
  ],
}

const CHANGE: HipaaComplianceChange = {
  change_id: 'CC-PR45',
  title: 'HIPAA PR3c: verify audit event integrity in Control Center',
  change_date: '2026-08-15',
  repository: 'omnibioai-control-center',
  branch: 'feat/hipaa-pr3c-audit-integrity',
  commit_sha: '80ea65081408cd1166d6a13738efe893405ded93',
  pr_number: 45,
  description: 'Verifies audit event signatures locally.',
  control_category: 'audit_event_verification',
  affected_component: 'checks/audit_trail.py',
  status: 'released',
  verification_result: '1323/1323 passed, 0 regressions',
  reviewer: null,
  evidence: [
    { type: 'github_pr', label: 'omnibioai-control-center#45', url: 'https://github.com/OmniBioAI/omnibioai-control-center/pull/45' },
    { type: 'test_suite', label: '1323/1323 passed' },
  ],
  notes: 'Self-authored and self-merged; no formal GitHub PR review recorded.',
  created_at: '2026-08-15T02:38:07Z',
  updated_at: '2026-08-15T02:38:07Z',
}

function listResponse(items: HipaaComplianceChange[], overrides: Partial<HipaaComplianceChangeListResponse> = {}): HipaaComplianceChangeListResponse {
  return { items, total: items.length, page: 1, page_size: 20, total_pages: 1, ...overrides }
}

describe('HipaaCompliancePage', () => {
  beforeEach(() => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockReset()
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockReset()
  })

  it('renders the Compliance Overview tab by default with real summary data', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    render(<HipaaCompliancePage />)

    expect(await screen.findByText('Attention needed')).toBeInTheDocument()
    expect(screen.getAllByText('3').length).toBeGreaterThan(0) // Controls Tracked / Verified
    expect(screen.getByText('HIPAA PR3d')).toBeInTheDocument()
    expect(screen.getByText(/CC-PR46/)).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockRejectedValue(new Error('/hipaa-compliance/changes/summary 403'))
    render(<HipaaCompliancePage />)
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  it('shows a session-expired state on a 401', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockRejectedValue(new Error('/hipaa-compliance/changes/summary 401'))
    render(<HipaaCompliancePage />)
    expect(await screen.findByText('Session expired')).toBeInTheDocument()
  })

  it('shows "No compliance changes recorded yet." when there is no latest change', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue({
      ...SUMMARY, latest_change_id: null, latest_change_title: null, latest_change_date: null,
    })
    render(<HipaaCompliancePage />)
    expect(await screen.findByText('No compliance changes recorded yet.')).toBeInTheDocument()
  })

  it('switches to the Compliance Controls tab and shows the full fixed taxonomy, including zero-count categories', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    render(<HipaaCompliancePage />)
    await screen.findByText('Attention needed')

    await userEvent.click(screen.getByText('Compliance Controls'))

    expect(await screen.findByText('Audit Event Verification')).toBeInTheDocument()
    expect(screen.getByText('Access Control')).toBeInTheDocument() // 0-count category still shown
  })

  it('switches to the Change History tab and lists changes with a status badge', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockResolvedValue(listResponse([CHANGE]))
    render(<HipaaCompliancePage />)
    await screen.findByText('Attention needed')

    await userEvent.click(screen.getByText('Change History'))

    expect(await screen.findByText('HIPAA PR3c: verify audit event integrity in Control Center')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('Released')).toBeInTheDocument()
  })

  it('opens the detail modal with evidence when "View" is clicked', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockResolvedValue(listResponse([CHANGE]))
    render(<HipaaCompliancePage />)
    await userEvent.click(screen.getByText('Change History'))
    await screen.findByText('HIPAA PR3c: verify audit event integrity in Control Center')

    await userEvent.click(screen.getByText('View →'))

    expect(await screen.findByRole('dialog', { name: 'HIPAA compliance change detail' })).toBeInTheDocument()
    expect(screen.getByText('omnibioai-control-center#45')).toBeInTheDocument()
    expect(screen.getByText('#45')).toBeInTheDocument()
  })

  it('filters change history by status', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockResolvedValue(listResponse([CHANGE]))
    render(<HipaaCompliancePage />)
    await userEvent.click(screen.getByText('Change History'))
    await screen.findByText('HIPAA PR3c: verify audit event integrity in Control Center')

    await userEvent.selectOptions(screen.getByLabelText('Filter by status'), 'released')

    await waitFor(() => {
      const lastCall = vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mock.calls.at(-1)?.[0]
      expect(lastCall?.status).toBe('released')
    })
  })

  it('shows the change-history permission-denied state on a 403', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockRejectedValue(new Error('/hipaa-compliance/changes 403'))
    render(<HipaaCompliancePage />)
    await userEvent.click(screen.getByText('Change History'))
    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
  })

  it('shows the empty state when no changes match the current filters', async () => {
    vi.mocked(hipaaCompliance.fetchHipaaComplianceSummary).mockResolvedValue(SUMMARY)
    vi.mocked(hipaaCompliance.fetchHipaaComplianceChanges).mockResolvedValue(listResponse([]))
    render(<HipaaCompliancePage />)
    await userEvent.click(screen.getByText('Change History'))
    expect(await screen.findByText('No HIPAA compliance changes recorded yet.')).toBeInTheDocument()
  })
})
