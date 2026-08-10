import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import InteractionsPage from './InteractionsPage'
import * as interactions from '../interactions'
import type { Interaction, InteractionListResponse } from '../interactions'
import * as organizations from '../organizations'
import type { PlatformOrgSummary } from '../organizations'

vi.mock('../interactions', async () => {
  const actual = await vi.importActual<typeof import('../interactions')>('../interactions')
  return { ...actual, fetchInteractions: vi.fn() }
})

vi.mock('../organizations', async () => {
  const actual = await vi.importActual<typeof import('../organizations')>('../organizations')
  return { ...actual, fetchPlatformOrgs: vi.fn() }
})

const orgOptions: PlatformOrgSummary[] = [
  { id: 3, name: 'Acme Corp', status: 'active', owner_email: null, member_count: 1, team_count: 0, api_key_count: 0, oauth_client_count: 0, license_count: 0, sso_enabled: false, mfa_policy_required: false, mfa_policy_configured: false, created_at: '2026-07-01T00:00:00' },
]

const ragQueryInteraction: Interaction = {
  id: 1, interaction_id: 'becbce38-0ada-427c-a29c-4c1bdfd95095',
  organization_id: 3, user_id: 630, session_id: null, trace_id: 'trace-1',
  service: 'rag', interaction_type: 'query', action: 'rag.query',
  resource_type: 'study', resource_id: 'default', status: 'success', decision: null,
  metadata: { mode: 'rag', top_k: 3 },
  created_at: '2026-08-10T01:41:38',
}

// Deliberately includes a sensitive-looking metadata key even though the
// real backend (interaction_service.py's own _redact_metadata, reused
// by app/workers/interaction_consumer.py) never writes one into a
// persisted Interaction's metadata -- proves this page's own
// defense-in-depth masking layer works, same reasoning
// AuditLogsPage.test.tsx's own overrideCreatedEvent fixture gives.
const secretShapedInteraction: Interaction = {
  id: 2, interaction_id: '11111111-2222-3333-4444-555555555555',
  organization_id: 3, user_id: 631, session_id: null, trace_id: 'trace-2',
  service: 'rag', interaction_type: 'query', action: 'rag.query',
  resource_type: 'study', resource_id: 'default', status: 'error', decision: null,
  metadata: { mode: 'rag', client_secret: 'should-never-render' },
  created_at: '2026-08-10T02:00:00',
}

function listResponse(items: Interaction[], overrides: Partial<InteractionListResponse> = {}): InteractionListResponse {
  return { items, total: items.length, page: 1, page_size: 20, total_pages: 1, ...overrides }
}

