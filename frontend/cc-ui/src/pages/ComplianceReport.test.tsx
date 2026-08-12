import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ComplianceReport from './ComplianceReport'
import * as compliance from '../compliance'
import type { HipaaReport } from '../compliance'
import * as organizations from '../organizations'
import type { PlatformOrgSummary } from '../organizations'

vi.mock('../compliance', async () => {
  const actual = await vi.importActual<typeof import('../compliance')>('../compliance')
  return {
    ...actual,
    fetchHipaaReport: vi.fn(),
    downloadHipaaReportPdf: vi.fn(),
    downloadHipaaReportCsv: vi.fn(),
  }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

const ORG_OPTIONS: PlatformOrgSummary[] = [
  {
    id: 1, name: 'KUMC Research', status: 'active', owner_email: null, member_count: 2, team_count: 0,
    api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false,
    mfa_policy_required: false, mfa_policy_configured: false, created_at: '2026-07-01T00:00:00',
  },
]

const REPORT: HipaaReport = {
  organization_id: 1,
  organization_name: 'KUMC Research',
  from_date: '2026-08-01',
  to_date: '2026-08-31',
  generated_at: '2026-08-11T12:00:00Z',
  generated_by: 'admin@omnibioai.org',
  summary: { total_users: 2, active_users: 1, total_rag_queries: 1, security_incidents: 1 },
  user_access: [
    { user_label: 'alice@kumc.edu', login_count: 5, last_login: '2026-08-20T10:00:00', failed_attempts: 0 },
  ],
  rag_queries: [
    { timestamp: '2026-08-10T09:00:00', user_label: 'alice@kumc.edu', trace_id: 'trace-1' },
  ],
  security_events: [
    { timestamp: '2026-08-13T10:00:00', label: 'Role Assignment Denied', actor_label: 'bob@kumc.edu', outcome: 'deny', event_type: 'role_assignment_denied' },
  ],
  truncated: false,
}

async function selectOrgAndGenerate(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText('Organization'), '1')
  await user.click(screen.getByRole('button', { name: /Generate Report/ }))
}

describe('ComplianceReport', () => {
  beforeEach(() => {
    vi.mocked(compliance.fetchHipaaReport).mockReset()
    vi.mocked(compliance.downloadHipaaReportPdf).mockReset()
    vi.mocked(compliance.downloadHipaaReportCsv).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockResolvedValue({ items: ORG_OPTIONS, total: 1, page: 1, page_size: 100, total_pages: 1 })
  })

  it('loads org options and disables Generate until one is picked', async () => {
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Generate Report/ })).toBeDisabled()
  })

  it('generates and renders the report preview', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockResolvedValue(REPORT)
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())

    await selectOrgAndGenerate(user)

    await waitFor(() => expect(screen.getByText(/KUMC Research \(org #1\)/)).toBeInTheDocument())
    // alice@kumc.edu legitimately appears in both the User Access Log and
    // RAG Query Log tables -- same user, two different sections.
    expect(screen.getAllByText('alice@kumc.edu').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Role Assignment Denied')).toBeInTheDocument()
  })

  it('shows empty-state notes when a section has no rows', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockResolvedValue({
      ...REPORT, user_access: [], rag_queries: [], security_events: [],
    })
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByText('No login activity recorded in this period.')).toBeInTheDocument())
  })

  it('shows a permission-denied state on a 403', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockRejectedValue(new Error('/compliance/hipaa-report 403'))
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByText('Permission denied')).toBeInTheDocument())
  })

  it('shows a generic error state on a non-403 failure', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockRejectedValue(new Error('network error'))
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByText('network error')).toBeInTheDocument())
  })

  it('warns when the report is truncated', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockResolvedValue({ ...REPORT, truncated: true })
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByText('Report may be incomplete')).toBeInTheDocument())
  })

  it('download buttons are disabled until a report is generated', async () => {
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Download PDF/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Download CSV/ })).toBeDisabled()
  })

  it('clicking Download PDF calls downloadHipaaReportPdf with the current filters', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockResolvedValue(REPORT)
    vi.mocked(compliance.downloadHipaaReportPdf).mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /Download PDF/ })).not.toBeDisabled())

    await user.click(screen.getByRole('button', { name: /Download PDF/ }))
    await waitFor(() => expect(compliance.downloadHipaaReportPdf).toHaveBeenCalledWith(
      expect.objectContaining({ orgId: 1 }),
    ))
  })

  it('clicking Download CSV calls downloadHipaaReportCsv and surfaces a failure', async () => {
    vi.mocked(compliance.fetchHipaaReport).mockResolvedValue(REPORT)
    vi.mocked(compliance.downloadHipaaReportCsv).mockRejectedValue(new Error('boom'))
    const user = userEvent.setup()
    render(<ComplianceReport />)
    await waitFor(() => expect(screen.getByRole('option', { name: 'KUMC Research' })).toBeInTheDocument())
    await selectOrgAndGenerate(user)
    await waitFor(() => expect(screen.getByRole('button', { name: /Download CSV/ })).not.toBeDisabled())

    await user.click(screen.getByRole('button', { name: /Download CSV/ }))
    await waitFor(() => expect(screen.getByText(/Download failed: boom/)).toBeInTheDocument())
  })
})
