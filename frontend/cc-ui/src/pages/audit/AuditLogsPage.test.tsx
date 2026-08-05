import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import AuditLogsPage from './AuditLogsPage'
import * as audit from '../../audit'
import type { AuditEvent, AuditEventListResponse } from '../../audit'
import * as organizations from '../../organizations'
import type { PlatformOrgSummary } from '../../organizations'

vi.mock('../../audit', async () => {
  const actual = await vi.importActual<typeof import('../../audit')>('../../audit')
  return { ...actual, fetchAuditEvents: vi.fn() }
})

vi.mock('../../organizations', async () => {
  const actual = await vi.importActual<typeof import('../../organizations')>('../../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

const orgOptions: PlatformOrgSummary[] = [
  { id: 3, name: 'Acme Corp', status: 'active', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, created_at: '2026-07-01T00:00:00' },
]

const apiKeyCreatedEvent: AuditEvent = {
  id: 1, event_type: 'api_key_created', actor_user_id: 7, actor_email: 'owner@acme.test',
  target_user_id: null, target_email: null, organization_id: 3, organization_name: 'Acme Corp',
  resource_type: 'api_key', resource_id: '9',
  before_state: null, after_state: { name: 'CI Pipeline', scopes: ['dataset.read'], status: 'active' },
  metadata: { api_key_name: 'CI Pipeline', scopes: ['dataset.read'] },
  created_at: '2026-08-05T10:00:00',
}

const ssoUpdatedEvent: AuditEvent = {
  id: 2, event_type: 'sso_configuration_updated', actor_user_id: 7, actor_email: 'owner@acme.test',
  target_user_id: null, target_email: null, organization_id: 3, organization_name: 'Acme Corp',
  resource_type: 'organization_sso_config', resource_id: '5',
  before_state: { issuer: 'https://old.example.com', client_id: 'old-client', allowed_domains: [] },
  after_state: { issuer: 'https://new.example.com', client_id: 'new-client', allowed_domains: [] },
  metadata: { provider_type: 'oidc', client_secret: 'should-never-render' },
  created_at: '2026-08-05T11:00:00',
}

// PR11.4c fixture -- deliberately includes a sensitive-looking metadata
// key (client_secret) even though the real backend never writes one
// into an override event; this proves masking generalizes to the new
// event type too, not just the ones PR11.4b's tests already covered.
const overrideCreatedEvent: AuditEvent = {
  id: 3, event_type: 'sso_override_created', actor_user_id: 1, actor_email: 'admin@omnibioai.org',
  target_user_id: null, target_email: null, organization_id: 3, organization_name: 'Acme Corp',
  resource_type: 'organization_sso_config', resource_id: '5',
  before_state: { sso_override_active: false, enforced: true },
  after_state: { sso_override_active: true, enforced: true },
  metadata: {
    action: 'override_created', override_reason: 'IdP outage, unblocking pending fix',
    enforced_before: true, timestamp: '2026-08-05T12:00:00', client_secret: 'should-never-render',
  },
  created_at: '2026-08-05T12:00:00',
}

function listResponse(items: AuditEvent[], overrides: Partial<AuditEventListResponse> = {}): AuditEventListResponse {
  return { items, total: items.length, page: 1, page_size: 20, total_pages: 1, ...overrides }
}

describe('AuditLogsPage', () => {
  beforeEach(() => {
    vi.mocked(audit.fetchAuditEvents).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset().mockResolvedValue({
      items: orgOptions, total: 1, page: 1, page_size: 100, total_pages: 1,
    })
  })

  it('shows a loading state while the events fetch is in flight', async () => {
    vi.mocked(audit.fetchAuditEvents).mockReturnValue(new Promise(() => {}))
    render(<AuditLogsPage />)
    expect(await screen.findByText('Loading audit events…')).toBeInTheDocument()
  })

  it('shows the empty state when no events exist yet', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([]))
    render(<AuditLogsPage />)
    expect(await screen.findByText('No audit events recorded yet.')).toBeInTheDocument()
  })

  it('renders the table with Timestamp/Event/Actor/Organization/Target/Details columns', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([apiKeyCreatedEvent]))
    render(<AuditLogsPage />)

    expect(await screen.findByRole('columnheader', { name: 'Timestamp' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Event' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Actor' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Organization' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Target' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Details' })).toBeInTheDocument()

    expect(screen.getByRole('cell', { name: 'API Key Created' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'owner@acme.test' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Acme Corp' })).toBeInTheDocument()
  })

  it('re-fetches with the organization filter applied when changed', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([apiKeyCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'API Key Created' })

    await user.selectOptions(screen.getByLabelText('Filter by organization'), '3')

    await waitFor(() => expect(audit.fetchAuditEvents).toHaveBeenLastCalledWith(
      expect.objectContaining({ organizationId: 3 }),
    ))
  })

  it('re-fetches with the event type filter applied when changed', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([apiKeyCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'API Key Created' })

    await user.selectOptions(screen.getByLabelText('Filter by event type'), 'api_key_created')

    await waitFor(() => expect(audit.fetchAuditEvents).toHaveBeenLastCalledWith(
      expect.objectContaining({ eventType: 'api_key_created' }),
    ))
  })

  it('re-fetches with the actor filter applied when changed', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([apiKeyCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'API Key Created' })

    await user.type(screen.getByLabelText('Filter by actor user ID'), '7')

    await waitFor(() => expect(audit.fetchAuditEvents).toHaveBeenLastCalledWith(
      expect.objectContaining({ actorUserId: 7 }),
    ))
  })

  it('shows a permission-denied state on a 403, not the table', async () => {
    vi.mocked(audit.fetchAuditEvents).mockRejectedValue(new Error('/platform/audit-events 403'))
    render(<AuditLogsPage />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('Timestamp')).not.toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(audit.fetchAuditEvents).mockRejectedValueOnce(new Error('/platform/audit-events 503'))
    vi.mocked(audit.fetchAuditEvents).mockResolvedValueOnce(listResponse([apiKeyCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('cell', { name: 'API Key Created' })).toBeInTheDocument()
  })

  it('opens the detail modal on "View", showing actor/org/timestamp and before/after state', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([ssoUpdatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'SSO Configuration Updated' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Audit event detail' })
    expect(within(dialog).getByText('https://old.example.com', { exact: false })).toBeInTheDocument()
    expect(within(dialog).getByText('https://new.example.com', { exact: false })).toBeInTheDocument()
  })

  it('masks sensitive-looking fields in the detail view even if one appeared in metadata', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([ssoUpdatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'SSO Configuration Updated' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Audit event detail' })
    expect(within(dialog).queryByText(/should-never-render/)).not.toBeInTheDocument()
    expect(within(dialog).getByText(/••••••••/)).toBeInTheDocument()
  })

  it('closes the detail modal', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([apiKeyCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'API Key Created' })

    await user.click(screen.getByRole('button', { name: 'View →' }))
    expect(screen.getByRole('dialog', { name: 'Audit event detail' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  // ── PR11.4c: break-glass override event rendering ────────────────────

  it('renders a break-glass override event with its friendly label in the table', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([overrideCreatedEvent]))
    render(<AuditLogsPage />)

    expect(await screen.findByRole('cell', { name: 'SSO Break-Glass Override Enabled' })).toBeInTheDocument()
  })

  it('shows the friendly label, description, and unmasked reason in the break-glass event detail', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([overrideCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'SSO Break-Glass Override Enabled' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Audit event detail' })
    expect(within(dialog).getByText('SSO Break-Glass Override Enabled')).toBeInTheDocument()
    expect(within(dialog).getByText(/temporarily allowing password login/)).toBeInTheDocument()
    // A non-sensitive field (override_reason) renders in full...
    expect(within(dialog).getByText(/IdP outage, unblocking pending fix/)).toBeInTheDocument()
  })

  it('still masks sensitive-looking metadata on a break-glass event, same as any other event type', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([overrideCreatedEvent]))
    const user = userEvent.setup()
    render(<AuditLogsPage />)
    await screen.findByRole('cell', { name: 'SSO Break-Glass Override Enabled' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Audit event detail' })
    expect(within(dialog).queryByText(/should-never-render/)).not.toBeInTheDocument()
    expect(within(dialog).getByText(/••••••••/)).toBeInTheDocument()
  })

  it('offers the break-glass event types as filter options with friendly labels', async () => {
    vi.mocked(audit.fetchAuditEvents).mockResolvedValue(listResponse([]))
    render(<AuditLogsPage />)
    await screen.findByText('No audit events recorded yet.')

    const select = screen.getByLabelText('Filter by event type') as HTMLSelectElement
    const optionLabels = Array.from(select.options).map(o => o.text)
    expect(optionLabels).toContain('SSO Break-Glass Override Enabled')
    expect(optionLabels).toContain('SSO Break-Glass Override Removed')
  })
})