describe('InteractionsPage', () => {
  beforeEach(() => {
    vi.mocked(interactions.fetchInteractions).mockReset()
    vi.mocked(organizations.fetchPlatformOrgs).mockReset().mockResolvedValue({
      items: orgOptions, total: 1, page: 1, page_size: 100, total_pages: 1,
    })
  })

  it('shows a loading state while the interactions fetch is in flight', async () => {
    vi.mocked(interactions.fetchInteractions).mockReturnValue(new Promise(() => {}))
    render(<InteractionsPage />)
    expect(await screen.findByText('Loading interactions…')).toBeInTheDocument()
  })

  it('shows the empty state when no interactions exist yet', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([]))
    render(<InteractionsPage />)
    expect(await screen.findByText('No interactions recorded yet.')).toBeInTheDocument()
  })

  it('renders the table with Interaction Type/Action/Status/Organization/User/Details columns', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    render(<InteractionsPage />)

    expect(await screen.findByRole('columnheader', { name: 'Interaction Type' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Action' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Status' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Organization' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'User' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Details' })).toBeInTheDocument()

    expect(screen.getByRole('cell', { name: 'query' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'rag.query' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'success' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'Org #3' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'User #630' })).toBeInTheDocument()
  })

  it('re-fetches with the organization filter applied when changed', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.selectOptions(screen.getByLabelText('Filter by organization'), '3')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ organizationId: 3 }),
    ))
  })

  it('re-fetches with the user filter applied when changed', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.type(screen.getByLabelText('Filter by user ID'), '630')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ userId: 630 }),
    ))
  })

  it('re-fetches with the service filter applied when changed', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.type(screen.getByLabelText('Filter by service'), 'rag')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ service: 'rag' }),
    ))
  })

  it('re-fetches with the interaction type filter applied when changed', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.type(screen.getByLabelText('Filter by interaction type'), 'query')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ interactionType: 'query' }),
    ))
  })

  it('re-fetches with the status filter applied when changed', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.type(screen.getByLabelText('Filter by status'), 'success')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'success' }),
    ))
  })

  it('re-fetches with multiple filters applied together', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.selectOptions(screen.getByLabelText('Filter by organization'), '3')
    await user.type(screen.getByLabelText('Filter by service'), 'rag')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ organizationId: 3, service: 'rag' }),
    ))
  })

  it('resets to page 1 after a filter changes', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(
      listResponse([ragQueryInteraction], { page: 2, total_pages: 3, total: 41 }),
    )
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.selectOptions(screen.getByLabelText('Filter by organization'), '3')

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, organizationId: 3 }),
    ))
  })

  it('clears all filters and reloads unfiltered', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.type(screen.getByLabelText('Filter by service'), 'rag')
    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({ service: 'rag' }),
    ))

    await user.click(screen.getByRole('button', { name: 'Clear filters' }))

    await waitFor(() => expect(interactions.fetchInteractions).toHaveBeenLastCalledWith(
      expect.objectContaining({
        organizationId: undefined, userId: undefined, service: undefined,
        interactionType: undefined, status: undefined, startDate: undefined, endDate: undefined,
      }),
    ))
  })

  it('shows pagination controls reflecting the response', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(
      listResponse([ragQueryInteraction], { page: 2, total_pages: 3, total: 41 }),
    )
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })
    expect(screen.getByText(/Page/)).toBeInTheDocument()
    expect(screen.getByText('2', { selector: 'span' })).toBeInTheDocument()
  })

  it('shows a permission-denied state on a 403, not the table', async () => {
    vi.mocked(interactions.fetchInteractions).mockRejectedValue(new Error('/platform/interactions 403'))
    render(<InteractionsPage />)

    expect(await screen.findByText('Permission denied')).toBeInTheDocument()
    expect(screen.queryByText('Interaction Type')).not.toBeInTheDocument()
  })

  it('shows an error state with retry for an unexpected failure', async () => {
    vi.mocked(interactions.fetchInteractions).mockRejectedValueOnce(new Error('/platform/interactions 503'))
    vi.mocked(interactions.fetchInteractions).mockResolvedValueOnce(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)

    expect(await screen.findByText('Error')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('cell', { name: 'query' })).toBeInTheDocument()
  })

  it('opens the detail modal on "View", showing all key fields', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Interaction detail' })
    expect(within(dialog).getByText(ragQueryInteraction.interaction_id)).toBeInTheDocument()
    expect(within(dialog).getByText('trace-1')).toBeInTheDocument()
    expect(within(dialog).getByText('rag.query')).toBeInTheDocument()
    expect(within(dialog).getByText('study #default')).toBeInTheDocument()
    expect(within(dialog).getByText('User #630')).toBeInTheDocument()
    expect(within(dialog).getByText('Org #3')).toBeInTheDocument()
  })

  it('renders metadata as pretty-printed JSON in the detail view', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Interaction detail' })
    expect(within(dialog).getByText(/"mode": "rag"/)).toBeInTheDocument()
    expect(within(dialog).getByText(/"top_k": 3/)).toBeInTheDocument()
  })

  it('closes the detail modal', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([ragQueryInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'query' })

    await user.click(screen.getByRole('button', { name: 'View →' }))
    expect(screen.getByRole('dialog', { name: 'Interaction detail' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('masks sensitive-looking metadata keys in the detail view', async () => {
    vi.mocked(interactions.fetchInteractions).mockResolvedValue(listResponse([secretShapedInteraction]))
    const user = userEvent.setup()
    render(<InteractionsPage />)
    await screen.findByRole('cell', { name: 'error' })

    await user.click(screen.getByRole('button', { name: 'View →' }))

    const dialog = screen.getByRole('dialog', { name: 'Interaction detail' })
    expect(within(dialog).queryByText(/should-never-render/)).not.toBeInTheDocument()
    expect(within(dialog).getByText(/••••••••/)).toBeInTheDocument()
  })
})
