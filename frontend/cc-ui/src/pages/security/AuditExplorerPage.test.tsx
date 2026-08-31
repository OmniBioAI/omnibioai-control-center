import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import AuditExplorerPage from './AuditExplorerPage'
import * as audit from '../../securityAudit'

vi.mock('../../securityAudit', async () => ({ ...(await vi.importActual<typeof import('../../securityAudit')>('../../securityAudit')), fetchSafeAuditEvents: vi.fn() }))
vi.mock('../../auth', () => ({ hasPlatformAdminAccess: () => true, getSessionUser: () => ({ orgId: null }) }))
vi.mock('../../organizations', () => ({ fetchPlatformOrgs: vi.fn().mockResolvedValue({ items: [] }) }))

const base = { source: 'security_audit', total: 1, page: 1, page_size: 20, total_pages: 1, source_availability: 'AVAILABLE' as const, generated_at: '2026-08-30T10:00:00Z', source_checked_at: '2026-08-30T10:00:00Z', freshness: { status: 'UNKNOWN' }, retention: { status: 'UNKNOWN' }, warnings: [] }

beforeEach(() => vi.mocked(audit.fetchSafeAuditEvents).mockReset())

describe('AuditExplorerPage', () => {
  it('renders loading and available empty states', async () => {
    vi.mocked(audit.fetchSafeAuditEvents).mockReturnValue(new Promise(() => {}))
    render(<AuditExplorerPage />)
    expect(screen.getByText('Loading Security Audit events…')).toBeInTheDocument()
    vi.mocked(audit.fetchSafeAuditEvents).mockResolvedValue({ ...base, total: 0, items: [] })
  })

  it('renders source semantics, normalized integrity, and safe detail metadata', async () => {
    vi.mocked(audit.fetchSafeAuditEvents).mockResolvedValue({ ...base, items: [{ event_id: 'evt-1', timestamp: '2026-08-30T10:00:00Z', organization_id: '7', tenant_scope: 'organization', actor: 'user-1', event_type: 'workflow_execution_denied', action: 'deny', decision: 'deny', integrity: 'invalid', metadata: { trace_id: 'trace-1', request_id: 'req-1', workflow_id: 'wf-1', run_id: 'run-1', resource_type: 'workflow', resource_id: '42', backend: 'workflow-bundles' } }] })
    render(<AuditExplorerPage />)
    expect(await screen.findByText('Workflow Execution Denied')).toBeInTheDocument()
    expect(screen.getAllByText('invalid').length).toBeGreaterThan(1)
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    expect(screen.getByText('workflow-bundles')).toBeInTheDocument()
  })
})
